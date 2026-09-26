import type { components } from './schema';

type Schemas = components['schemas'];

type Loosen<T, K extends keyof T> = Omit<T, K> & { [P in K]?: T[P] | null };

export type Role =
  | 'customer_manager'
  | 'customer_employee'
  | 'provider_admin'
  | 'provider_dispatcher';

export type OrganizationKind = 'customer' | 'provider';

export type MembershipStatus = 'pending' | 'active' | 'revoked';

export type InvitationState = 'active' | 'expired' | 'revoked' | 'used' | 'declined';

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: Record<string, unknown>;
  };
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export type CurrentUser = Schemas['UserView'];

export interface OrganizationRef extends Omit<Schemas['OrganizationRefView'], 'kinds'> {
  kinds: OrganizationKind[];
}

export interface Organization extends Omit<Schemas['OrganizationView'], 'kinds'> {
  kinds: OrganizationKind[];
}

export interface Membership
  extends Omit<Schemas['MembershipView'], 'role' | 'status' | 'organization'> {
  role: Role;
  status: MembershipStatus;
  organization: OrganizationRef;
}

export interface AuthResponse extends Omit<Schemas['AuthResponse'], 'memberships' | 'organizations'> {
  memberships: Membership[];
  organizations: OrganizationRef[];
}

export interface LinkAuthResponse extends AuthResponse {
  target?: string | null;
}

export interface MeResponse extends Omit<Schemas['MeResponse'], 'memberships' | 'organizations'> {
  memberships: Membership[];
  organizations: OrganizationRef[];
}

export type District = Schemas['DistrictView'];
export type City = Schemas['CityView'];

export interface PhotoTemplateSlot {
  code: string;
  label: string;
  required: boolean;
  visibility_class: AttachmentVisibilityClass;
}

export interface EquipmentCategory extends Omit<Schemas['EquipmentCategoryView'], 'photo_template'> {
  photo_template: PhotoTemplateSlot[];
}

export type Location = Schemas['app__modules__catalog__views__LocationView'];
export type LocationInput = Schemas['LocationCreateBody'];
export type LocationUpdateInput = Schemas['LocationUpdateBody'];

export type EquipmentBindingSummary = Loosen<
  Schemas['EquipmentBindingSummaryView'],
  'provider_name' | 'valid_until' | 'guarantor_kind' | 'guarantor_name' | 'provider_has_crm'
>;
export type EquipmentActiveRequest = Schemas['EquipmentActiveRequestView'];

export type Equipment = Omit<
  Schemas['app__modules__catalog__views__EquipmentView'],
  | 'category_code'
  | 'category_name'
  | 'location_name'
  | 'binding'
  | 'active_request'
  | 'has_nameplate_photo'
> & {
  category_code?: string | null;
  category_name?: string | null;
  location_name?: string | null;
  binding?: EquipmentBindingSummary | null;
  active_request?: EquipmentActiveRequest | null;
  has_nameplate_photo?: boolean | null;
};
export type EquipmentInput = Schemas['EquipmentCreateBody'];
export type EquipmentUpdateInput = Schemas['EquipmentUpdateBody'];

export type FirstLocationInput = Schemas['FirstLocationBody'];

export type ProviderKind = 'company' | 'independent_specialist';

export interface CreateOrganizationInput
  extends Omit<Schemas['OrganizationCreateBody'], 'kind' | 'provider_kind'> {
  kind: OrganizationKind;
  provider_kind?: ProviderKind;
}

export type UpdateOrganizationInput = Schemas['OrganizationUpdateBody'];

export interface ParticipationInput extends Omit<Schemas['ParticipationBody'], 'kind' | 'provider_kind'> {
  kind: OrganizationKind;
  provider_kind?: ProviderKind;
}

export interface CreateOrganizationResponse
  extends Omit<Schemas['OrganizationCreatedView'], 'organization' | 'membership'> {
  organization: Organization;
  membership: Membership;
}

export interface Invitation extends Omit<Schemas['InvitationView'], 'role' | 'state'> {
  role: Role | null;
  state: InvitationState;
}

