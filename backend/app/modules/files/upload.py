import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, IntegrationActor, UserActor
from app.core.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from app.db.enums import (
    AssignmentState,
    AttachmentOwnerKind,
    ProviderProfileStatus,
    RequestStatus,
    VerificationDecision,
    VisibilityClass,
)
from app.db.models import (
    Assignment,
    Equipment,
    Message,
    ProviderProfile,
    RepairRequest,
    Review,
    VerificationCase,
)
from app.infra.config import get_settings
from app.infra.images.sniff import sniff_image_format
from app.infra.storage.base import make_storage_key
from app.modules.files import policy, queries
from app.modules.files.errors import FileTooLarge, UnsupportedMediaType
from app.modules.files.owners import AttachmentOwner, OwnerKind
from app.modules.files.storage import get_storage
from app.modules.files.views import MIME_BY_FORMAT

_SNIFF_BYTES = 16
_TERMINAL_STATUSES = (RequestStatus.CLOSED, RequestStatus.CANCELLED)
_DRAFT_STATUSES = (RequestStatus.DRAFT, RequestStatus.APPROVAL_REQUIRED)
OPEN_VERIFICATION = (VerificationDecision.PENDING, VerificationDecision.NEEDS_INFORMATION)

REPORT_SLOTS = frozenset({"before", "after"})

PORTFOLIO_PURPOSE = "portfolio"
AVATAR_PURPOSE = "avatar"

PURPOSE_REQUEST_PHOTO = "request_photo"
PURPOSE_EQUIPMENT_PHOTO = "equipment_photo"
PURPOSE_PROFILE_PHOTO = "profile_photo"
PURPOSE_VERIFICATION_EVIDENCE = "verification_evidence"
PURPOSE_REVIEW_PHOTO = "review_photo"


@dataclass(frozen=True, slots=True)
class UploadPlan:
    """Что и куда будет записано — вычислено до касания хранилища."""

    owner_kind: str
    visibility_class: str
    purpose: str | None
    slot: str | None
    prefix: str
    request_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    equipment_id: uuid.UUID | None = None
    provider_profile_id: uuid.UUID | None = None
    verification_case_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredBlob:
    storage_key: str
    byte_size: int
    mime_type: str


async def prepare(
    session: AsyncSession, actor: Actor, owner: AttachmentOwner, purpose: str | None
) -> UploadPlan:
    plan = await _prepare(session, actor, owner, purpose)
    await ensure_provider_may_change(session, actor, message_id=plan.message_id)
    return plan


async def ensure_provider_may_change(
    session: AsyncSession, actor: Actor, *, message_id: uuid.UUID | None = None
) -> None:
    """ТЗ 6.5.3: заблокированному исполнителю остаётся только переписка по принятым
    назначениям. Вложение к такому сообщению допустимо, остальные изменения — нет.
    Правило то же, что в модуле заявок, для Web App, бота и CRM."""
    provider_org_id = _provider_org(actor)
    if provider_org_id is None:
        return
    if message_id is not None:
        message = await session.get(Message, message_id)
        assignment = (
            await session.get(Assignment, message.assignment_id)
            if message is not None and message.assignment_id is not None
            else None
        )
        if assignment is not None and assignment.state == AssignmentState.ACCEPTED:
            return
    from app.modules.requests import api as requests_api

    await requests_api.ensure_provider_not_suspended(session, provider_org_id)


async def _prepare(
    session: AsyncSession, actor: Actor, owner: AttachmentOwner, purpose: str | None
) -> UploadPlan:
    match owner.kind:
        case OwnerKind.REQUEST:
            return await _plan_request(session, actor, owner.object_id, purpose, message_id=None)
        case OwnerKind.MESSAGE:
            message = await queries.get_message(session, _required(owner.object_id))
            await _ensure_message_author(session, actor, message)
            return await _plan_request(
                session, actor, message.request_id, purpose, message_id=message.id
            )
        case OwnerKind.EQUIPMENT:
            return await _plan_equipment(session, actor, _required(owner.object_id), purpose)
        case OwnerKind.PROVIDER_PROFILE:
            return await _plan_profile(session, actor, owner.object_id, purpose)
        case OwnerKind.VERIFICATION_CASE:
            return await _plan_verification(session, actor, owner.object_id)
        case OwnerKind.REVIEW:
            return await _plan_review(session, actor, _required(owner.object_id))
    raise ValidationFailed("Неизвестный владелец вложения", field="owner")


