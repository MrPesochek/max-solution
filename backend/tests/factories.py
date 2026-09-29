import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.db.models import (
    City,
    District,
    Equipment,
    EquipmentCategory,
    IntegrationClient,
    IntegrationEvent,
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    ModerationCase,
    Notification,
    Organization,
    PlatformRole,
    ProviderBrandRestriction,
    ProviderCategory,
    ProviderProfile,
    ProviderServiceArea,
    Review,
    ReviewReply,
    ReviewVersion,
    ServiceBinding,
    ServiceContract,
    Session,
    User,
    VerificationCase,
    WarrantyAuthorization,
    WebhookDelivery,
    WebhookSubscription,
)
from app.infra.config import Settings, get_settings
from app.infra.crypto import SecretBox, generate_token, hash_token
from app.modules.integration.keys import issue_api_key

BOT_TOKEN = "123456:test-bot-token"
BOT_USERNAME = "repairbot"


def apply_test_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Iterator[Settings]:
    env = {
        "APP_ENV": "test",
        "MAX_BOT_TOKEN": BOT_TOKEN,
        "MAX_BOT_USERNAME": BOT_USERNAME,
        "DEMO_LOGIN_ENABLED": "false"
        if overrides.get("MAX_UPDATES_MODE", "off") != "off"
        else "true",
        **overrides,
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        yield get_settings()
    finally:
        get_settings.cache_clear()


def sign_init_data(
    user_id: int,
    *,
    bot_token: str = BOT_TOKEN,
    auth_date: datetime | None = None,
    display_name: str = "Иван",
    signature: str | None = None,
) -> str:
    """Собирает initData тем же алгоритмом, что и проверяющая сторона."""
    moment = auth_date or utcnow()
    fields = {
        "auth_date": str(int(moment.timestamp())),
        "user": json.dumps({"id": user_id, "first_name": display_name}, ensure_ascii=False),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature or computed})


async def create_user(
    session: AsyncSession, *, max_user_id: str | None = None, display_name: str = "Пользователь"
) -> User:
    user = User(max_user_id=max_user_id or uuid.uuid4().hex, display_name=display_name)
    session.add(user)
    await session.flush()
    return user


async def create_organization(
    session: AsyncSession,
    *,
    name: str = "ООО Ромашка",
    customer: bool = True,
    provider: bool = False,
    inn: str | None = None,
) -> Organization:
    org = Organization(
        is_customer=customer,
        is_provider=provider,
        legal_name=name,
        display_name=name,
        inn_raw=inn,
        inn_normalized=inn,
        details_verification_status="unverified",
        representative_verification_status="unverified",
    )
    session.add(org)
    await session.flush()
    return org


async def create_membership(
    session: AsyncSession,
    user: User,
    org: Organization,
    *,
    role: str = "customer_manager",
    status: str = "active",
    locations: Sequence[Location] = (),
) -> Membership:
    membership = Membership(user_id=user.id, organization_id=org.id, role=role, status=status)
    session.add(membership)
    await session.flush()
    for location in locations:
        session.add(MembershipLocation(membership_id=membership.id, location_id=location.id))
    await session.flush()
    return membership


async def seed_city(session: AsyncSession) -> City:
    city = (await session.execute(select(City).order_by(City.name).limit(1))).scalar_one()
    return city


async def seed_district(session: AsyncSession, city: City) -> District | None:
    return (
        await session.execute(select(District).where(District.city_id == city.id).limit(1))
    ).scalar_one_or_none()


async def seed_category(session: AsyncSession) -> EquipmentCategory:
    return (
        await session.execute(select(EquipmentCategory).order_by(EquipmentCategory.code).limit(1))
    ).scalar_one()


async def create_location(
    session: AsyncSession,
    org: Organization,
    *,
    name: str = "Точка",
    city: City | None = None,
    address: str = "ул. Тестовая, 1",
) -> Location:
    city = city or await seed_city(session)
    location = Location(
        customer_org_id=org.id,
        name=name,
        city_id=city.id,
        address=address,
        timezone=city.timezone,
    )
    session.add(location)
    await session.flush()
    return location