export interface InvitationIssued extends Omit<Schemas['InvitationIssuedView'], 'role' | 'state'> {
  role: Role | null;
  state: InvitationState;
}

export interface CreateInvitationInput extends Omit<Schemas['InvitationCreateBody'], 'role'> {
  role: Role;
}

export interface InvitationPreview extends Omit<Schemas['InvitationPreviewView'], 'role' | 'state'> {
  role: Role | null;
  state: InvitationState;
}

export interface StaffMember extends Omit<Schemas['MemberView'], 'role' | 'status'> {
  role: Role;
  status: MembershipStatus;
}

export type ProviderProfileStatus =
  | 'draft'
  | 'pending_review'
  | 'needs_information'
  | 'active'
  | 'suspended'
  | 'rejected';

export type VerificationDecision = 'pending' | 'approved' | 'rejected' | 'needs_information' | 'revoked';
export type VerificationCheckKind = 'requisites' | 'representative' | 'customer_representative';

export type BindingStatus = 'pending' | 'confirmed' | 'rejected' | 'revoked';
export type BindingBasis = 'warranty' | 'service_contract' | 'preferred_provider';
export type BindingDecision = 'confirm' | 'reject';
export type GuarantorKind = 'manufacturer' | 'seller' | 'service_org';
export type WarrantyAuthorizationStatus = 'pending' | 'active' | 'expired' | 'revoked';

export type IntegrationClientStatus = 'active' | 'revoked';
export type WebhookSubscriptionStatus = 'active' | 'disabled';
export type DeliveryState = 'queued' | 'delivered' | 'retrying' | 'failed' | 'blocked';

export type ProviderCategory = Schemas['ProviderCategoryView'];
export type ProviderServiceArea = Schemas['ProviderServiceAreaView'];
export type ProviderBrandRestriction = Schemas['ProviderBrandRestrictionView'];
export type VerificationBadge = Schemas['VerificationBadgeView'];

export interface WarrantyAuthorization
  extends Omit<Schemas['WarrantyAuthorizationView'], 'guarantor_kind' | 'status'> {
  guarantor_kind: GuarantorKind;
  status: WarrantyAuthorizationStatus;
}

export interface ProviderProfile extends Omit<Schemas['ProviderProfileView'], 'provider_kind' | 'status'> {
  provider_kind: ProviderKind;
  status: ProviderProfileStatus;
}

export type GalleryItem = Schemas['GalleryItemView'];

export interface ProviderPublicProfile
  extends Omit<
    Schemas['ProviderPublicProfileView'],
    'provider_kind' | 'warranty_authorizations' | 'gallery_items'
  > {
  gallery_items?: GalleryItem[] | null;
  provider_kind: ProviderKind;
  warranty_authorizations: WarrantyAuthorization[];
}

export interface ProviderCatalogItem extends Omit<Schemas['ProviderCatalogItemView'], 'provider_kind'> {
  provider_kind: ProviderKind;
}

export type ServiceAreaInput = Schemas['ServiceAreaBody'];
export type BrandRestrictionInput = Schemas['BrandRestrictionBody'];
export type ProviderProfileUpdateInput = Schemas['ProviderProfileUpdateBody'];

export interface ServiceBinding
  extends Omit<
    Schemas['ServiceBindingView'],
    'status' | 'basis' | 'guarantor_kind' | 'warranty_authorization' | 'guarantor_stated_by_provider'
  > {
  guarantor_stated_by_provider?: boolean | null;
  status: BindingStatus;
  basis: BindingBasis;
  guarantor_kind: GuarantorKind | null;
  warranty_authorization: WarrantyAuthorization | null;
}

export interface ProviderBinding extends Omit<Schemas['ProviderBindingView'], 'status' | 'basis'> {
  status: BindingStatus;
  basis: BindingBasis;
}

