import { useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRequestOffers } from '../../api/hooks/useOffers';
import { ErrorState } from '../../components/states/ErrorState';
import { Skeleton } from '../../components/states/Skeleton';
import { useCountdown } from '../../lib/datetime';
import { formatPrice, isPriceKnown, vatModeLabel } from '../../lib/money';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note, PageTitle, PriceBlock, SectionCaption, TextCard } from '../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { List, ListRow } from '../../ui/List';
import { StatusHero } from '../../ui/StatusHero';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { requestFallback, useCustomerRequest } from '../requests/card/customerRequest';
import { relativeWindow, timeOrDate } from '../requests/card/cardFormat';
import { offerStateText, ratingText } from './offerFormat';
import { useOfferSelection } from './useOfferSelection';

export function OfferDetailScreen() {
  const { id, offerId } = useParams<{ id: string; offerId: string }>();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const offersQuery = useRequestOffers(id);
  const selection = useOfferSelection(request, offersQuery);
  const offer = offersQuery.data?.find((o) => o.id === offerId);
  const countdown = useCountdown(offer?.valid_until);
  const back = id ? `/requests/${id}/offers` : undefined;
  const o = strings.offers;

  if (!activeMembership || !id || !offerId) return null;
  const title = offer?.provider?.display_name ?? o.providerFallback;
  const fallback = requestFallback({
    query,
    request,
    title,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;

  if (offersQuery.isPending) {
    return (
      <Screen title={title} back={back}>
        <Skeleton lines={5} />
      </Screen>
    );
  }
  if (offersQuery.isError) {
    return (
      <Screen title={title} back={back}>
        <ErrorState error={offersQuery.error} onRetry={() => void offersQuery.refetch()} />
      </Screen>
    );
  }
  if (!offer) {
    return (
      <Screen title={title} back={back}>
        <StatusHero illustration="status-offers" top={40} title={o.inactiveTitle}>
          {o.notFound}
        </StatusHero>
      </Screen>
    );
  }

  const tz = request.location.timezone;
  const known = isPriceKnown(offer.price);
  const price = formatPrice(offer.price);
  const selectable = offer.state === 'active' && !countdown.expired && request.status === 'searching';
  const stateText =
    offer.state !== 'active' ? offerStateText(offer.state) : countdown.expired ? o.expiredBadge : null;
  const vat = known ? vatModeLabel(offer.price.vat_mode) : null;

  const rows: KeyValueRow[] = [
    {
      label: o.whenLabel,
      value: offer.visit_window_start
        ? relativeWindow(offer.visit_window_start, offer.visit_window_end, tz, true)
        : o.visitWindowUnknown,
    },
    { label: o.scopeLabel, value: offer.scope_description ?? o.defaultScope },
  ];
  if (vat) rows.push({ label: strings.approvals.vatLabel, value: vat });
  if (offer.access_requirements) rows.push({ label: o.onSiteLabel, value: offer.access_requirements });
  rows.push({
    label: o.validUntilRow,
    value: timeOrDate(offer.valid_until, tz),
    tone: countdown.expired ? 'error' : undefined,
  });

  return (
    <Screen
      title={title}
      back={back}
      actions={
        selectable ? (
          <BottomActions>
            <ActionButton disabled={selection.runner.busy} onClick={() => selection.confirm(offer)}>
              {known ? o.selectFor(price) : o.select}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      <PageTitle subtitle={ratingText(offer)}>{title}</PageTitle>
      {!selection.confirming && (
        <div className="ui-pad">
          <ActionFeedback feedback={selection.runner.feedback} />
        </div>
      )}
      {stateText && (
        <Banner tone="w" title={o.inactiveTitle}>
          {stateText}
        </Banner>
      )}
      {known ? (
        <PriceBlock value={price} caption={o.priceCaption} />
      ) : (
        <PriceBlock value={o.priceUnknownTitle} caption={o.priceUnknownCaption} />
      )}
      <KeyValueRows rows={rows} />
      {offer.comment && (
        <>
          <SectionCaption>{o.commentLabel}</SectionCaption>
          <TextCard>{offer.comment}</TextCard>
        </>
      )}
      <List>
        {offer.provider && <ListRow title={o.profileRow} chevron to={`/providers/${offer.provider.id}`} />}
        {request.status === 'searching' && (
          <ListRow title={o.askQuestionRow} chevron to={`/requests/${id}/offers/${offer.id}/messages`} />
        )}
      </List>
      {known ? (
        <Note>{o.afterSelectNote}</Note>
      ) : (
        <Banner tone="y" title={o.notConsentTitle}>
          {o.notConsentText}
        </Banner>
      )}
      {selection.sheet}
    </Screen>
  );
}
