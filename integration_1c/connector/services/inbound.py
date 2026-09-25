from __future__ import annotations

import logging

from connector import repo
from connector.contract import REQUEST_EVENTS, WebhookEnvelope
from connector.profile import FieldRef
from connector.services import attachments, documents, outbound
from connector.state import AppState

logger = logging.getLogger("onec_connector.inbound")

_TERMINAL_STATUSES = {"closed", "cancelled"}
_TRACKED_ASSIGNMENT_STATES = {"pending", "accepted"}


async def handle_event(state: AppState, envelope: WebhookEnvelope) -> None:
    if envelope.type in REQUEST_EVENTS:
        await handle_request(
            state,
            envelope.resource_id,
            hint_version=envelope.resource_version,
            with_messages=envelope.type == "message.created",
        )
    elif envelope.type == "assignment.revoked":
        await _handle_revoked(state, envelope)
    else:
        logger.info("событие %s не относится к документам 1С", envelope.type)


async def handle_request(
    state: AppState,
    request_id: str,
    *,
    hint_version: int | None = None,
    with_messages: bool = False,
) -> None:
    async with state.lock_for(request_id):
        link = repo.get_link(state.conn, request_id)
        if (
            link is not None
            and hint_version is not None
            and hint_version <= int(link["applied_version"])
            and not with_messages
        ):
            logger.info(
                "событие версии %s заявки %s не новее применённой", hint_version, request_id
            )
            return

        card = await state.client.get_request(request_id)
        if "status" not in card:
            logger.info("заявка %s: назначение прекращено, карточка недоступна", request_id)
            return

        version = int(card["version"])
        if link is None:
            assignment_state = card["assignment"]["state"]
            if version <= 0:
                logger.info("заявка %s: карточка без версии, документ не создаётся", request_id)
                return
            if assignment_state not in _TRACKED_ASSIGNMENT_STATES:
                logger.info(
                    "заявка %s: назначение в состоянии %s, документ не создаётся",
                    request_id,
                    assignment_state,
                )
                return
            card = await documents.create_document(state, card)
            with_messages = True
        else:
            if version < int(link["applied_version"]):
                logger.info(
                    "заявка %s: прочитана версия %s старше применённой %s",
                    request_id,
                    version,
                    link["applied_version"],
                )
                return
            if int(link["applied_version"]) == 0:
                with_messages = True
            card = await documents.ensure_external_reference(state, request_id, card)
            await documents.update_document(
                state, str(link["ref_key"]), card, with_messages=with_messages
            )
            with_messages = False

        link = repo.get_link(state.conn, request_id)
        if link is None:
            raise RuntimeError(f"заявка {request_id}: связь с документом 1С не сохранилась")
        ref_key = str(link["ref_key"])
        if with_messages:
            await documents.update_document(state, ref_key, card, with_messages=True)
        await attachments.sync_to_onec(state, request_id, ref_key, card)
        repo.update_link_card(state.conn, request_id, card)
        version = int(card.get("version") or 0)
        if card.get("status") in _TERMINAL_STATUSES:
            repo.mark_link_applied(state.conn, request_id, version)
            repo.deactivate_link(state.conn, request_id)
            return
        await outbound.evaluate_locked(state, request_id)
        repo.mark_link_applied(state.conn, request_id, version)


async def _handle_revoked(state: AppState, envelope: WebhookEnvelope) -> None:
    """Назначение прекращено (ТЗ 14): карточка больше не читается, документ 1С
    помечается состоянием из профиля и перестаёт отслеживаться."""
    request_id = str(envelope.data.get("request_id") or "")
    link = repo.get_link(state.conn, request_id) if request_id else None
    if link is None:
        return
    async with state.lock_for(request_id):
        profile = state.profile
        entity = profile.document.entity
        ref_key = str(link["ref_key"])
        doc = await state.onec.get(entity, ref_key)
        if doc is not None:
            values: dict[FieldRef, str] = {}
            reason = str(envelope.data.get("reason_kind") or "")
            if profile.exchange_status is not None:
                values[profile.exchange_status] = f"Назначение прекращено платформой ({reason})"
            body = await state.directory.build_patch(doc, values)
            revoked_state = profile.state.inbound.get("revoked")
            if revoked_state is not None:
                body[profile.state.attribute] = await state.directory.state_value(revoked_state)
            if body:
                await state.onec.update(entity, ref_key, body)
        repo.deactivate_link(state.conn, request_id)
