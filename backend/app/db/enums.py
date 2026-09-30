from enum import StrEnum


class LegalForm(StrEnum):
    OOO = "ooo"
    IP = "ip"
    SELF_EMPLOYED = "self_employed"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class MembershipRole(StrEnum):
    CUSTOMER_EMPLOYEE = "customer_employee"
    CUSTOMER_MANAGER = "customer_manager"
    PROVIDER_ADMIN = "provider_admin"
    PROVIDER_DISPATCHER = "provider_dispatcher"


class MembershipStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


class PlatformRoleName(StrEnum):
    OPERATOR = "operator"


class InvitationKind(StrEnum):
    MEMBERSHIP = "membership"
    SERVICE_BINDING = "service_binding"


class InvitationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
    DECLINED = "declined"


class ProviderKind(StrEnum):
    COMPANY = "company"
    INDEPENDENT_SPECIALIST = "independent_specialist"


class ProviderProfileStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    NEEDS_INFORMATION = "needs_information"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class VerificationSubjectType(StrEnum):
    ORGANIZATION_DETAILS = "organization_details"
    REPRESENTATIVE = "representative"
    CUSTOMER_REPRESENTATIVE = "customer_representative"


class VerificationDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_INFORMATION = "needs_information"
    REVOKED = "revoked"


class GuarantorKind(StrEnum):
    MANUFACTURER = "manufacturer"
    SELLER = "seller"
    SERVICE_ORG = "service_org"


class WarrantyAuthorizationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class BindingBasis(StrEnum):
    WARRANTY = "warranty"
    SERVICE_CONTRACT = "service_contract"
    PREFERRED_PROVIDER = "preferred_provider"


class BindingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    REVOKED = "revoked"


class RequestRoute(StrEnum):
    OWN_SERVICE = "own_service"
    MARKETPLACE = "marketplace"


class RequestStatus(StrEnum):
    DRAFT = "draft"
    APPROVAL_REQUIRED = "approval_required"
    AWAITING_PROVIDER = "awaiting_provider"
    SEARCHING = "searching"
    AWAITING_ASSIGNMENT_CONFIRMATION = "awaiting_assignment_confirmation"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETION_REPORTED = "completion_reported"
    CLOSED = "closed"
    ACTION_REQUIRED = "action_required"
    CANCELLATION_PENDING = "cancellation_pending"
    CANCELLED = "cancelled"


class Urgency(StrEnum):
    CRITICAL = "critical"
    URGENT = "urgent"
    NORMAL = "normal"


class ClosureKind(StrEnum):
    CUSTOMER_CONFIRMED = "customer_confirmed"
    AUTO_TIMEOUT = "auto_timeout"


class PublicCardStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class AssignmentState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"
    WITHDRAWN = "withdrawn"
    COMPLETED = "completed"


class WarrantyDecision(StrEnum):
    NOT_STATED = "not_stated"
    WARRANTY = "warranty"
    NOT_WARRANTY = "not_warranty"
    UNDETERMINED = "undetermined"


class VatMode(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    NOT_APPLICABLE = "not_applicable"


class Currency(StrEnum):
    RUB = "RUB"


class OfferStatus(StrEnum):
    ACTIVE = "active"
    SELECTED = "selected"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class VisitProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class RepairQuoteStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class CancellationTarget(StrEnum):
    CANCEL_REQUEST = "cancel_request"
    CHANGE_PROVIDER = "change_provider"


class CancellationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    WITHDRAWN = "withdrawn"
    FORCE_CLOSED = "force_closed"


class CancellationResolutionKind(StrEnum):
    PROVIDER_CONFIRMED = "provider_confirmed"
    CUSTOMER_UNILATERAL = "customer_unilateral"
    MANUAL = "manual"


class MessageVisibilityScope(StrEnum):
    ALL_PARTICIPANTS = "all_participants"
    PRE_ASSIGNMENT_THREAD = "pre_assignment_thread"


class MessageAuthorKind(StrEnum):
    CUSTOMER_MEMBERSHIP = "customer_membership"
    PROVIDER_MEMBERSHIP = "provider_membership"
    INTEGRATION_CLIENT = "integration_client"
    SYSTEM = "system"


class RequestEventActorKind(StrEnum):
    CUSTOMER_MEMBERSHIP = "customer_membership"
    PROVIDER_MEMBERSHIP = "provider_membership"
    INTEGRATION_CLIENT = "integration_client"
    SYSTEM = "system"
    OPERATOR = "operator"


class AttachmentOwnerKind(StrEnum):
    REQUEST = "request"
    MESSAGE = "message"
    PROFILE = "profile"
    REVIEW = "review"
    VERIFICATION = "verification"
    MODERATION = "moderation"
    EQUIPMENT = "equipment"


class VisibilityClass(StrEnum):
    REQUEST_PRIVATE = "request_private"
    REQUEST_SENSITIVE = "request_sensitive"
    PUBLIC_CARD = "public_card"
    PROFILE_PUBLIC = "profile_public"
    REVIEW_PUBLIC = "review_public"
    VERIFICATION_EVIDENCE = "verification_evidence"


class AttachmentState(StrEnum):
    QUARANTINED = "quarantined"
    READY = "ready"
    REJECTED = "rejected"


class AttachmentVariantKind(StrEnum):
    ORIGINAL = "original"
    SAFE_COPY = "safe_copy"
    PREVIEW = "preview"
    PUBLIC_COPY = "public_copy"


class ModerationStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"
    REMOVED = "removed"
    WITHDRAWN = "withdrawn"


class ModerationSubjectType(StrEnum):
    PROVIDER_PROFILE = "provider_profile"
    REVIEW = "review"
    ATTACHMENT = "attachment"
    SERVICE_BINDING = "service_binding"
    NO_SHOW = "no_show"


class IntegrationClientStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class WebhookSubscriptionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class IntegrationEventType(StrEnum):
    REQUEST_ASSIGNED = "request.assigned"
    REQUEST_CHANGED = "request.changed"
    MESSAGE_CREATED = "message.created"
    OFFER_SELECTED = "offer.selected"
    ASSIGNMENT_REVOKED = "assignment.revoked"
    VISIT_PROPOSAL_RESPONDED = "visit_proposal.responded"
    REPAIR_QUOTE_RESPONDED = "repair_quote.responded"
    CANCELLATION_REQUESTED = "cancellation.requested"
    REQUEST_CLOSED = "request.closed"
    SERVICE_BINDING_CHANGED = "service_binding.changed"
    MARKETPLACE_REQUEST_AVAILABLE = "marketplace.request.available"
    MARKETPLACE_REQUEST_CLOSED = "marketplace.request.closed"


class DeliveryState(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    RETRYING = "retrying"
    FAILED = "failed"
    BLOCKED = "blocked"


class NotificationState(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class AuditActorKind(StrEnum):
    USER = "user"
    OPERATOR = "operator"
    INTEGRATION_CLIENT = "integration_client"
    SYSTEM = "system"


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
