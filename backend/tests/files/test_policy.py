import uuid

import pytest

from app.core.actor import BareUserActor, IntegrationActor, OperatorActor, UserActor
from app.db.enums import AssignmentState, AttachmentState, ModerationStatus, VisibilityClass
from app.modules.files.policy import AttachmentAccess, can_read, is_uploader

CUSTOMER_ORG = uuid.uuid4()
PROVIDER_ORG = uuid.uuid4()
LOCATION = uuid.uuid4()
OTHER_LOCATION = uuid.uuid4()


def _customer(role: str = "customer_manager", locations: set[uuid.UUID] | None = None) -> UserActor:
    return UserActor(
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        organization_id=CUSTOMER_ORG,
        role=role,
        location_ids=frozenset(locations) if locations is not None else None,
    )


def _provider(role: str = "provider_dispatcher") -> UserActor:
    return UserActor(
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        role=role,
    )


def _access(**changes: object) -> AttachmentAccess:
    base = {
        "attachment_id": uuid.uuid4(),
        "visibility_class": VisibilityClass.REQUEST_PRIVATE,
        "processing_state": AttachmentState.READY,
        "owner_kind": "request",
        "customer_org_id": CUSTOMER_ORG,
        "location_id": LOCATION,
    }
    base.update(changes)
    return AttachmentAccess(**base)


def test_customer_sees_own_request_photos() -> None:
    assert can_read(_customer(), _access())
    assert can_read(_customer("customer_employee", {LOCATION}), _access())
    assert not can_read(_customer("customer_employee", {OTHER_LOCATION}), _access())


def test_equipment_photo_is_seen_by_customer_participant_of_its_location() -> None:
    access = _access(owner_kind="equipment")
    assert can_read(_customer(), access)
    assert can_read(_customer("customer_employee", {LOCATION}), access)
    assert not can_read(_customer("customer_employee", {OTHER_LOCATION}), access)


def test_equipment_photo_needs_confirmed_binding_for_provider() -> None:
    access = _access(owner_kind="equipment", service_binding_confirmed=False)
    assert not can_read(_provider(), access)
    assert not can_read(_provider("provider_admin"), access)

    confirmed = _access(owner_kind="equipment", service_binding_confirmed=True)
    assert can_read(_provider(), confirmed)
    assert can_read(_provider("provider_admin"), confirmed)


def test_equipment_photo_integration_key_needs_scope_and_confirmation() -> None:
    confirmed = _access(owner_kind="equipment", service_binding_confirmed=True)
    with_scope = IntegrationActor(
        integration_client_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        scopes=frozenset({"requests:read"}),
    )
    without_scope = IntegrationActor(
        integration_client_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        scopes=frozenset({"marketplace:read"}),
    )
    assert can_read(with_scope, confirmed)
    assert not can_read(without_scope, confirmed)

    unconfirmed = _access(owner_kind="equipment", service_binding_confirmed=False)
    assert not can_read(with_scope, unconfirmed)


def test_provider_needs_live_assignment() -> None:
    for state in (AssignmentState.PENDING, AssignmentState.ACCEPTED, AssignmentState.COMPLETED):
        assert can_read(_provider(), _access(assignment_state=state))
    for state in (AssignmentState.REVOKED, AssignmentState.WITHDRAWN, AssignmentState.DECLINED):
        assert not can_read(_provider(), _access(assignment_state=state))
    assert not can_read(_provider(), _access())


@pytest.mark.parametrize(
    ("route", "state", "expected"),
    [
        ("own_service", AssignmentState.PENDING, True),
        ("marketplace", AssignmentState.PENDING, False),
        ("marketplace", AssignmentState.ACCEPTED, True),
        ("marketplace", AssignmentState.REVOKED, False),
    ],
)
def test_sensitive_opens_after_confirmation(route: str, state: str, expected: bool) -> None:
    access = _access(
        visibility_class=VisibilityClass.REQUEST_SENSITIVE,
        assignment_state=state,
        assignment_route=route,
    )
    assert can_read(_provider(), access) is expected
    assert can_read(OperatorActor(user_id=uuid.uuid4()), access)


def test_public_card_copy_needs_open_card_and_match() -> None:
    access = _access(
        visibility_class=VisibilityClass.PUBLIC_CARD,
        card_open=True,
        listed_in_card=True,
        publication_state=ModerationStatus.PUBLISHED,
    )
    assert can_read(_provider(), access, marketplace_visible=True)
    assert not can_read(_provider(), access, marketplace_visible=False)
    assert not can_read(
        _provider(),
        _access(visibility_class=VisibilityClass.PUBLIC_CARD, card_open=False, listed_in_card=True),
        marketplace_visible=True,
    )
    assert not can_read(
        _provider(),
        _access(
            visibility_class=VisibilityClass.PUBLIC_CARD,
            card_open=True,
            listed_in_card=True,
            publication_state=ModerationStatus.REMOVED,
        ),
        marketplace_visible=True,
    )