export type BindingRequestInput = Schemas['BindingRequestBody'];
export type ContactBindingInput = Schemas['ContactBindingBody'];
export type BindingRequestAccepted = Schemas['BindingRequestAcceptedView'];
export type BindingRespondInput = Schemas['BindingRespondBody'];
export type BindingRevokeInput = Schemas['BindingRevokeBody'];
export type BindingInvitationAcceptInput = Schemas['BindingInvitationAcceptBody'];
export type BindingInvitationItem = Schemas['BindingInvitationItemView'];
export type BindingInvitationItemInput = Schemas['BindingInvitationItemBody'];
export type BindingItemMatch = Schemas['BindingItemMatchBody'];

export interface BindingInvitation
  extends Omit<Schemas['BindingInvitationView'], 'state' | 'basis' | 'guarantor_kind' | 'guarantor_name'> {
  guarantor_kind?: GuarantorKind | null;
  guarantor_name?: string | null;
  state: InvitationState;
  basis: BindingBasis | null;
}

export interface BindingInvitationIssued
  extends Omit<Schemas['BindingInvitationIssuedView'], 'state' | 'basis' | 'guarantor_kind' | 'guarantor_name'> {
  guarantor_kind?: GuarantorKind | null;
  guarantor_name?: string | null;
  state: InvitationState;
  basis: BindingBasis | null;
}

export interface BindingInvitationPreview
  extends Omit<Schemas['BindingInvitationPreviewView'], 'state' | 'basis' | 'guarantor_kind' | 'guarantor_name'> {
  guarantor_kind?: GuarantorKind | null;
  guarantor_name?: string | null;
  state: InvitationState;
  basis: BindingBasis | null;
}

export type BindingInvitationCreateInput = Schemas['BindingInvitationCreateBody'];
export type BindingInvitationDeclineInput = Schemas['BindingInvitationDeclineBody'];

export interface VerificationCase
  extends Omit<Schemas['VerificationCaseView'], 'decision' | 'check_kind'> {
  decision: VerificationDecision;
  check_kind: VerificationCheckKind;
}

export type VerificationInformationInput = Schemas['VerificationInformationBody'];

export const INTEGRATION_SCOPES = [
  'requests:read',
  'requests:write',
  'marketplace:read',
  'marketplace:write',
  'equipment:read',
  'service_bindings:read',
  'service_bindings:write',
  'reviews:read',
  'reviews:write',
  'webhooks:manage',
  'events:read',
] as const;

export type IntegrationScope = (typeof INTEGRATION_SCOPES)[number];

export type ApiKeyWarning = 'service_bindings_write_shared';

export interface ApiKey extends Omit<Schemas['ApiKeyView'], 'status' | 'scopes' | 'warnings'> {
  status: IntegrationClientStatus;
  scopes: IntegrationScope[];
  warnings?: ApiKeyWarning[] | null;
}

export interface ApiKeyIssued
  extends Omit<Schemas['ApiKeyIssuedView'], 'status' | 'scopes' | 'warnings'> {
  status: IntegrationClientStatus;
  scopes: IntegrationScope[];
  warnings?: ApiKeyWarning[] | null;
}

export type ApiKeyCreateInput = Schemas['ApiKeyCreateBody'];

export interface WebhookSubscription extends Omit<Schemas['WebhookSubscriptionView'], 'status'> {
  status: WebhookSubscriptionStatus;
}

export interface WebhookSubscriptionIssued
  extends Omit<Schemas['WebhookSubscriptionSecretView'], 'status'> {
  status: WebhookSubscriptionStatus;
}

export type WebhookSubscriptionCreateInput = Schemas['WebhookSubscriptionCreateBody'];

export type IntegrationSummary = Schemas['IntegrationSummaryView'];
export type IntegrationDeliveriesStats = Schemas['IntegrationDeliveriesStatsView'];

export interface Delivery extends Omit<Schemas['DeliveryView'], 'state'> {
  state: DeliveryState;
}

export interface DeliveryPage extends Omit<Schemas['DeliveryPageView'], 'items'> {
  items: Delivery[];
}

export type ModerationStatus = 'pending' | 'published' | 'rejected' | 'removed';

export type ComplaintStatus = ModerationStatus | 'withdrawn';