async def _ensure_message_author(session: AsyncSession, actor: Actor, message: Message) -> None:
    """Файл прикладывается только к своему сообщению и только в видимом автору канале:
    к чужой реплике, приватному треду другого исполнителя или переписке прежнего
    назначения — нельзя."""
    if isinstance(actor, UserActor):
        own = message.author_membership_id == actor.membership_id
    elif isinstance(actor, IntegrationActor):
        own = message.author_integration_client_id == actor.integration_client_id
    else:
        own = False
    if not own:
        raise NotFound()
    provider_org_id = _provider_org(actor)
    if provider_org_id is None:
        return
    assignment = await queries.provider_assignment(session, message.request_id, provider_org_id)
    if not queries.message_in_channel(message, assignment, provider_org_id):
        raise NotFound()


def _required(object_id: uuid.UUID | None) -> uuid.UUID:
    if object_id is None:
        raise ValidationFailed("Не указан объект вложения", field="owner")
    return object_id


async def _plan_request(
    session: AsyncSession,
    actor: Actor,
    request_id: uuid.UUID | None,
    slot: str | None,
    *,
    message_id: uuid.UUID | None,
) -> UploadPlan:
    request = await session.get(RepairRequest, _required(request_id))
    if request is None:
        raise NotFound()
    await ensure_request_participant(session, actor, request)
    if request.status in _TERMINAL_STATUSES:
        raise InvalidTransition("Заявка завершена, файл добавить нельзя")
    if slot in REPORT_SLOTS and _provider_org(actor) is None:
        raise ValidationFailed("Фото «до» и «после» добавляет исполнитель", field="slot")
    await ensure_photo_limit(session, request.id)
    template = await queries.category_photo_template(session, request.equipment_id)
    return UploadPlan(
        owner_kind=(
            AttachmentOwnerKind.MESSAGE if message_id is not None else AttachmentOwnerKind.REQUEST
        ),
        visibility_class=visibility_for_slot(template, slot),
        purpose=PURPOSE_REQUEST_PHOTO,
        slot=slot,
        prefix="requests",
        request_id=request.id,
        message_id=message_id,
        organization_id=request.customer_org_id,
    )


async def ensure_request_participant(
    session: AsyncSession, actor: Actor, request: RepairRequest
) -> None:
    """Участник своей стороны: заказчик по точке либо исполнитель с активным назначением."""
    if isinstance(actor, UserActor) and actor.side == "customer":
        if actor.organization_id != request.customer_org_id:
            raise NotFound()
        if actor.location_ids is not None and request.location_id not in actor.location_ids:
            raise NotFound()
        return
    provider_org_id = _provider_org(actor)
    if provider_org_id is None:
        raise NotFound()
    if isinstance(actor, IntegrationActor) and policy.REQUESTS_WRITE not in actor.scopes:
        raise Forbidden(code="INSUFFICIENT_SCOPE", required_scope=policy.REQUESTS_WRITE)
    assignment = await queries.provider_assignment(session, request.id, provider_org_id)
    if assignment is None or assignment.state not in policy.READABLE_ASSIGNMENT_STATES:
        raise NotFound()


def _provider_org(actor: Actor) -> uuid.UUID | None:
    if isinstance(actor, IntegrationActor):
        return actor.organization_id
    if isinstance(actor, UserActor) and actor.side == "provider":
        return actor.organization_id
    return None


