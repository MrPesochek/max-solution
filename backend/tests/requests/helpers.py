import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core import ids
from app.core.clock import utcnow
from app.db import session as db_session
from app.db.models import IntegrationEvent, Notification, RequestPublicCard
from app.modules.requests import api
from tests.requests import factories
from tests.requests.factories import World


def rid(body: dict[str, Any]) -> uuid.UUID:
    return ids.decode("request", body["id"])


def assignment_id(body: dict[str, Any]) -> uuid.UUID:
    return ids.decode("assignment", body["assignment"]["id"])


def proposal_id(body: dict[str, Any], index: int = 0) -> uuid.UUID:
    return ids.decode("visit_proposal", body["visit_proposals"][index]["id"])


def quote_id(body: dict[str, Any], index: int = 0) -> uuid.UUID:
    return ids.decode("repair_quote", body["repair_quotes"][index]["id"])


def cancellation_id(body: dict[str, Any]) -> uuid.UUID:
    return ids.decode("cancellation", body["cancellation"]["id"])


def oid(body: dict[str, Any]) -> uuid.UUID:
    return ids.decode("offer", body["id"])


def hours(value: int) -> timedelta:
    return timedelta(hours=value)


def window_start() -> datetime:
    return utcnow() + timedelta(days=1)


def window_end() -> datetime:
    return utcnow() + timedelta(days=1, hours=3)


def visit_window() -> dict[str, datetime]:
    return {"visit_window_start": window_start(), "visit_window_end": window_end()}


async def public_card(body: dict[str, Any]) -> RequestPublicCard:
    async with db_session.transaction() as session:
        stmt = select(RequestPublicCard).where(RequestPublicCard.request_id == rid(body))
        return (await session.execute(stmt)).scalar_one()


async def make_marketplace_draft(
    world: World, *, equipment_id: uuid.UUID | None = None
) -> dict[str, Any]:
    result = await api.create_draft(
        world.manager,
        equipment_id=equipment_id or world.equipment_id,
        route="marketplace",
        symptom_description="Не держит температуру",
    )
    return result.body


async def make_published(world: World, **card: Any) -> dict[str, Any]:
    draft = await make_marketplace_draft(world)
    result = await api.publish_search(
        world.manager,
        rid(draft),
        data=api.PublicCardInput(**card) if card else None,
        expected_version=draft["version"],
    )
    return result.body


async def make_published_with_rival(world: World) -> tuple[dict[str, Any], World]:
    rival = await factories.build_rival_provider(world)
    published = await make_published(world)
    return published, rival


async def build_world_without_providers() -> World:
    return await factories.build_world(provider_matches=False, category_index=2)


async def make_draft(world: World, *, actor: Any = None) -> dict[str, Any]:
    result = await api.create_draft(
        actor or world.employee,
        equipment_id=world.equipment_id,
        urgency="normal",
        symptom_description="Не держит температуру",
    )
    return result.body


async def make_submitted(world: World) -> dict[str, Any]:
    draft = await make_draft(world)
    result = await api.submit_to_own_service(
        world.employee, rid(draft), expected_version=draft["version"]
    )
    return result.body


async def make_accepted(world: World) -> dict[str, Any]:
    submitted = await make_submitted(world)
    result = await api.accept_assignment(
        world.dispatcher,
        rid(submitted),
        assignment_id=assignment_id(submitted),
        expected_version=submitted["version"],
    )
    return result.body


async def make_scheduled(world: World, *, amount_minor: int | None = 250000) -> dict[str, Any]:
    accepted = await make_accepted(world)
    proposed = (
        await api.propose_visit(
            world.dispatcher,
            rid(accepted),
            assignment_id=assignment_id(accepted),
            data=api.VisitProposalInput(
                **visit_window(), amount_minor=amount_minor, currency="RUB"
            ),
            expected_version=accepted["version"],
        )
    ).body
    approved = await api.approve_visit_proposal(
        world.manager,
        rid(proposed),
        proposal_id=proposal_id(proposed),
        proposal_version=proposed["visit_proposals"][0]["version"],
        expected_version=proposed["version"],
    )
    return approved.body


async def make_in_progress(world: World) -> dict[str, Any]:
    scheduled = await make_scheduled(world)
    result = await api.start_work(
        world.dispatcher,
        rid(scheduled),
        assignment_id=assignment_id(scheduled),
        expected_version=scheduled["version"],
    )
    return result.body


async def make_completion_reported(world: World) -> dict[str, Any]:
    in_progress = await make_in_progress(world)
    result = await api.report_completion(
        world.dispatcher,
        rid(in_progress),
        assignment_id=assignment_id(in_progress),
        outcome="resolved",
        summary="Заменён термостат",
        expected_version=in_progress["version"],
    )
    return result.body


async def make_marketplace_accepted(world: World, *, amount_minor: int = 1000) -> dict[str, Any]:
    published = await make_published(world)
    offer = (
        await api.submit_offer(
            world.dispatcher, rid(published), data=api.OfferInput(amount_minor=amount_minor)
        )
    ).body
    selected = (await api.select_offer(world.manager, rid(published), offer_id=oid(offer))).body
    result = await api.accept_assignment(
        world.dispatcher,
        rid(published),
        assignment_id=assignment_id(selected),
        expected_version=selected["version"],
    )
    return result.body


async def change_provider_and_republish(
    world: World, accepted: dict[str, Any], *, reason: str = "Смена сервиса"
) -> None:
    request_id = rid(accepted)
    current = await api.get_request(world.manager, request_id)
    pending = (
        await api.request_cancellation(
            world.manager,
            request_id,
            target="change_provider",
            reason=reason,
            expected_version=current.version,
        )
    ).body
    await api.respond_cancellation(
        world.dispatcher,
        request_id,
        assignment_id=assignment_id(pending),
        cancellation_id=cancellation_id(pending),
        decision="accept",
        comment="Согласны",
    )
    current = await api.get_request(world.manager, request_id)
    await api.publish_search(world.manager, request_id, expected_version=current.version)


async def select_next_provider(
    world: World, provider: World, request_id: uuid.UUID, *, amount_minor: int = 2000
) -> dict[str, Any]:
    offer = (
        await api.submit_offer(
            provider.dispatcher, request_id, data=api.OfferInput(amount_minor=amount_minor)
        )
    ).body
    return (await api.select_offer(world.manager, request_id, offer_id=oid(offer))).body


async def integration_events(request_id: uuid.UUID | None = None) -> list[IntegrationEvent]:
    async with db_session.transaction() as session:
        stmt = select(IntegrationEvent).order_by(IntegrationEvent.id)
        if request_id is not None:
            stmt = stmt.where(IntegrationEvent.resource_id == request_id)
        return list((await session.execute(stmt)).scalars().all())


async def event_types() -> list[str]:
    async with db_session.transaction() as session:
        stmt = select(IntegrationEvent.event_type).order_by(IntegrationEvent.id)
        return list((await session.execute(stmt)).scalars().all())


async def notifications() -> list[Notification]:
    async with db_session.transaction() as session:
        stmt = select(Notification).order_by(Notification.id)
        return list((await session.execute(stmt)).scalars().all())


async def notification_types() -> list[str]:
    return [n.notification_type for n in await notifications()]


async def count_of(model: Any) -> int:
    async with db_session.transaction() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def reload(model: Any, row_id: uuid.UUID) -> Any:
    async with db_session.transaction() as session:
        return await session.get(model, row_id)