export type ReviewEligibilityMode = 'create' | 'edit' | 'needs_admission';

export type ReviewReply = Schemas['ReviewReplyView'];
export type ReviewPublishedSnapshot = Schemas['ReviewPublishedSnapshotView'];

export interface MyReview extends Omit<Schemas['MyReviewView'], 'moderation_status'> {
  moderation_status: ModerationStatus;
}

export interface ReviewEligibility extends Omit<Schemas['ReviewEligibilityView'], 'mode'> {
  mode: ReviewEligibilityMode | null;
}

export interface RequestReviewState extends Omit<Schemas['RequestReviewStateView'], 'review' | 'eligibility'> {
  review: MyReview | null;
  eligibility: ReviewEligibility;
}

export type ReviewSubmitInput = Schemas['ReviewSubmitBody'];
export type ReviewReplyInput = Schemas['ReviewReplyBody'];
export type ReviewAppealInput = Schemas['ReviewAppealBody'];
export type ReviewAppealReasonCode = NonNullable<Schemas['ReviewAppealBody']['reason_code']>;

export interface ProviderReview extends Omit<Schemas['ProviderReviewView'], 'complaint'> {
  complaint?: { id: string; status: ComplaintStatus } | null;
}

export type PublicReview = Schemas['PublicReviewView'];

export type ComplaintSubjectType = 'provider_profile' | 'review' | 'attachment' | 'no_show';
export type ComplaintAppealStatus = 'pending' | 'published' | 'rejected' | 'removed' | null;

export interface Complaint
  extends Omit<
    Schemas['ComplaintView'],
    'subject_type' | 'status' | 'appeal_status' | 'subject_id' | 'review_id' | 'reason_code'
  > {
  subject_type: ComplaintSubjectType;
  status: ComplaintStatus;
  appeal_status: ComplaintAppealStatus;
  subject_id?: string | null;
  review_id?: string | null;
  reason_code?: ReviewAppealReasonCode | null;
}

export type ComplaintCreateInput = Schemas['ComplaintCreateBody'];

export type RequestRoute = 'own_service' | 'marketplace';

export type RequestStatus =
  | 'draft'
  | 'approval_required'
  | 'awaiting_provider'
  | 'searching'
  | 'awaiting_assignment_confirmation'
  | 'accepted'
  | 'scheduled'
  | 'in_progress'
  | 'completion_reported'
  | 'closed'
  | 'action_required'
  | 'cancellation_pending'
  | 'cancelled';

export type Urgency = 'critical' | 'urgent' | 'normal';

export type AssignmentState =
  | 'pending'
  | 'accepted'
  | 'declined'
  | 'expired'
  | 'revoked'
  | 'withdrawn'
  | 'completed';

export type WarrantyDecision = 'not_stated' | 'warranty' | 'not_warranty' | 'undetermined';

export type OfferState = 'active' | 'selected' | 'expired' | 'withdrawn' | 'closed';

export type VisitProposalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'superseded';

export type RepairQuoteStatus = VisitProposalStatus;

export type CancellationTarget = 'cancel_request' | 'change_provider';

export type CancellationStatus = 'pending' | 'accepted' | 'disputed' | 'withdrawn' | 'force_closed';

export type AttachmentProcessingState = 'quarantined' | 'ready' | 'rejected';

export type AttachmentVisibilityClass =
  | 'request_private'
  | 'request_sensitive'
  | 'public_card'
  | 'profile_public'
  | 'review_public'
  | 'verification_evidence';

export type Price = Schemas['PriceView'];

export type RequestEquipmentSnapshot = Schemas['app__modules__requests__views__EquipmentView'];
export type RequestLocationSnapshot = Schemas['app__modules__requests__views__LocationView'];
export type FieldWorker = Schemas['FieldWorkerView'];

export type ProviderRatingSummary = Loosen<
  Schemas['ProviderSummaryRatingView'],
  'verification_marks' | 'reviews_count' | 'unique_reviewer_orgs_count'
>;