def test_public_card_needs_marketplace_scope_for_integration() -> None:
    access = _access(
        visibility_class=VisibilityClass.PUBLIC_CARD,
        card_open=True,
        listed_in_card=True,
        publication_state=ModerationStatus.PUBLISHED,
    )
    with_scope = IntegrationActor(
        integration_client_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        scopes=frozenset({"marketplace:read"}),
    )
    without = IntegrationActor(
        integration_client_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        scopes=frozenset({"requests:read"}),
    )
    assert can_read(with_scope, access, marketplace_visible=True)
    assert not can_read(without, access, marketplace_visible=True)


def test_gallery_and_review_photos_wait_for_moderation() -> None:
    pending = _access(
        visibility_class=VisibilityClass.PROFILE_PUBLIC,
        customer_org_id=None,
        location_id=None,
        provider_org_id=PROVIDER_ORG,
        publication_state=ModerationStatus.PENDING,
    )
    assert not can_read(_customer(), pending)
    assert can_read(_provider("provider_admin"), pending)

    published = _access(
        visibility_class=VisibilityClass.REVIEW_PUBLIC,
        customer_org_id=None,
        location_id=None,
        publication_state=ModerationStatus.PUBLISHED,
    )
    assert can_read(_customer(), published)
    assert can_read(BareUserActor(user_id=uuid.uuid4()), published)


def test_unmoderated_photos_are_seen_only_by_their_side_of_dual_org() -> None:
    customer_side = UserActor(
        user_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        organization_id=PROVIDER_ORG,
        role="customer_manager",
    )
    portfolio = _access(
        visibility_class=VisibilityClass.PROFILE_PUBLIC,
        customer_org_id=None,
        location_id=None,
        provider_org_id=PROVIDER_ORG,
        publication_state=ModerationStatus.PENDING,
    )
    assert not can_read(customer_side, portfolio)
    assert can_read(_provider("provider_admin"), portfolio)

    review_photo = _access(
        visibility_class=VisibilityClass.REVIEW_PUBLIC,
        customer_org_id=None,
        location_id=None,
        review_customer_org_id=PROVIDER_ORG,
        publication_state=ModerationStatus.PENDING,
    )
    assert can_read(customer_side, review_photo)
    assert not can_read(_provider("provider_admin"), review_photo)


def test_evidence_is_for_operator_and_submitter() -> None:
    access = _access(
        visibility_class=VisibilityClass.VERIFICATION_EVIDENCE,
        customer_org_id=None,
        location_id=None,
        verification_org_id=PROVIDER_ORG,
    )
    assert can_read(OperatorActor(user_id=uuid.uuid4()), access)
    assert can_read(_provider("provider_admin"), access)
    assert not can_read(_customer(), access)


def test_operator_does_not_browse_private_request_photos() -> None:
    assert not can_read(OperatorActor(user_id=uuid.uuid4()), _access())


def test_evidence_is_closed_to_ordinary_staff() -> None:
    access = _access(
        visibility_class=VisibilityClass.VERIFICATION_EVIDENCE,
        customer_org_id=None,
        location_id=None,
        verification_org_id=PROVIDER_ORG,
    )
    assert not can_read(_provider("provider_dispatcher"), access)
    customer_case = _access(
        visibility_class=VisibilityClass.VERIFICATION_EVIDENCE, verification_org_id=CUSTOMER_ORG
    )
    assert can_read(_customer("customer_manager"), customer_case)
    assert not can_read(_customer("customer_employee", {LOCATION}), customer_case)


def test_uploader_is_bound_to_membership_and_not_to_copies() -> None:
    author = _customer("customer_employee", {LOCATION})
    own = _access(
        uploaded_by_user_id=author.user_id, uploaded_by_membership_id=author.membership_id
    )
    assert is_uploader(author, own)

    elsewhere = UserActor(
        user_id=author.user_id,
        membership_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role="customer_manager",
    )
    assert not is_uploader(elsewhere, own)
    assert not is_uploader(BareUserActor(author.user_id), own)

    copy = _access(
        uploaded_by_user_id=author.user_id,
        uploaded_by_membership_id=author.membership_id,
        is_copy=True,
    )
    assert not is_uploader(author, copy)