async def create_equipment(
    session: AsyncSession,
    org: Organization,
    location: Location,
    *,
    category: EquipmentCategory | None = None,
    brand: str | None = "Бренд",
    serial_number: str | None = None,
) -> Equipment:
    category = category or await seed_category(session)
    equipment = Equipment(
        customer_org_id=org.id,
        location_id=location.id,
        equipment_category_id=category.id,
        brand=brand,
        serial_number=serial_number,
    )
    session.add(equipment)
    await session.flush()
    return equipment


async def create_session_token(
    session: AsyncSession,
    user: User,
    *,
    expires_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    now = utcnow()
    token = generate_token()
    session.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            token_prefix=token[:8],
            issued_at=now,
            expires_at=expires_at or now + timedelta(hours=12),
            last_seen_at=last_seen_at or now,
            revoked_at=revoked_at,
        )
    )
    await session.flush()
    return token


async def create_invitation(
    session: AsyncSession,
    org: Organization,
    *,
    role: str = "customer_employee",
    kind: str = "membership",
    status: str = "pending",
    locations: Sequence[Location] = (),
    expires_at: datetime | None = None,
    created_by: Membership | None = None,
    recipient_max_user_id: str | None = None,
) -> tuple[Invitation, str]:
    token = generate_token()
    invitation = Invitation(
        kind=kind,
        organization_id=org.id,
        created_by_membership_id=created_by.id if created_by else None,
        role=role,
        location_ids=[loc.id for loc in locations],
        equipment_ids=[],
        token_hash=hash_token(token),
        token_prefix=token[:8],
        recipient_max_user_id=recipient_max_user_id,
        status=status,
        expires_at=expires_at or utcnow() + timedelta(hours=24),
    )
    session.add(invitation)
    await session.flush()
    return invitation, token


SECRETS_ENCRYPTION_KEY = base64.urlsafe_b64encode(b"repair-hub-tests".ljust(32, b"0")).decode()


def integration_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Iterator[Settings]:
    """Настройки для интеграции: ключ шифрования секретов и разрешённый локальный адрес
    приёмника вебхуков в тестах (loopback — только явным IP в списке)."""
    yield from apply_test_settings(
        monkeypatch,
        SECRETS_ENCRYPTION_KEY=SECRETS_ENCRYPTION_KEY,
        ALLOWED_PRIVATE_WEBHOOK_HOSTS="127.0.0.1",
        **overrides,
    )


async def create_provider_profile(
    session: AsyncSession,
    org: Organization,
    *,
    status: str = "active",
    provider_kind: str = "company",
    accepting: bool = True,
    visit_terms: str | None = None,
) -> ProviderProfile:
    profile = ProviderProfile(
        organization_id=org.id,
        provider_kind=provider_kind,
        status=status,
        accepting_new_requests=accepting,
        can_provide_documents=False,
        visit_terms=visit_terms,
    )
    session.add(profile)
    await session.flush()
    return profile


async def create_integration_client(
    session: AsyncSession,
    org: Organization,
    *,
    name: str = "CRM",
    scopes: Sequence[str] = ("requests:read", "webhooks:manage", "events:read"),
    status: str = "active",
    revoked_at: datetime | None = None,
) -> tuple[IntegrationClient, str]:
    issued = issue_api_key("test")
    client = IntegrationClient(
        provider_org_id=org.id,
        name=name,
        api_key_hash=issued.digest,
        api_key_prefix=issued.prefix,
        scopes=list(scopes),
        status=status,
        revoked_at=revoked_at,
    )
    session.add(client)
    await session.flush()
    return client, issued.raw


