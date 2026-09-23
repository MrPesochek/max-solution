import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, IntegrationActor, UserActor
from app.core.errors import NotFound
from app.db.enums import (
    AttachmentOwnerKind,
    AttachmentState,
    AttachmentVariantKind,
    BindingStatus,
    ModerationStatus,
    ModerationSubjectType,
    PublicCardStatus,
)
from app.db.models import (
    Assignment,
    Attachment,
    AttachmentVariant,
    Equipment,
    EquipmentCategory,
    IntegrationClient,
    Membership,
    Message,
    ModerationCase,
    ProviderProfile,
    RepairRequest,
    RequestPublicCard,
    Review,
    ServiceBinding,
    VerificationCase,
)
from app.modules.files.policy import AttachmentAccess

VARIANT_SAFE = "safe"
VARIANT_THUMB = "thumb"
VARIANT_KINDS = {
    VARIANT_SAFE: AttachmentVariantKind.SAFE_COPY,
    VARIANT_THUMB: AttachmentVariantKind.PREVIEW,
}

EVIDENCE_KIND = "copy_kind"


@dataclass(frozen=True, slots=True)
class CopySource:
    """Материализация публичной копии: откуда берутся байты."""

    copy_id: uuid.UUID
    copy_storage_key: str
    source_id: uuid.UUID


async def get_attachment(session: AsyncSession, attachment_id: uuid.UUID) -> Attachment:
    row = await session.get(Attachment, attachment_id)
    if row is None:
        raise NotFound()
    return row


