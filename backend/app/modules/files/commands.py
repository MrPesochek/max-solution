import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.actor import IntegrationActor, UserActor
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.locking import lock_by_id
from app.core.pipeline import CommandContext, CommandResult, Handler
from app.db.enums import (
    AttachmentOwnerKind,
    AttachmentState,
    ModerationStatus,
    ModerationSubjectType,
    VisibilityClass,
)
from app.db.models import (
    Attachment,
    AttachmentVariant,
    Equipment,
    ModerationCase,
    ProviderProfile,
    RepairRequest,
    Review,
    VerificationCase,
)
from app.modules.files import queries, upload
from app.modules.files.storage import get_storage
from app.modules.files.upload import StoredBlob, UploadPlan
from app.modules.files.views import to_attachment_view

MODERATED_CLASSES = (VisibilityClass.PROFILE_PUBLIC, VisibilityClass.REVIEW_PUBLIC)


def register_attachment(plan: UploadPlan, blob: StoredBlob) -> Handler:
    """Файл уже в хранилище; команда лишь фиксирует строку в карантине."""

    async def handler(ctx: CommandContext) -> CommandResult:
        await upload.ensure_provider_may_change(ctx.session, ctx.actor, message_id=plan.message_id)
        if plan.request_id is not None:
            await lock_by_id(ctx.session, RepairRequest, plan.request_id)
            await upload.ensure_photo_limit(ctx.session, plan.request_id)
        if plan.equipment_id is not None:
            await lock_by_id(ctx.session, Equipment, plan.equipment_id)
            await upload.ensure_equipment_photo_limit(ctx.session, plan.equipment_id)
        if plan.provider_profile_id is not None and plan.slot == upload.PORTFOLIO_PURPOSE:
            await lock_by_id(ctx.session, ProviderProfile, plan.provider_profile_id)
            await upload.ensure_portfolio_limit(ctx.session, plan.provider_profile_id)
        if plan.review_id is not None:
            await lock_by_id(ctx.session, Review, plan.review_id)
            await upload.ensure_review_photo_limit(ctx.session, plan.review_id)

        row = Attachment(
            owner_kind=plan.owner_kind,
            request_id=plan.request_id,
            message_id=plan.message_id,
            equipment_id=plan.equipment_id,
            provider_profile_id=plan.provider_profile_id,
            verification_case_id=plan.verification_case_id,
            review_id=plan.review_id,
            uploaded_by_user_id=_user_id(ctx),
            uploaded_by_membership_id=_membership_id(ctx),
            uploaded_by_integration_client_id=_client_id(ctx),
            purpose=plan.purpose,
            slot=plan.slot,
            visibility_class=plan.visibility_class,
            mime_type=blob.mime_type,
            byte_size=blob.byte_size,
            storage_key=blob.storage_key,
            processing_state=AttachmentState.QUARANTINED,
        )
        ctx.session.add(row)
        await ctx.session.flush()

        if plan.visibility_class in MODERATED_CLASSES:
            await open_moderation_case(ctx, row, status=ModerationStatus.PENDING)

        ctx.audit(
            "attachment.upload",
            "attachment",
            row.id,
            organization_id=plan.organization_id,
            visibility_class=plan.visibility_class,
            byte_size=blob.byte_size,
        )
        return CommandResult(to_attachment_view(row).model_dump(mode="json"), status=201)

    return handler


async def open_moderation_case(
    ctx: CommandContext,
    attachment: Attachment,
    *,
    status: str,
    evidence: dict[str, object] | None = None,
) -> ModerationCase:
    """Дело — журнал решения; текущее состояние публикации живёт в attachments.publication_state."""
    case = ModerationCase(
        subject_type=ModerationSubjectType.ATTACHMENT,
        attachment_id=attachment.id,
        provider_profile_id=attachment.provider_profile_id,
        review_id=attachment.review_id,
        status=status,
        evidence=evidence or {},
    )
    ctx.session.add(case)
    await ctx.session.flush()
    attachment.moderation_case_id = case.id
    attachment.publication_state = status
    return case


MAX_CAPTION = 200


def set_portfolio_caption(attachment_id: uuid.UUID, caption: str | None) -> Handler:
    """Подпись к фото портфолио ведёт администратор исполнителя (ТЗ 14.1.1).

    Новая подпись уходит на модерацию вместе с фото: до решения оператора фото
    не показывается в публичном профиле."""
    text = (caption or "").strip() or None
    if text is not None and len(text) > MAX_CAPTION:
        raise ValidationFailed(f"Подпись — не длиннее {MAX_CAPTION} символов", field="caption")

    async def handler(ctx: CommandContext) -> CommandResult:
        actor = ctx.actor
        if not isinstance(actor, UserActor) or actor.role != "provider_admin":
            raise Forbidden("Галерею ведёт администратор исполнителя")
        await upload.ensure_provider_may_change(ctx.session, actor)
        row = await lock_by_id(ctx.session, Attachment, attachment_id)
        profile = (
            await ctx.session.get(ProviderProfile, row.provider_profile_id)
            if row.provider_profile_id is not None
            else None
        )
        if (
            profile is None
            or profile.organization_id != actor.organization_id
            or row.owner_kind != AttachmentOwnerKind.PROFILE
            or row.slot == upload.AVATAR_PURPOSE
        ):
            raise NotFound()
        if row.caption != text:
            row.caption = text
            if row.visibility_class in MODERATED_CLASSES:
                await _return_to_moderation(ctx, row, text)
            ctx.audit(
                "attachment.caption",
                "attachment",
                row.id,
                organization_id=actor.organization_id,
            )
        await ctx.session.flush()
        await ctx.session.refresh(row)
        return CommandResult(to_attachment_view(row).model_dump(mode="json"))

    return handler