export interface Assignment
  extends Omit<
    Schemas['AssignmentView'],
    'route' | 'state' | 'warranty_decision' | 'en_route_at' | 'provider' | 'reminder_at'
  > {
  route: RequestRoute;
  state: AssignmentState;
  warranty_decision: WarrantyDecision;
  en_route_at?: string | null;
  provider?: ProviderRatingSummary | null;
  reminder_at?: string | null;
}

export interface VisitProposal extends Omit<Schemas['VisitProposalView'], 'status'> {
  status: VisitProposalStatus;
}

export interface RepairQuote extends Omit<Schemas['RepairQuoteView'], 'status' | 'warranty_terms'> {
  status: RepairQuoteStatus;
  warranty_terms?: string | null;
}

export interface CancellationRequest
  extends Omit<Schemas['CancellationRequestView'], 'target' | 'status'> {
  target: CancellationTarget;
  status: CancellationStatus;
}

export type OfferProvider = Loosen<Schemas['OfferProviderView'], 'reviews_count'>;

export interface Offer extends Omit<Schemas['OfferView'], 'state' | 'provider'> {
  state: OfferState;
  provider?: OfferProvider | null;
}

export type DeliveryStatus = Schemas['DeliveryStatusView'];

export type RequestMessage = Loosen<
  Schemas['MessageView'],
  'author_display_name' | 'author_organization_name' | 'author_label' | 'delivery'
>;
export type DialogMessageInput = Schemas['DialogMessageBody'];
export type MessagesRead = Schemas['MessagesReadView'];
export type PendingDecision = Schemas['PendingDecisionView'];
export type RequestEvent = Schemas['RequestEventView'];
export type SearchState = Schemas['SearchStateView'];
export type PublicCardStatus = 'open' | 'closed';

export interface RequestPublicCard
  extends Omit<Schemas['RequestPublicCardView'], 'urgency' | 'status' | 'city_name' | 'district_name'> {
  urgency: Urgency;
  status: PublicCardStatus;
  city_name?: string | null;
  district_name?: string | null;
}
export type ExistingBinding = Schemas['ExistingBindingView'];

export interface PublicCardPreview
  extends Omit<Schemas['PublicCardPreviewView'], 'public_card' | 'existing_binding'> {
  public_card: RequestPublicCard;
  existing_binding: ExistingBinding | null;
}

export interface MarketplaceListItem
  extends Omit<Schemas['MarketplaceListItemView'], 'urgency' | 'city_name' | 'district_name'> {
  urgency: Urgency;
  city_name?: string | null;
  district_name?: string | null;
}

export interface MarketplaceCard extends Omit<Schemas['MarketplaceCardView'], 'card' | 'my_offers'> {
  card: RequestPublicCard;
  my_offers: Offer[];
}

export type AttachmentOwnerKind =
  | 'request'
  | 'message'
  | 'equipment'
  | 'provider_profile'
  | 'verification_case';

export interface Attachment
  extends Omit<Schemas['AttachmentView'], 'processing_state' | 'visibility_class' | 'caption'> {
  processing_state: AttachmentProcessingState;
  visibility_class: AttachmentVisibilityClass;
  caption?: string | null;
}

export type PortfolioCaptionInput = Schemas['PortfolioCaptionBody'];

interface RequestCommon {
  status: RequestStatus;
  route: RequestRoute;
  urgency: Urgency;
  equipment: RequestEquipmentSnapshot;
  location: RequestLocationSnapshot;
  visit_proposals: VisitProposal[];
  repair_quotes: RepairQuote[];
  cancellation: CancellationRequest | null;
  attachments: Attachment[];
}

export interface RequestCustomer
  extends Omit<
      Schemas['RequestCustomerView'],
      keyof RequestCommon | 'assignment' | 'search'
    >,
    RequestCommon {
  assignment: Assignment | null;
  search: SearchState | null;
}

export interface RequestProvider
  extends Omit<Schemas['RequestProviderView'], keyof RequestCommon | 'assignment'>,
    RequestCommon {
  assignment: Assignment;
}