async def create_webhook_subscription(
    session: AsyncSession,
    client: IntegrationClient,
    *,
    url: str = "https://crm.example.com/hooks",
    events: Sequence[str] | None = None,
    secret: str = "test-webhook-secret",
    status: str = "active",
) -> WebhookSubscription:
    box = SecretBox(SECRETS_ENCRYPTION_KEY)
    subscription = WebhookSubscription(
        integration_client_id=client.id,
        provider_org_id=client.provider_org_id,
        url=url,
        event_types=list(events) if events is not None else ["request.assigned"],
        secret_encrypted=box.encrypt(secret.encode()),
        status=status,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def create_integration_event(
    session: AsyncSession,
    org: Organization,
    *,
    event_type: str = "request.assigned",
    resource_kind: str = "request",
    resource_id: uuid.UUID | None = None,
    resource_version: int | None = 1,
    payload: dict[str, object] | None = None,
    feed_seq: int | None = None,
    occurred_at: datetime | None = None,
) -> IntegrationEvent:
    event = IntegrationEvent(
        event_type=event_type,
        recipient_org_id=org.id,
        feed_seq=feed_seq,
        resource_kind=resource_kind,
        resource_id=resource_id or uuid.uuid4(),
        resource_version=resource_version,
        occurred_at=occurred_at or utcnow(),
        payload=payload or {"status": "accepted"},
    )
    session.add(event)
    await session.flush()
    return event


async def create_webhook_delivery(
    session: AsyncSession,
    event: IntegrationEvent,
    subscription: WebhookSubscription,
    *,
    state: str = "queued",
    attempt_count: int = 0,
    next_attempt_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> WebhookDelivery:
    now = utcnow()
    delivery = WebhookDelivery(
        integration_event_id=event.id,
        webhook_subscription_id=subscription.id,
        provider_org_id=subscription.provider_org_id,
        state=state,
        current_delivery_id=uuid.uuid4(),
        attempt_count=attempt_count,
        next_attempt_at=next_attempt_at if next_attempt_at is not None else now,
        expires_at=expires_at or now + timedelta(hours=24),
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def create_notification(
    session: AsyncSession,
    user: User,
    *,
    notification_type: str = "request.assigned",
    payload: dict[str, object] | None = None,
    state: str = "queued",
    attempt_count: int = 0,
    next_attempt_at: datetime | None = None,
    organization: Organization | None = None,
) -> Notification:
    notification = Notification(
        recipient_user_id=user.id,
        organization_id=organization.id if organization else None,
        notification_type=notification_type,
        payload=payload or {},
        state=state,
        attempt_count=attempt_count,
        next_attempt_at=next_attempt_at if next_attempt_at is not None else utcnow(),
    )
    session.add(notification)
    await session.flush()
    return notification


async def add_provider_category(
    session: AsyncSession, org: Organization, category: EquipmentCategory
) -> ProviderCategory:
    row = ProviderCategory(provider_org_id=org.id, equipment_category_id=category.id)
    session.add(row)
    await session.flush()
    return row


async def add_provider_service_area(
    session: AsyncSession, org: Organization, city: City, district: District | None = None
) -> ProviderServiceArea:
    row = ProviderServiceArea(
        provider_org_id=org.id,
        city_id=city.id,
        district_id=district.id if district else None,
    )
    session.add(row)
    await session.flush()
    return row


async def add_brand_restriction(
    session: AsyncSession, org: Organization, category: EquipmentCategory, brand: str
) -> ProviderBrandRestriction:
    row = ProviderBrandRestriction(
        provider_org_id=org.id, equipment_category_id=category.id, brand=brand
    )
    session.add(row)
    await session.flush()
    return row


async def verify_organization(
    session: AsyncSession,
    org: Organization,
    *,
    details: bool = True,
    representative: bool = True,
) -> Organization:
    now = utcnow()
    if details:
        org.details_verification_status = "verified"
        org.details_verified_at = now
    if representative:
        org.representative_verification_status = "verified"
        org.representative_verified_at = now
    await session.flush()
    return org


async def create_verification_case(
    session: AsyncSession,
    org: Organization,
    *,
    check_kind: str = "requisites",
    subject_type: str = "organization_details",
    decision: str = "pending",
    membership: Membership | None = None,
    source: str | None = None,
    is_demo: bool = False,
) -> VerificationCase:
    case = VerificationCase(
        organization_id=org.id,
        membership_id=membership.id if membership else None,
        subject_type=subject_type,
        check_kind=check_kind,
        decision=decision,
        source=source,
        is_demo=is_demo,
    )
    session.add(case)
    await session.flush()
    return case


async def create_review(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    assignment_id: uuid.UUID,
    customer_org_id: uuid.UUID,
    provider_org_id: uuid.UUID,
    author_membership_id: uuid.UUID,
    rating: int = 5,
    moderation_status: str = "pending",
) -> Review:
    review = Review(
        assignment_id=assignment_id,
        request_id=request_id,
        customer_org_id=customer_org_id,
        provider_org_id=provider_org_id,
        author_membership_id=author_membership_id,
        rating=rating,
        moderation_status=moderation_status,
        order_occurred_at=utcnow(),
    )
    session.add(review)
    await session.flush()
    return review


async def create_review_version(
    session: AsyncSession,
    review: Review,
    *,
    version: int,
    rating: int | None = None,
    text: str | None = None,
    moderation_status: str = "pending",
    edited_by_membership_id: uuid.UUID | None = None,
) -> ReviewVersion:
    row = ReviewVersion(
        review_id=review.id,
        version=version,
        rating=rating if rating is not None else review.rating,
        text_body=text,
        moderation_status=moderation_status,
        edited_by_membership_id=edited_by_membership_id,
    )
    session.add(row)
    await session.flush()
    return row


async def create_review_reply(
    session: AsyncSession,
    review: Review,
    *,
    provider_org_id: uuid.UUID,
    author_membership_id: uuid.UUID | None = None,
    body: str = "Спасибо за отзыв",
) -> ReviewReply:
    reply = ReviewReply(
        review_id=review.id,
        provider_org_id=provider_org_id,
        author_membership_id=author_membership_id,
        body=body,
    )
    session.add(reply)
    await session.flush()
    return reply


async def create_moderation_case(
    session: AsyncSession,
    *,
    subject_type: str = "review",
    review: Review | None = None,
    provider_profile_id: uuid.UUID | None = None,
    attachment_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    filer_org_id: uuid.UUID | None = None,
    filer_membership_id: uuid.UUID | None = None,
    status: str = "pending",
    evidence: dict[str, object] | None = None,
) -> ModerationCase:
    case = ModerationCase(
        subject_type=subject_type,
        review_id=review.id if review is not None else None,
        provider_profile_id=provider_profile_id,
        attachment_id=attachment_id,
        assignment_id=assignment_id,
        filer_org_id=filer_org_id,
        filer_membership_id=filer_membership_id,
        status=status,
        evidence=evidence or {},
    )
    session.add(case)
    await session.flush()
    return case


async def create_platform_role(
    session: AsyncSession, user: User, *, role: str = "operator"
) -> PlatformRole:
    row = PlatformRole(user_id=user.id, role=role, granted_at=utcnow())
    session.add(row)
    await session.flush()
    return row


async def create_service_contract(
    session: AsyncSession,
    provider: Organization,
    customer: Organization,
    *,
    number: str = "Д-1",
    basis: str = "service_contract",
) -> ServiceContract:
    contract = ServiceContract(
        provider_org_id=provider.id,
        customer_org_id=customer.id,
        contract_number=number,
        basis=basis,
    )
    session.add(contract)
    await session.flush()
    return contract


async def create_service_binding(
    session: AsyncSession,
    equipment: Equipment,
    customer: Organization,
    created_by: Membership,
    *,
    provider: Organization | None = None,
    status: str = "pending",
    basis: str = "service_contract",
    contract: ServiceContract | None = None,
    contact_name: str | None = None,
) -> ServiceBinding:
    binding = ServiceBinding(
        equipment_id=equipment.id,
        customer_org_id=customer.id,
        provider_org_id=provider.id if provider else None,
        personal_contact_name=contact_name,
        contract_id=contract.id if contract else None,
        basis=basis,
        status=status,
        created_by_membership_id=created_by.id,
        customer_confirmed_at=utcnow(),
    )
    session.add(binding)
    await session.flush()
    return binding


async def create_warranty_authorization(
    session: AsyncSession,
    provider: Organization,
    *,
    guarantor_kind: str = "manufacturer",
    guarantor_name: str = "Завод",
    brands: Sequence[str] = (),
    category: EquipmentCategory | None = None,
    status: str = "active",
) -> WarrantyAuthorization:
    row = WarrantyAuthorization(
        guarantor_kind=guarantor_kind,
        guarantor_name=guarantor_name,
        authorized_provider_org_id=provider.id,
        equipment_category_id=category.id if category else None,
        brand_scope=list(brands),
        status=status,
    )
    session.add(row)
    await session.flush()
    return row
