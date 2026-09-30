import uuid
from dataclasses import dataclass
from enum import StrEnum


class OwnerKind(StrEnum):
    REQUEST = "request"
    MESSAGE = "message"
    EQUIPMENT = "equipment"
    PROVIDER_PROFILE = "provider_profile"
    VERIFICATION_CASE = "verification_case"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class AttachmentOwner:
    kind: OwnerKind
    object_id: uuid.UUID | None = None


def request_owner(request_id: uuid.UUID) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.REQUEST, request_id)


def message_owner(message_id: uuid.UUID) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.MESSAGE, message_id)


def equipment_owner(equipment_id: uuid.UUID) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.EQUIPMENT, equipment_id)


def provider_profile_owner(profile_id: uuid.UUID | None = None) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.PROVIDER_PROFILE, profile_id)


def verification_owner(case_id: uuid.UUID | None = None) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.VERIFICATION_CASE, case_id)


def review_owner(review_id: uuid.UUID) -> AttachmentOwner:
    return AttachmentOwner(OwnerKind.REVIEW, review_id)