async def _return_to_moderation(ctx: CommandContext, row: Attachment, caption: str | None) -> None:
    """Фото с новой подписью снова ждёт решения оператора в том же деле."""
    case = await queries.publication_case(ctx.session, row.id)
    if case is None:
        await open_moderation_case(
            ctx, row, status=ModerationStatus.PENDING, evidence={"caption": caption}
        )
        return
    case.status = ModerationStatus.PENDING
    case.decision_reason = None
    case.operator_user_id = None
    case.evidence = {**(case.evidence or {}), "caption": caption}
    row.publication_state = ModerationStatus.PENDING


def delete_attachment(attachment_id: uuid.UUID) -> Handler:
    """Удаляет автор и только до отправки заявки (A21: черновик остаётся целым).

    Доказательства проверки удаляются, лишь пока по делу нет решения: после
    него это основание решения оператора (ТЗ 14.1.2)."""

    async def handler(ctx: CommandContext) -> CommandResult:
        row = await queries.get_attachment(ctx.session, attachment_id)
        await _ensure_owner(ctx, row)
        await upload.ensure_provider_may_change(ctx.session, ctx.actor, message_id=row.message_id)
        if row.verification_case_id is not None:
            case = await lock_by_id(ctx.session, VerificationCase, row.verification_case_id)
            if case.decision not in upload.OPEN_VERIFICATION:
                raise Conflict(
                    "Доказательство по делу с решением удалить нельзя",
                    code="ATTACHMENT_NOT_DELETABLE",
                    decision=case.decision,
                )
        if row.request_id is not None:
            request = await lock_by_id(ctx.session, RepairRequest, row.request_id)
            if not upload.draft_stage(request.status):
                raise Conflict(
                    "Файл можно удалить только до отправки заявки",
                    code="ATTACHMENT_NOT_DELETABLE",
                    status=request.status,
                )
        keys = [row.storage_key] + [
            variant.storage_key for variant in await queries.variants_of(ctx.session, row.id)
        ]
        await purge_row(ctx.session, row)
        ctx.audit("attachment.delete", "attachment", attachment_id)
        ctx.after_commit(drop_keys(keys))
        return CommandResult({"id": ids.encode("attachment", attachment_id), "deleted": True})

    return handler


def drop_keys(keys: list[str]) -> Callable[[], Awaitable[None]]:
    async def run() -> None:
        storage = get_storage()
        for key in keys:
            await storage.delete(key)

    return run


async def purge_row(session: AsyncSession, row: Attachment) -> None:
    """Снимает перекрёстный FK и удаляет строку вместе с вариантами и делом модерации."""
    await session.execute(
        sql_delete(AttachmentVariant).where(AttachmentVariant.attachment_id == row.id)
    )
    row.moderation_case_id = None
    await session.flush()
    await session.execute(sql_delete(ModerationCase).where(ModerationCase.attachment_id == row.id))
    await session.delete(row)
    await session.flush()


async def _ensure_owner(ctx: CommandContext, row: Attachment) -> None:
    actor = ctx.actor
    own_upload = row.source_attachment_id is None
    if (
        own_upload
        and isinstance(actor, UserActor)
        and row.uploaded_by_user_id == actor.user_id
        and row.uploaded_by_membership_id == actor.membership_id
    ):
        return
    if (
        own_upload
        and isinstance(actor, IntegrationActor)
        and row.uploaded_by_integration_client_id == actor.integration_client_id
    ):
        return
    if (
        isinstance(actor, UserActor)
        and actor.role == "provider_admin"
        and row.provider_profile_id is not None
    ):
        profile = await ctx.session.get(ProviderProfile, row.provider_profile_id)
        if profile is not None and profile.organization_id == actor.organization_id:
            return
    if isinstance(actor, UserActor) and actor.is_manager and row.equipment_id is not None:
        equipment = await ctx.session.get(Equipment, row.equipment_id)
        if equipment is not None and equipment.customer_org_id == actor.organization_id:
            return
    raise NotFound()


def _user_id(ctx: CommandContext) -> uuid.UUID | None:
    return ctx.actor.user_id if isinstance(ctx.actor, UserActor) else None


def _membership_id(ctx: CommandContext) -> uuid.UUID | None:
    return ctx.actor.membership_id if isinstance(ctx.actor, UserActor) else None


def _client_id(ctx: CommandContext) -> uuid.UUID | None:
    return ctx.actor.integration_client_id if isinstance(ctx.actor, IntegrationActor) else None