async def variant_of(
    session: AsyncSession, attachment_id: uuid.UUID, kind: str
) -> AttachmentVariant | None:
    stmt = select(AttachmentVariant).where(
        AttachmentVariant.attachment_id == attachment_id,
        AttachmentVariant.variant_kind == kind,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def variants_of(session: AsyncSession, attachment_id: uuid.UUID) -> list[AttachmentVariant]:
    stmt = select(AttachmentVariant).where(AttachmentVariant.attachment_id == attachment_id)
    return list((await session.execute(stmt)).scalars().all())


async def publication_case(
    session: AsyncSession, attachment_id: uuid.UUID
) -> ModerationCase | None:
    stmt = (
        select(ModerationCase)
        .where(
            ModerationCase.attachment_id == attachment_id,
            ModerationCase.subject_type == ModerationSubjectType.ATTACHMENT,
        )
        .order_by(ModerationCase.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@dataclass(frozen=True, slots=True)
class RequestAccessContext:
    """Заявка, назначение читающего исполнителя и публичная карточка — общие для
    всех вложений одной заявки: список грузит их один раз, а не на каждое вложение."""

    request_id: uuid.UUID
    request: RepairRequest | None
    assignment: Assignment | None
    card: RequestPublicCard | None


async def request_access_context(
    session: AsyncSession, request_id: uuid.UUID, actor: Actor
) -> RequestAccessContext:
    request = await session.get(RepairRequest, request_id)
    if request is None:
        return RequestAccessContext(request_id, None, None, None)
    provider_org_id = _provider_org_of(actor)
    assignment = (
        await provider_assignment(session, request.id, provider_org_id)
        if provider_org_id is not None
        else None
    )
    return RequestAccessContext(
        request_id, request, assignment, await public_card(session, request.id)
    )


async def load_access(
    session: AsyncSession,
    attachment: Attachment,
    actor: Actor,
    *,
    request_context: RequestAccessContext | None = None,
) -> AttachmentAccess:
    """Собирает состояние владельца, от которого зависит доступ именно этого актора.

    `request_context` — уже загруженное состояние заявки вложения (список вложений)."""
    access = AttachmentAccess(
        attachment_id=attachment.id,
        visibility_class=attachment.visibility_class,
        processing_state=attachment.processing_state,
        owner_kind=attachment.owner_kind,
        uploaded_by_user_id=attachment.uploaded_by_user_id,
        uploaded_by_membership_id=attachment.uploaded_by_membership_id,
        uploaded_by_integration_client_id=attachment.uploaded_by_integration_client_id,
        is_copy=attachment.source_attachment_id is not None,
        publication_state=attachment.publication_state,
    )
    if attachment.request_id is not None:
        if request_context is None or request_context.request_id != attachment.request_id:
            request_context = await request_access_context(session, attachment.request_id, actor)
        access = await _with_request(session, access, attachment, actor, request_context)
    if attachment.equipment_id is not None:
        access = await _with_equipment(session, access, attachment, actor)
    if attachment.provider_profile_id is not None:
        profile = await session.get(ProviderProfile, attachment.provider_profile_id)
        access = replace(
            access, provider_org_id=profile.organization_id if profile is not None else None
        )
    if attachment.review_id is not None:
        review = await session.get(Review, attachment.review_id)
        if review is not None:
            access = replace(
                access,
                review_customer_org_id=review.customer_org_id,
                provider_org_id=review.provider_org_id,
            )
    if attachment.verification_case_id is not None:
        case_row = await session.get(VerificationCase, attachment.verification_case_id)
        if case_row is not None:
            access = replace(access, verification_org_id=case_row.organization_id)
    return access


async def _with_request(
    session: AsyncSession,
    access: AttachmentAccess,
    attachment: Attachment,
    actor: Actor,
    context: RequestAccessContext,
) -> AttachmentAccess:
    request, assignment, card = context.request, context.assignment, context.card
    if request is None:
        return access
    provider_org_id = _provider_org_of(actor)
    return replace(
        access,
        customer_org_id=request.customer_org_id,
        location_id=request.location_id,
        assignment_state=assignment.state if assignment is not None else None,
        assignment_route=assignment.route if assignment is not None else None,
        card_open=card is not None and card.status == PublicCardStatus.OPEN,
        listed_in_card=card is not None and attachment.id in card.published_attachment_ids,
        within_assignment=(
            await _within_assignment(session, attachment, request, assignment, provider_org_id)
            if provider_org_id is not None
            else True
        ),
    )


def message_in_channel(
    message: Message, assignment: Assignment | None, provider_org_id: uuid.UUID
) -> bool:
    """Как в переписке заявки: свой приватный тред и общий канал своего назначения."""
    if message.thread_provider_org_id is not None:
        return message.thread_provider_org_id == provider_org_id
    return assignment is not None and message.assignment_id == assignment.id


async def _within_assignment(
    session: AsyncSession,
    attachment: Attachment,
    request: RepairRequest,
    assignment: Assignment | None,
    provider_org_id: uuid.UUID,
) -> bool:
    """Вложение относится к периоду назначения читающего исполнителя.

    Файлы сообщений — по видимости сообщения; файлы, добавленные стороной
    исполнителя, — только свои и загруженные в текущем назначении: фото отчёта
    прежнего исполнителя новому не показываются. Файлы заказчика видны любому
    исполнителю с назначением."""
    if attachment.message_id is not None:
        message = await session.get(Message, attachment.message_id)
        return message is not None and message_in_channel(message, assignment, provider_org_id)
    uploader_org_id = await _uploader_org(session, attachment)
    if uploader_org_id is None or uploader_org_id == request.customer_org_id:
        return True
    return (
        assignment is not None
        and uploader_org_id == provider_org_id
        and attachment.created_at >= assignment.created_at
    )


async def _uploader_org(session: AsyncSession, attachment: Attachment) -> uuid.UUID | None:
    if attachment.uploaded_by_membership_id is not None:
        membership = await session.get(Membership, attachment.uploaded_by_membership_id)
        return membership.organization_id if membership is not None else None
    if attachment.uploaded_by_integration_client_id is not None:
        client = await session.get(IntegrationClient, attachment.uploaded_by_integration_client_id)
        return client.provider_org_id if client is not None else None
    return None


async def _with_equipment(
    session: AsyncSession, access: AttachmentAccess, attachment: Attachment, actor: Actor
) -> AttachmentAccess:
    equipment = await session.get(Equipment, attachment.equipment_id)
    if equipment is None:
        return access
    provider_org_id = _provider_org_of(actor)
    confirmed = (
        await equipment_binding_confirmed(session, equipment.id, provider_org_id)
        if provider_org_id is not None
        else False
    )
    return replace(
        access,
        customer_org_id=equipment.customer_org_id,
        location_id=equipment.location_id,
        service_binding_confirmed=confirmed,
    )


async def equipment_binding_confirmed(
    session: AsyncSession, equipment_id: uuid.UUID, provider_org_id: uuid.UUID
) -> bool:
    stmt = (
        select(ServiceBinding.id)
        .where(
            ServiceBinding.equipment_id == equipment_id,
            ServiceBinding.provider_org_id == provider_org_id,
            ServiceBinding.status == BindingStatus.CONFIRMED,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


def _provider_org_of(actor: Actor) -> uuid.UUID | None:
    if isinstance(actor, IntegrationActor):
        return actor.organization_id
    if isinstance(actor, UserActor) and actor.side == "provider":
        return actor.organization_id
    return None


async def provider_assignment(
    session: AsyncSession, request_id: uuid.UUID, provider_org_id: uuid.UUID
) -> Assignment | None:
    stmt = (
        select(Assignment)
        .where(Assignment.request_id == request_id, Assignment.provider_org_id == provider_org_id)
        .order_by(Assignment.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def public_card(session: AsyncSession, request_id: uuid.UUID) -> RequestPublicCard | None:
    stmt = select(RequestPublicCard).where(RequestPublicCard.request_id == request_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def request_attachments(
    session: AsyncSession, request_id: uuid.UUID, *, include_copies: bool = False
) -> list[Attachment]:
    stmt = select(Attachment).where(Attachment.request_id == request_id)
    if not include_copies:
        stmt = stmt.where(Attachment.visibility_class != "public_card")
    return list((await session.execute(stmt.order_by(Attachment.id))).scalars().all())


async def count_request_photos(session: AsyncSession, request_id: uuid.UUID) -> int:
    """Лимит фото на заявку считается по собственным вложениям, без публичных копий."""
    stmt = (
        select(func.count())
        .select_from(Attachment)
        .where(
            Attachment.request_id == request_id,
            Attachment.visibility_class != "public_card",
            Attachment.processing_state != AttachmentState.REJECTED,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def equipment_attachments(session: AsyncSession, equipment_id: uuid.UUID) -> list[Attachment]:
    stmt = select(Attachment).where(Attachment.equipment_id == equipment_id).order_by(Attachment.id)
    return list((await session.execute(stmt)).scalars().all())


async def count_equipment_photos(session: AsyncSession, equipment_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Attachment)
        .where(
            Attachment.equipment_id == equipment_id,
            Attachment.processing_state != AttachmentState.REJECTED,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def portfolio_images(
    session: AsyncSession, provider_profile_id: uuid.UUID
) -> list[Attachment]:
    stmt = (
        select(Attachment)
        .where(
            Attachment.provider_profile_id == provider_profile_id,
            Attachment.owner_kind == AttachmentOwnerKind.PROFILE,
            Attachment.processing_state != AttachmentState.REJECTED,
        )
        .order_by(Attachment.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def published_portfolio_ids(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> list[uuid.UUID]:
    """Галерея публичного профиля: только прошедшие модерацию готовые фото, без аватара."""
    stmt = (
        select(Attachment.id)
        .join(ProviderProfile, ProviderProfile.id == Attachment.provider_profile_id)
        .where(
            ProviderProfile.organization_id == provider_org_id,
            Attachment.owner_kind == AttachmentOwnerKind.PROFILE,
            Attachment.processing_state == AttachmentState.READY,
            Attachment.publication_state == ModerationStatus.PUBLISHED,
            or_(Attachment.slot.is_(None), Attachment.slot != "avatar"),
        )
        .order_by(Attachment.created_at, Attachment.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def published_portfolio_items(
    session: AsyncSession, provider_org_id: uuid.UUID
) -> list[tuple[uuid.UUID, str | None]]:
    stmt = (
        select(Attachment.id, Attachment.caption)
        .join(ProviderProfile, ProviderProfile.id == Attachment.provider_profile_id)
        .where(
            ProviderProfile.organization_id == provider_org_id,
            Attachment.owner_kind == AttachmentOwnerKind.PROFILE,
            Attachment.processing_state == AttachmentState.READY,
            Attachment.publication_state == ModerationStatus.PUBLISHED,
            or_(Attachment.slot.is_(None), Attachment.slot != "avatar"),
        )
        .order_by(Attachment.created_at, Attachment.id)
    )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def review_photos(session: AsyncSession, review_id: uuid.UUID) -> list[Attachment]:
    stmt = select(Attachment).where(Attachment.review_id == review_id).order_by(Attachment.id)
    return list((await session.execute(stmt)).scalars().all())


async def get_message(session: AsyncSession, message_id: uuid.UUID) -> Message:
    row = await session.get(Message, message_id)
    if row is None:
        raise NotFound()
    return row


async def category_photo_template(
    session: AsyncSession, equipment_id: uuid.UUID
) -> list[dict[str, object]]:
    stmt = (
        select(EquipmentCategory.photo_template)
        .join(Equipment, Equipment.equipment_category_id == EquipmentCategory.id)
        .where(Equipment.id == equipment_id)
    )
    template = (await session.execute(stmt)).scalar_one_or_none()
    return list(template or [])


async def moderation_queue(
    session: AsyncSession, *, status: str, after: uuid.UUID | None, limit: int
) -> tuple[list[tuple[Attachment, ModerationCase]], uuid.UUID | None]:
    stmt = (
        select(Attachment, ModerationCase)
        .join(ModerationCase, ModerationCase.attachment_id == Attachment.id)
        .where(
            ModerationCase.subject_type == ModerationSubjectType.ATTACHMENT,
            ModerationCase.status == status,
        )
    )
    if after is not None:
        stmt = stmt.where(ModerationCase.id > after)
    rows = (await session.execute(stmt.order_by(ModerationCase.id).limit(limit + 1))).all()
    items = [(row[0], row[1]) for row in rows[:limit]]
    next_cursor = items[-1][1].id if len(rows) > limit and items else None
    return items, next_cursor


async def pending_copies(session: AsyncSession, ids_: Sequence[uuid.UUID]) -> list[CopySource]:
    """Копии, для которых байты ещё не скопированы (после падения — доберёт worker)."""
    if not ids_:
        return []
    stmt = select(Attachment).where(
        Attachment.id.in_(tuple(ids_)),
        Attachment.processing_state == AttachmentState.QUARANTINED,
        Attachment.source_attachment_id.is_not(None),
    )
    return [
        CopySource(
            copy_id=row.id,
            copy_storage_key=row.storage_key,
            source_id=row.source_attachment_id,
        )
        for row in (await session.execute(stmt)).scalars().all()
        if row.source_attachment_id is not None
    ]