async def ensure_photo_limit(session: AsyncSession, request_id: uuid.UUID) -> None:
    limit = get_settings().max_photos_per_request
    if await queries.count_request_photos(session, request_id) >= limit:
        raise ValidationFailed(
            f"К заявке уже приложено {limit} фото",
            code="PHOTO_LIMIT_REACHED",
            limit=limit,
        )


async def ensure_equipment_photo_limit(session: AsyncSession, equipment_id: uuid.UUID) -> None:
    limit = get_settings().max_photos_per_equipment
    if await queries.count_equipment_photos(session, equipment_id) >= limit:
        raise ValidationFailed(
            f"К оборудованию уже приложено {limit} фото",
            code="EQUIPMENT_PHOTO_LIMIT_REACHED",
            limit=limit,
        )


def visibility_for_slot(template: list[dict[str, object]], slot: str | None) -> str:
    """Класс чувствительности берётся из шаблона категории (D13); по умолчанию приватный."""
    if slot:
        for entry in template:
            if entry.get("code") == slot:
                value = entry.get("visibility_class")
                if isinstance(value, str) and value in (
                    VisibilityClass.REQUEST_PRIVATE,
                    VisibilityClass.REQUEST_SENSITIVE,
                ):
                    return value
    return VisibilityClass.REQUEST_PRIVATE


async def _plan_equipment(
    session: AsyncSession, actor: Actor, equipment_id: uuid.UUID, slot: str | None
) -> UploadPlan:
    """Загружает менеджер заказчика либо сотрудник в своей точке (не исполнитель)."""
    equipment = await session.get(Equipment, equipment_id)
    if equipment is None or not isinstance(actor, UserActor) or actor.side != "customer":
        raise NotFound()
    if actor.organization_id != equipment.customer_org_id:
        raise NotFound()
    if actor.location_ids is not None and equipment.location_id not in actor.location_ids:
        raise NotFound()
    await ensure_equipment_photo_limit(session, equipment.id)
    return UploadPlan(
        owner_kind=AttachmentOwnerKind.EQUIPMENT,
        visibility_class=VisibilityClass.REQUEST_PRIVATE,
        purpose=PURPOSE_EQUIPMENT_PHOTO,
        slot=slot,
        prefix="equipment",
        equipment_id=equipment.id,
        organization_id=equipment.customer_org_id,
    )


async def _plan_profile(
    session: AsyncSession, actor: Actor, profile_id: uuid.UUID | None, purpose: str | None
) -> UploadPlan:
    if not isinstance(actor, UserActor) or actor.role != "provider_admin":
        raise Forbidden("Галерею ведёт администратор исполнителя")
    profile = await _own_profile(session, actor.organization_id)
    if profile_id is not None and profile_id != profile.id:
        raise NotFound()
    slot = AVATAR_PURPOSE if purpose == AVATAR_PURPOSE else PORTFOLIO_PURPOSE
    if slot == PORTFOLIO_PURPOSE:
        await ensure_portfolio_limit(session, profile.id)
    return UploadPlan(
        owner_kind=AttachmentOwnerKind.PROFILE,
        visibility_class=VisibilityClass.PROFILE_PUBLIC,
        purpose=PURPOSE_PROFILE_PHOTO,
        slot=slot,
        prefix="portfolio",
        provider_profile_id=profile.id,
        organization_id=actor.organization_id,
    )


async def ensure_portfolio_limit(session: AsyncSession, profile_id: uuid.UUID) -> None:
    limit = get_settings().portfolio_max_images
    gallery = [
        item
        for item in await queries.portfolio_images(session, profile_id)
        if item.slot != AVATAR_PURPOSE
    ]
    if len(gallery) >= limit:
        raise ValidationFailed(
            f"В галерее уже {limit} изображений",
            code="PORTFOLIO_LIMIT_REACHED",
            limit=limit,
        )


