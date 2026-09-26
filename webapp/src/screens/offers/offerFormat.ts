import { strings } from '../../strings/ru';
import type { Offer } from '../../api/types';
import { pluralRu } from '../requests/card/cardFormat';

export function ratingText(offer: Offer): string {
  const provider = offer.provider;
  if (!provider || provider.rating === null || provider.rating === undefined) {
    return provider?.rating_label ?? strings.offers.providerFewReviews;
  }
  const reviews = provider.reviews_count;
  return strings.offers.ratingTag(
    provider.rating.toFixed(1).replace('.', ','),
    typeof reviews === 'number'
      ? pluralRu(reviews, strings.offers.reviewForms)
      : pluralRu(provider.unique_reviewer_orgs_count, strings.offers.orgForms),
  );
}

export function offerStateText(state: Offer['state']): string | null {
  switch (state) {
    case 'expired':
      return strings.offers.expiredBadge;
    case 'withdrawn':
      return strings.offers.withdrawnBadge;
    case 'selected':
      return strings.offers.selectedBadge;
    case 'closed':
      return strings.offers.closedBadge;
    default:
      return null;
  }
}

export function isSelectable(offer: Offer, now = Date.now()): boolean {
  return offer.state === 'active' && new Date(offer.valid_until).getTime() > now;
}
