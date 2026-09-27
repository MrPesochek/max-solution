import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useMarketplaceCard,
  useMarketplaceMessages,
  usePostMarketplaceMessage,
  useSubmitOffer,
  useWithdrawOffer,
} from '../../api/hooks/useMarketplace';
import { useProviderProfile } from '../../api/hooks/useProviderProfile';
import { MessagesSection } from '../../components/request/MessagesSection';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { useConfirm } from '../../components/useConfirm';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import {
  EMPTY_PRICE_VALUE,
  priceValueToBody,
  isPriceValueValid,
  type PriceFormValue,
} from '../../lib/priceForm';
import { formatPrice } from '../../lib/money';
import { useCountdown } from '../../lib/datetime';
import { offerStateLabel } from '../../lib/status';
import type { Offer, OfferState, Urgency } from '../../api/types';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { UnsavedInputGuard } from '../../ui/layout/unsavedGuard';
import { useSubView } from '../../ui/layout/subView';
import { Banner, Note, PageTitle, SectionCaption, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { ChipGroup } from '../../ui/Chips';
import { PhotoGrid, PhotoTile } from '../../ui/PhotoGrid';
import { TextAreaField, TextField } from '../../ui/FormField';
import { relativeDay, shortDateTime, visitWindowShort } from '../../ui/format';
import { PriceForm } from './components/PriceForm';
import { localToIso, priceNote } from './components/priceText';
import { cardAreaName, cardTitle } from './components/cardText';
import { visitSlots } from './components/visitSlots';
import './components/workspace.css';

const OFFER_TONE: Record<OfferState, Tone> = {
  active: 'a',
  selected: 'ok',
  expired: 'w',
  withdrawn: 'w',
  closed: 'w',
};

const CUSTOM_SLOT = 'custom';

const DEFAULT_VISIT_RUB = 1500;

function urgencyEyebrow(urgency: Urgency): { text: string; danger: boolean } {
  return {
    text: strings.workspace.urgencyEyebrow[urgency] ?? strings.workspace.urgencyEyebrow.normal!,
    danger: urgency !== 'normal',
  };
}

const SUB_VIEWS = ['ask'] as const;

export function MarketplaceCardScreen() {
  const { id } = useParams<{ id: string }>();
  const query = useMarketplaceCard(id);
  const profile = useProviderProfile();
  const submitOffer = useSubmitOffer(id ?? '');
  const withdrawOffer = useWithdrawOffer(id ?? '');

  const [view, setView] = useSubView(SUB_VIEWS);
  const asking = view === 'ask';
  const questions = useMarketplaceMessages(id, asking);
  const postQuestion = usePostMarketplaceMessage(id ?? '');
  const timezone = query.data?.card.city_timezone;
  const slots = useMemo(() => visitSlots(timezone), [timezone]);
  const [slot, setSlot] = useState<string | null>(null);
  const [visitStart, setVisitStart] = useState('');
  const [visitEnd, setVisitEnd] = useState('');
  const [priceValue, setPriceValue] = useState<PriceFormValue | null>(null);
  const [termsOpen, setTermsOpen] = useState(false);
  const [scopeDescription, setScopeDescription] = useState('');
  const [comment, setComment] = useState('');
  const [accessRequirements, setAccessRequirements] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [error, setError] = useState<string | null>(null);
  const { confirm, dialog } = useConfirm();

  if (!id) return null;
  if (query.isPending) {
    return (
      <Screen title={strings.ui.requestGenericTitle}>
        <Skeleton lines={6} />
      </Screen>
    );
  }
  if (query.isError) {
    const gone = query.error instanceof ApiError && query.error.status === 404;
    return (
      <Screen title={strings.ui.requestGenericTitle}>
        {gone ? (
          <EmptyState
            title={strings.workspace.availableTitle}
            description={strings.workspace.cardNotInSearch}
          />
        ) : (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        )}
      </Screen>
    );
  }

  const w = strings.workspace;
  const { card, my_offers: myOffers } = query.data;
  const tz = card.city_timezone;
  const activeOffer = myOffers.find((o) => o.state === 'active');
  const canOffer = card.status === 'open' && !activeOffer;
  const selectedSlot = slot ?? slots[0]?.id ?? CUSTOM_SLOT;
  const quick = slots.find((s) => s.id === selectedSlot);
  const fromProfile = profile.data?.visit_price_from_minor;
  const price: PriceFormValue = priceValue ?? {
    ...EMPTY_PRICE_VALUE,
    mode: 'amount',
    amountRub: String(fromProfile ? Math.round(fromProfile / 100) : DEFAULT_VISIT_RUB),
  };

  const handleSubmit = async () => {
    setError(null);
    try {
      await submitOffer.mutateAsync({
        visit_window_start: quick ? quick.start : localToIso(visitStart),
        visit_window_end: quick ? quick.end : localToIso(visitEnd),
        ...priceValueToBody(price),
        scope_description: scopeDescription.trim() || null,
        comment: comment.trim() || null,
        access_requirements: accessRequirements.trim() || null,
        valid_until: localToIso(validUntil),
      });
    } catch (e) {
      setError(actionErrorMessage(e, w.offerSubmitError));
    }
  };

  const handleWithdraw = async (offerId: string) => {
    if (!(await confirm({ title: w.offerWithdrawConfirm, destructive: true }))) return;
    setError(null);
    try {
      await withdrawOffer.mutateAsync({ offerId, input: {} });
    } catch (e) {
      setError(actionErrorMessage(e, w.offerWithdrawError));
    }
  };

  if (asking) {
    return (
      <UnsavedInputGuard>
        <Screen
          title={w.askQuestionTitle}
          subtitle={w.askQuestionSubtitle(strings.ui.requestTitle(card.request_number))}
          back={() => setView('main')}
        >
          <Banner tone="a" title={w.askQuestionBannerTitle}>
            {w.askQuestionBannerText}
          </Banner>
          <div className="request-thread">
            <MessagesSection
              requestId={card.request_id}
              ownAuthorKind="provider_membership"
              thread={{ query: questions, send: (body) => postQuestion.mutateAsync({ body }) }}
              placeholder={w.questionPlaceholder}
              sendLabel={w.questionSend}
              canPost={card.status === 'open'}
              timezone={tz}
              onSendError={() => void query.refetch()}
              embedded
            />
          </div>
          {card.status !== 'open' && <Note>{strings.errorCodes.OFFER_DIALOG_CLOSED}</Note>}
        </Screen>
      </UnsavedInputGuard>
    );
  }

  const area = cardAreaName(card);
  const eyebrow = urgencyEyebrow(card.urgency);
  const valid = isPriceValueValid(price) && (Boolean(quick) || Boolean(visitStart));

  let actions;
  if (canOffer) {
    actions = (
      <BottomActions layout="row">
        <ActionButton kind="s" onClick={() => setView('ask')}>
          {w.incomingAskQuestion}
        </ActionButton>
        <ActionButton
          loading={submitOffer.isPending}
          disabled={!valid}
          onClick={() => void handleSubmit()}
        >
          {w.offerRespond}
        </ActionButton>
      </BottomActions>
    );
  } else if (activeOffer) {
    actions = (
      <BottomActions>
        <div className="pw-sent" role="status">
          <span>{w.offerSentLine(formatPrice(activeOffer.price))}</span>
          <button
            type="button"
            className="pw-link"
            disabled={withdrawOffer.isPending}
            onClick={() => void handleWithdraw(activeOffer.id)}
          >
            {w.offerWithdraw}
          </button>
        </div>
      </BottomActions>
    );
  }

  return (
    <Screen title={strings.ui.requestTitle(card.request_number)} actions={actions}>
      <PageTitle
        eyebrow={eyebrow.text}
        eyebrowTone={eyebrow.danger ? 'danger' : undefined}
        subtitle={w.rowSubtitle(card.model, area)}
      >
        {cardTitle(card)}
      </PageTitle>

      {card.published_description && <p className="pw-text">{card.published_description}</p>}
      {card.published_attachment_ids.length > 0 && (
        <PhotoGrid label={w.cardPhotosLabel} columns={4}>
          {card.published_attachment_ids.map((attachmentId, index) => (
            <PhotoTile
              key={attachmentId}
              attachmentId={attachmentId}
              alt={strings.attachments.photoAlt(index + 1)}
            />
          ))}
        </PhotoGrid>
      )}
      <Note>
        {w.rowSubtitle(
          w.cardPublishedLine(relativeDay(card.published_at, tz)),
          card.search_expires_at
            ? w.cardSearchUntil(shortDateTime(card.search_expires_at, tz))
            : null,
        )}
      </Note>
      <hr className="pw-rule" />

      {canOffer && (
        <>
          <SectionCaption>{w.offerWhenTitle}</SectionCaption>
          <ChipGroup
            label={w.offerWhenTitle}
            options={[
              ...slots.map((s) => ({ value: s.id, label: s.label })),
              { value: CUSTOM_SLOT, label: w.slotCustom },
            ]}
            value={selectedSlot}
            onChange={setSlot}
          />
          {selectedSlot === CUSTOM_SLOT ? (
            <>
              <TextField
                id="offer-start"
                type="datetime-local"
                label={w.offerWindowStartLabel}
                value={visitStart}
                onChange={setVisitStart}
              />
              <TextField
                id="offer-end"
                type="datetime-local"
                label={w.offerWindowEndLabel}
                hint={w.offerTimezoneHintWith(tz)}
                value={visitEnd}
                onChange={setVisitEnd}
              />
            </>
          ) : (
            <Note>{w.slotWindowNote(tz)}</Note>
          )}

          <SectionCaption>{w.offerVisitPriceTitle}</SectionCaption>
          <PriceForm
            idPrefix="offer-price"
            amountLabel={w.offerPriceLabel}
            value={price}
            onChange={setPriceValue}
            stepper
          />
          <Note>{w.offerRepairLater}</Note>

          <List>
            <ListRow
              title={w.offerTermsRow}
              subtitle={w.offerTermsHint}
              chevron
              expanded={termsOpen}
              onClick={() => setTermsOpen((v) => !v)}
            />
          </List>
          {termsOpen && (
            <>
              <TextAreaField
                id="offer-scope"
                label={w.offerScopeLabel}
                placeholder={w.offerScopePlaceholder}
                value={scopeDescription}
                onChange={setScopeDescription}
                rows={2}
              />
              <TextField
                id="offer-valid-until"
                type="datetime-local"
                label={w.offerValidUntilScreenLabel}
                value={validUntil}
                onChange={setValidUntil}
              />
              <TextAreaField
                id="offer-access"
                label={w.offerAccessRequirementsLabel}
                value={accessRequirements}
                onChange={setAccessRequirements}
                rows={2}
              />
              <TextAreaField
                id="offer-comment"
                label={w.offerCommentLabel}
                value={comment}
                onChange={setComment}
                rows={2}
              />
            </>
          )}
          <Note>{w.availableContactsNote}</Note>
        </>
      )}

      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      {myOffers.length > 0 && (
        <>
          <SectionCaption>{w.cardMyOffersTitle}</SectionCaption>
          {myOffers.map((offer) => (
            <MyOffer key={offer.id} offer={offer} timeZone={tz} />
          ))}
        </>
      )}
      {!canOffer && card.status === 'open' && (
        <List>
          <ListRow title={w.askQuestionRow} chevron onClick={() => setView('ask')} />
        </List>
      )}
      {card.status !== 'open' && myOffers.length === 0 && <Note>{w.cardNotInSearch}</Note>}
      {dialog}
    </Screen>
  );
}

function MyOffer({ offer, timeZone }: { offer: Offer; timeZone: string | null | undefined }) {
  const countdown = useCountdown(offer.valid_until);
  const active = offer.state === 'active';
  const visitWindow = offer.visit_window_start
    ? visitWindowShort(offer.visit_window_start, offer.visit_window_end, timeZone)
    : null;
  const expiry = active
    ? countdown.expired
      ? strings.offers.expiredBadge
      : `${strings.offers.expiresIn}: ${countdown.label}`
    : null;

  return (
    <List>
      <ListRow
        title={formatPrice(offer.price)}
        subtitle={strings.workspace.rowSubtitle(priceNote(offer.price), visitWindow, expiry)}
        tag={{ label: offerStateLabel(offer.state), tone: OFFER_TONE[offer.state] }}
      />
    </List>
  );
}
