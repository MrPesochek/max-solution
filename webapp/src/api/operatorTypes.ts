import type { components } from './operatorSchema';
import type {
  AttachmentProcessingState,
  AttachmentVisibilityClass,
  ComplaintAppealStatus,
  GuarantorKind,
  ModerationStatus,
  ProviderKind,
  ProviderProfileStatus,
  WarrantyAuthorizationStatus,
} from './types';

type Schemas = components['schemas'];

export type VerificationDecision = 'pending' | 'approved' | 'rejected' | 'needs_information' | 'revoked';
export type VerificationCheckKind = 'requisites' | 'representative' | 'customer_representative';

export interface VerificationCaseOperator
  extends Omit<Schemas['VerificationCaseOperatorView'], 'decision' | 'check_kind'> {
  decision: VerificationDecision;
  check_kind: VerificationCheckKind;
}

export type VerificationDecisionInput = Schemas['VerificationDecisionBody'];

export interface OperatorProviderProfile extends Omit<Schemas['ProviderProfileView'], 'provider_kind' | 'status'> {
  provider_kind: ProviderKind;
  status: ProviderProfileStatus;
}

export type ProfileStatusInput = Schemas['ProfileStatusBody'];
export type RevokeInput = Schemas['RevokeBody'];

export interface OperatorWarrantyAuthorization
  extends Omit<Schemas['WarrantyAuthorizationView'], 'guarantor_kind' | 'status'> {
  guarantor_kind: GuarantorKind;
  status: WarrantyAuthorizationStatus;
}

export type WarrantyAuthorizationInput = Schemas['WarrantyAuthorizationBody'];

export type OperatorBinding = Schemas['OperatorBindingView'];

export interface OperatorAttachment
  extends Omit<Schemas['AttachmentView'], 'processing_state' | 'visibility_class'> {
  processing_state: AttachmentProcessingState;
  visibility_class: AttachmentVisibilityClass;
}

export type ReviewOperatorDecision = 'published' | 'rejected' | 'removed';

export interface ReviewOperator extends Omit<Schemas['ReviewOperatorView'], 'moderation_status'> {
  moderation_status: ModerationStatus;
}

export type ReviewDecisionInput = Schemas['ReviewDecisionBody'];
export type FraudFlagInput = Schemas['FraudFlagBody'];

export interface ModerationCaseOperator
  extends Omit<Schemas['ModerationCaseOperatorView'], 'status' | 'appeal_status'> {
  status: ModerationStatus;
  appeal_status: ComplaintAppealStatus;
}

export type CaseDecisionInput = Schemas['CaseDecisionBody'];

export interface OperatorPage<T> {
  items: T[];
  next_cursor: string | null;
}