export type RequestFormerProvider = Omit<Schemas['RequestFormerProviderView'], 'assignment'> & {
  assignment: Assignment;
};

type RequestListItemExtra =
  | 'visit_window_start'
  | 'visit_window_end'
  | 'timezone'
  | 'en_route_at'
  | 'field_worker_name'
  | 'unread_messages_count'
  | 'last_message_at'
  | 'my_review_rating'
  | 'closed_at'
  | 'cancelled_at';

export interface RequestListItem
  extends Omit<
    Schemas['RequestListItemView'],
    'status' | 'route' | 'urgency' | 'assignment_state' | RequestListItemExtra
  > {
  status: RequestStatus;
  route: RequestRoute;
  urgency: Urgency;
  assignment_state: AssignmentState | null;
  visit_window_start?: string | null;
  visit_window_end?: string | null;
  timezone?: string | null;
  en_route_at?: string | null;
  field_worker_name?: string | null;
  unread_messages_count?: number | null;
  last_message_at?: string | null;
  my_review_rating?: number | null;
  closed_at?: string | null;
  cancelled_at?: string | null;
}

export type RequestDraftCreateInput = Omit<Schemas['RequestDraftCreateBody'], 'route' | 'urgency'> & {
  route: RequestRoute;
  urgency: Urgency;
};

export type RequestDraftUpdateInput = Omit<Schemas['RequestDraftUpdateBody'], 'urgency'> & {
  urgency?: Urgency | null;
};

export type PublicCardInput = Schemas['RequestPublicCardBody'];
export type PublicCardPreviewInput = Schemas['RequestPublicCardPreviewBody'];
export type SelectOfferInput = Schemas['RequestSelectOfferBody'];
export type UpdateDetailsInput = Omit<Schemas['RequestUpdateDetailsBody'], 'urgency'> & {
  urgency?: Urgency | null;
};
export type VisitDecisionInput = Schemas['RequestVisitDecisionBody'];
export type QuoteDecisionInput = Schemas['RequestQuoteDecisionBody'];

export type CancellationInput = Omit<Schemas['RequestCancellationBody'], 'target'> & {
  target: CancellationTarget;
};
export type CancellationIdInput = Schemas['RequestCancellationIdBody'];
export type RejectCompletionInput = Schemas['RequestRejectCompletionBody'];
export type FollowupInput = Omit<Schemas['RequestFollowupBody'], 'urgency'> & {
  urgency?: Urgency | null;
};
export type MessageInput = Schemas['RequestMessageBody'];
export type SubmitToOwnServiceInput = Schemas['RequestSubmitToOwnServiceBody'];
export type MarketplaceOfferInput = Schemas['MarketplaceOfferSubmitBody'];
export type MarketplaceOfferWithdrawInput = Schemas['MarketplaceOfferWithdrawBody'];

export type AssignmentAcceptInput = Schemas['AssignmentAcceptBody'];
export type AssignmentDeclineInput = Schemas['AssignmentDeclineBody'];
export type AssignmentWithdrawInput = Schemas['AssignmentWithdrawBody'];
export type AssignmentProposeVisitInput = Schemas['AssignmentProposeVisitBody'];
export type AssignmentRepairQuoteInput = Schemas['AssignmentRepairQuoteBody'];
export type AssignmentStartWorkInput = Schemas['AssignmentStartWorkBody'];
export type AssignmentMarkEnRouteInput = Schemas['AssignmentMarkEnRouteBody'];
export type AssignmentReportCompletionInput = Schemas['AssignmentReportCompletionBody'];
export type AssignmentCancellationResponseInput = Schemas['AssignmentCancellationResponseBody'];
export type AssignmentWarrantyDecisionInput = Schemas['AssignmentWarrantyDecisionBody'];
export type AssignmentFieldWorkerInput = Schemas['AssignmentFieldWorkerBody'];

export type ProviderCount = Schemas['ProviderCountView'];

export type AccessRequestInput = Schemas['AccessRequestBody'];
export type AccessRequestSent = Schemas['AccessRequestSentView'];
