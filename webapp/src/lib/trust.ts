import type { BindingStatus, ProviderProfileStatus, VerificationDecision } from '../api/types';

export type Tone = 'neutral' | 'positive' | 'warning' | 'negative';

const REQUISITE_EDIT_STATUSES: ProviderProfileStatus[] = ['draft', 'needs_information'];
const PROFILE_EDIT_STATUSES: ProviderProfileStatus[] = ['draft', 'needs_information', 'pending_review', 'active'];

export function canEditRequisites(status: ProviderProfileStatus): boolean {
  return REQUISITE_EDIT_STATUSES.includes(status);
}

export function canEditProfileFields(status: ProviderProfileStatus): boolean {
  return PROFILE_EDIT_STATUSES.includes(status);
}

export function canSubmitProfile(status: ProviderProfileStatus): boolean {
  return REQUISITE_EDIT_STATUSES.includes(status);
}

export function canToggleAccepting(status: ProviderProfileStatus): boolean {
  return status === 'active';
}

export function profileStatusTone(status: ProviderProfileStatus): Tone {
  switch (status) {
    case 'active':
      return 'positive';
    case 'needs_information':
      return 'warning';
    case 'suspended':
    case 'rejected':
      return 'negative';
    case 'pending_review':
    case 'draft':
    default:
      return 'neutral';
  }
}

export function bindingStatusTone(status: BindingStatus): Tone {
  switch (status) {
    case 'confirmed':
      return 'positive';
    case 'rejected':
    case 'revoked':
      return 'negative';
    case 'pending':
    default:
      return 'neutral';
  }
}

export function verificationDecisionTone(decision: VerificationDecision): Tone {
  switch (decision) {
    case 'approved':
      return 'positive';
    case 'needs_information':
      return 'warning';
    case 'rejected':
    case 'revoked':
      return 'negative';
    case 'pending':
    default:
      return 'neutral';
  }
}

export function badgeTone(confirmed: boolean): Tone {
  return confirmed ? 'positive' : 'neutral';
}

export function formatRating(rating: number | null | undefined, ratingLabel: string | null | undefined): string {
  if (rating === null || rating === undefined) return ratingLabel ?? 'Мало отзывов';
  return rating.toFixed(1);
}