async def ensure_review_photo_limit(session: AsyncSession, review_id: uuid.UUID) -> None:
    limit = get_settings().review_max_photos
    if len(await queries.review_photos(session, review_id)) >= limit:
        raise ValidationFailed(
            f"К отзыву уже приложено {limit} фото", code="REVIEW_PHOTO_LIMIT_REACHED", limit=limit
        )


async def _own_profile(session: AsyncSession, organization_id: uuid.UUID) -> ProviderProfile:
    stmt = select(ProviderProfile).where(ProviderProfile.organization_id == organization_id)
    profile = (await session.execute(stmt)).scalar_one_or_none()
    if profile is None or profile.status == ProviderProfileStatus.REJECTED:
        raise NotFound()
    return profile


async def _plan_verification(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID | None
) -> UploadPlan:
    if not isinstance(actor, UserActor) or actor.role not in policy.VERIFICATION_ROLES:
        raise Forbidden("Доказательства подаёт руководитель организации")
    case = await _open_case(session, actor.organization_id, case_id)
    return UploadPlan(
        owner_kind=AttachmentOwnerKind.VERIFICATION,
        visibility_class=VisibilityClass.VERIFICATION_EVIDENCE,
        purpose=PURPOSE_VERIFICATION_EVIDENCE,
        slot="evidence",
        prefix="verification",
        verification_case_id=case.id,
        organization_id=actor.organization_id,
    )


async def _open_case(
    session: AsyncSession, organization_id: uuid.UUID, case_id: uuid.UUID | None
) -> VerificationCase:
    stmt = select(VerificationCase).where(
        VerificationCase.organization_id == organization_id,
        VerificationCase.decision.in_(tuple(OPEN_VERIFICATION)),
    )
    if case_id is not None:
        stmt = stmt.where(VerificationCase.id == case_id)
    case = (
        await session.execute(stmt.order_by(VerificationCase.id.desc()).limit(1))
    ).scalar_one_or_none()
    if case is None:
        raise NotFound()
    return case


async def _plan_review(session: AsyncSession, actor: Actor, review_id: uuid.UUID) -> UploadPlan:
    review = await session.get(Review, review_id)
    if review is None or not isinstance(actor, UserActor) or not actor.is_manager:
        raise NotFound()
    if review.customer_org_id != actor.organization_id:
        raise NotFound()
    await ensure_review_photo_limit(session, review.id)
    return UploadPlan(
        owner_kind=AttachmentOwnerKind.REVIEW,
        visibility_class=VisibilityClass.REVIEW_PUBLIC,
        purpose=PURPOSE_REVIEW_PHOTO,
        slot="review",
        prefix="reviews",
        review_id=review.id,
        organization_id=actor.organization_id,
    )


def draft_stage(status: str) -> bool:
    return status in _DRAFT_STATUSES


async def store_incoming(
    stream: AsyncIterable[bytes], *, prefix: str, max_bytes: int
) -> StoredBlob:
    source = aiter(stream)
    head = await _read_head(source, _SNIFF_BYTES)
    fmt = sniff_image_format(head)
    if fmt is None:
        raise UnsupportedMediaType()
    if len(head) > max_bytes:
        raise FileTooLarge()

    storage = get_storage()
    key = make_storage_key(prefix)
    try:
        size = await storage.put(key, _capped(head, source, max_bytes))
    except BaseException:
        await storage.delete(key)
        raise
    return StoredBlob(storage_key=key, byte_size=size, mime_type=MIME_BY_FORMAT[str(fmt)])


async def _read_head(source: AsyncIterator[bytes], size: int) -> bytes:
    head = bytearray()
    while len(head) < size:
        try:
            head.extend(await anext(source))
        except StopAsyncIteration:
            break
    return bytes(head)


async def _capped(
    head: bytes, source: AsyncIterator[bytes], max_bytes: int
) -> AsyncIterator[bytes]:
    total = len(head)
    if total > max_bytes:
        raise FileTooLarge()
    if head:
        yield head
    async for chunk in source:
        total += len(chunk)
        if total > max_bytes:
            raise FileTooLarge()
        yield chunk
