import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRequestOffers } from '../../api/hooks/useOffers';
import type { Offer } from '../../api/types';
import { ErrorState } from '../../components/states/ErrorState';
import { Skeleton } from '../../components/states/Skeleton';
import { formatPrice, isPriceKnown, vatModeLabel } from '../../lib/money';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Avatar, Note, PageTitle } from '../../ui/blocks/Blocks';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { SceneBanner } from '../../ui/SceneBanner';
import { StatusHero } from '../../ui/StatusHero';
import { requestFallback, useCustomerRequest } from '../requests/card/customerRequest';
import { pluralRu, relativeWindow, timeOrDate } from '../requests/card/cardFormat';
import { isSelectable, offerStateText, ratingText } from './offerFormat';
import { useOfferSelection } from './useOfferSelection';
import '../../components/request/request.css';

function byTime(a: Offer, b: Offer): number {
  const at = a.visit_window_start ? Date.parse(a.visit_window_start) : Infinity;
  const bt = b.visit_window_start ? Date.parse(b.visit_window_start) : Infinity;
  return at - bt;
}

export function OffersScreen() {
  const { id } = useParams<{ id: string }>();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const offersQuery = useRequestOffers(id);
  const selection = useOfferSelection(request, offersQuery);
  const [picked, setPicked] = useState<string | null>(null);
  const back = id ? `/requests/${id}` : undefined;
  const o = strings.offers;

  if (!activeMembership || !id) return null;
  const fallback = requestFallback({
    query,
    request,
    title: o.listTitle,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;

  const tz = request.location.timezone;

  if (request.status === 'awaiting_assignment_confirmation') {
    return (
      <Screen
        title={o.listTitle}
        back={back}
        actions={
          <BottomActions>
            <ActionButton kind="s" to={`/requests/${id}`}>
              {o.toRequest}
            </ActionButton>
          </BottomActions>
        }
      >
        <StatusHero illustration="status-waiting" top={40} title={o.awaitingConfirmationTitle}>
          {o.awaitingConfirmationDescription}
        </StatusHero>
      </Screen>
    );
  }

  if (offersQuery.isPending) {
    return (
      <Screen title={o.listTitle} back={back}>
        <Skeleton lines={5} />
      </Screen>
    );
  }
  if (offersQuery.isError) {
    return (
      <Screen title={o.listTitle} back={back}>
        <ErrorState error={offersQuery.error} onRetry={() => void offersQuery.refetch()} />
      </Screen>
    );
  }

  const offers = offersQuery.data ?? [];
  const now = Date.now();
  const sorted = [...offers].sort((a, b) => {
    const activeDiff = Number(isSelectable(b, now)) - Number(isSelectable(a, now));
    return activeDiff || byTime(a, b);
  });
  const selectable = sorted.filter((offer) => isSelectable(offer, now) && request.status === 'searching');
  const chosen = selectable.find((offer) => offer.id === picked) ?? selectable[0];
  const deadline = selectable
    .map((offer) => offer.valid_until)
    .sort()
    .at(0);

  if (offers.length === 0) {
    return (
      <Screen title={o.listTitle} back={back}>
        <StatusHero illustration="status-search" top={40} title={o.empty}>
          {o.empty24h}
        </StatusHero>
      </Screen>
    );
  }

  return (
    <Screen
      title={o.listTitle}
      back={back}
      actions={
        chosen ? (
          <BottomActions>
            <ActionButton disabled={selection.runner.busy} onClick={() => selection.confirm(chosen)}>
              {o.selectNamed(chosen.provider?.display_name ?? o.providerFallback)}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      <SceneBanner name="status-offers" height={130} />
      <PageTitle subtitle={deadline ? o.chooseUntil(timeOrDate(deadline, tz)) : o.noneSelectable}>
        {pluralRu(offers.length, strings.requests.card.offerForms)}
      </PageTitle>
      <div className="request-offers">
        <ChoiceGroup label={o.title}>
          {sorted.map((offer) => {
            const name = offer.provider?.display_name ?? o.providerFallback;
            const active = isSelectable(offer, now) && request.status === 'searching';
            const stateText = isSelectable(offer, now) ? null : (offerStateText(offer.state) ?? o.expiredBadge);
            const known = isPriceKnown(offer.price);
            const terms = stateText
              ? stateText
              : [
                  offer.scope_description ?? o.defaultScope,
                  o.validUntilShort(timeOrDate(offer.valid_until, tz)),
                  known ? vatModeLabel(offer.price.vat_mode) : null,
                ]
                  .filter(Boolean)
                  .join(' · ');
            return (
              <div className="request-offer" key={offer.id}>
                <ChoiceCard
                  selected={active && chosen?.id === offer.id}
                  disabled={!active}
                  onSelect={() => setPicked(offer.id)}
                  media={<Avatar name={name} size={44} gradient={active ? 'o' : 'n'} aria-hidden />}
                  title={name}
                  subtitle={ratingText(offer)}
                >
                  <span className="request-offer__line">
                    <span>{offer.visit_window_start ? relativeWindow(offer.visit_window_start, offer.visit_window_end, tz) : o.visitWindowUnknown}</span>
                    <span className={`request-offer__price${known ? '' : ' request-offer__price--unknown'}`}>
                      {known ? formatPrice(offer.price) : o.priceUnknownTitle}
                    </span>
                  </span>
                  <span className={`request-offer__terms${stateText ? ' request-offer__terms--off' : ''}`}>
                    {terms}
                  </span>
                </ChoiceCard>
                <Link className="request-offer__more" to={`/requests/${id}/offers/${offer.id}`}>
                  {o.moreAbout(name)}
                </Link>
              </div>
            );
          })}
        </ChoiceGroup>
      </div>
      <Note>{o.sortNote}</Note>
      {selection.sheet}
    </Screen>
  );
}
