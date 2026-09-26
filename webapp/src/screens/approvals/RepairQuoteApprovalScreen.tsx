import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useApproveRepairQuote, useRefreshRequest, useRejectRepairQuote } from '../../api/hooks/useRequests';
import { ApiError } from '../../api/errors';
import type { RepairQuote } from '../../api/types';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { formatTime, useCountdown } from '../../lib/datetime';
import { formatAmountMinor, formatPrice, isPriceKnown, vatModeLabel } from '../../lib/money';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note, PageTitle, PriceBlock, TextCard } from '../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { SceneBanner } from '../../ui/SceneBanner';
import { ChipGroup } from '../../ui/Chips';
import { TextAreaField } from '../../ui/FormField';
import { Sheet } from '../../ui/Sheet';
import { StatusHero } from '../../ui/StatusHero';
import { EmptyState } from '../../components/states/EmptyState';
import { requestFallback, useCustomerRequest } from '../requests/card/customerRequest';
import { approvedVisit, dayMonth } from '../requests/card/cardFormat';
import '../../components/request/request.css';

const STALE_CODES = new Set(['QUOTE_NOT_CURRENT', 'QUOTE_EXPIRED', 'QUOTE_NOT_PENDING', 'VERSION_CONFLICT']);

function itemRows(quote: RepairQuote, previous: RepairQuote | undefined): KeyValueRow[] {
  const currency = quote.price.currency ?? 'RUB';
  return quote.items.map((item, index) => {
    const before = previous?.items.find((p) => p.title === item.title);
    const changed = previous !== undefined && (!before || before.amount_minor !== item.amount_minor);
    return {
      id: `${item.title}-${index}`,
      label: item.title,
      value: formatAmountMinor(item.amount_minor, currency),
      oldValue: changed && before ? formatAmountMinor(before.amount_minor, currency) : undefined,
      tone: changed ? 'accent' : undefined,
    };
  });
}

function validUntil(iso: string, timezone?: string | null): string {
  return `${dayMonth(iso, timezone)}, ${formatTime(iso, timezone)}`;
}

export function RepairQuoteApprovalScreen() {
  const { id, quoteId } = useParams<{ id: string; quoteId: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const approve = useApproveRepairQuote(id ?? '');
  const reject = useRejectRepairQuote(id ?? '');
  const refresh = useRefreshRequest(id);
  const runner = useActionRunner({
    onStale: refresh,
    staleCodes: STALE_CODES,
    fallbackMessage: strings.approvals.approveError,
  });
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [seenVersion, setSeenVersion] = useState<number | null>(null);
  const [diffShown, setDiffShown] = useState<number | null>(null);

  const quotes = request?.repair_quotes ?? [];
  const anchor = quotes.find((q) => q.id === quoteId);
  const quote: RepairQuote | undefined = anchor
    ? quotes.filter((q) => q.assignment_id === anchor.assignment_id).sort((a, b) => b.version - a.version)[0]
    : undefined;
  const countdown = useCountdown(quote?.valid_until);
  const a = strings.approvals;

  const title = request ? strings.ui.requestTitle(request.request_number) : a.quoteTitle;
  const back = id ? `/requests/${id}` : undefined;
  if (!activeMembership || !id || !quoteId) return null;
  const fallback = requestFallback({
    query,
    request,
    title,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;
  if (!quote || !anchor) {
    return (
      <Screen title={title} back={back}>
        <EmptyState title={a.quoteTitle} description={a.quoteNotFound} />
      </Screen>
    );
  }

  const stale = runner.feedback?.kind === 'stale';
  const tz = request.location.timezone;

  if (anchor.id !== quote.id && !stale && !showCurrent) {
    return (
      <Screen
        title={title}
        back={back}
        actions={
          <BottomActions>
            <ActionButton onClick={() => setShowCurrent(true)}>{a.showNewTerms}</ActionButton>
          </BottomActions>
        }
      >
        <StatusHero illustration="status-price" top={40} title={a.staleLinkTitle}>
          {a.staleLinkText(anchor.version, quote.version)}
        </StatusHero>
      </Screen>
    );
  }

  const pending = quote.status === 'pending' && !countdown.expired;
  const known = isPriceKnown(quote.price);
  const warranty = known && quote.price.amount_minor === 0;
  const price = formatPrice(quote.price);
  const previous =
    stale && seenVersion !== null && seenVersion < quote.version
      ? quotes.find((q) => q.assignment_id === quote.assignment_id && q.version === seenVersion)
      : undefined;
  const previousPrice = previous ? formatPrice(previous.price) : null;
  const visit = approvedVisit(request);
  const provider = request.assignment?.provider_display_name ?? strings.offers.providerFallback;
  const decided = quote.status === 'approved' || quote.status === 'rejected';
  const vat = known ? vatModeLabel(quote.price.vat_mode) : null;
  const terms = quote.warranty_terms?.trim() || null;

  const decide = async (approveDecision: boolean) => {
    setSeenVersion(quote.version);
    const mutation = approveDecision ? approve : reject;
    const text = approveDecision ? comment.trim() : [reason, comment.trim()].filter(Boolean).join('. ');
    let conflict = false;
    const done = await runner.run(
      approveDecision ? 'approve' : 'reject',
      async () => {
        await mutation.mutateAsync({
          quote_id: quote.id,
          quote_version: quote.version,
          comment: text || null,
          expected_version: request.version,
        });
        return true;
      },
      {
        mapError: (e) => {
          if (!(e instanceof ApiError)) return null;
          conflict = e.status === 409 || STALE_CODES.has(e.code);
          return e.code === 'PRICE_UNKNOWN' ? a.priceUnknownNotice : null;
        },
      },
    );
    if (done) navigate(`/requests/${id}`, { replace: true });
    // Условия изменились — назад к актуальной версии, причина отклонения остаётся в форме.
    else if (conflict) setRejecting(false);
  };

  if (rejecting) {
    return (
      <Screen
        title={title}
        back={() => setRejecting(false)}
        actions={
          <BottomActions layout="row">
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setRejecting(false)}>
              {strings.ui.back}
            </ActionButton>
            <ActionButton loading={runner.isRunning('reject')} disabled={runner.busy} onClick={() => void decide(false)}>
              {a.rejectQuoteConfirm}
            </ActionButton>
          </BottomActions>
        }
      >
        <SceneBanner name="status-dispute" height={130} />
        <PageTitle subtitle={a.rejectSubtitle}>{a.rejectHeading}</PageTitle>
        <div className="request-chip-block">
          <ChipGroup
            multiple
            label={a.rejectReasonsLabel}
            options={a.rejectReasons.map((option) => ({ value: option, label: option }))}
            value={reason ? [reason] : []}
            onChange={(next) => setReason(next.filter((value) => value !== reason)[0] ?? null)}
          />
        </div>
        <TextAreaField label={a.rejectCommentLabel} value={comment} onChange={setComment} rows={3} />
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      </Screen>
    );
  }

  const scene = quote.status === 'approved' ? 'status-done' : quote.status === 'rejected' ? 'status-cancel' : 'status-price';
  const heading = quote.status === 'approved' ? a.quoteApprovedTitle : quote.status === 'rejected' ? a.quoteRejectedTitle : a.quoteHeading;
  const subtitle = a.quoteSubtitle(provider, quote.version);
  const termsLine = [
    terms ? a.warrantyTerms(terms) : null,
    pending || quote.status === 'pending' ? a.validUntilSentence(validUntil(quote.valid_until, tz)) : null,
    vat,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <Screen
      title={title}
      back={back}
      actions={
        pending ? (
          <BottomActions layout="row" note={a.notPaymentNote}>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setRejecting(true)}>
              {a.rejectQuoteButton}
            </ActionButton>
            <ActionButton
              loading={runner.isRunning('approve')}
              disabled={runner.busy}
              aria-label={warranty || !known ? undefined : a.approveWithPrice(price)}
              onClick={() => void decide(true)}
            >
              {/* В два столбца цена не помещается: она — в итоге выше и в подписи для диктора. */}
              {warranty || !known ? a.approveRepair : a.approveButton}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      <SceneBanner name={scene} height={130} />
      <PageTitle subtitle={subtitle}>{heading}</PageTitle>
      {stale && !previous && (
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      )}
      {decided && (
        <Note>{quote.status === 'approved' ? a.quoteApprovedText : a.quoteRejectedText}</Note>
      )}

      {warranty ? (
        <>
          <PriceBlock value={price} caption={a.warrantyCaption} />
          <KeyValueRows
            rows={[
              ...(quote.price.zero_cost_reason ? [{ label: a.basisLabel, value: quote.price.zero_cost_reason }] : []),
              {
                label: a.worksLabel,
                value: quote.items.length > 0 ? quote.items.map((item) => item.title).join(', ') : quote.description_of_work,
              },
              { label: a.deadlineLabel, value: a.untilDate(dayMonth(quote.valid_until, tz)) },
            ]}
          />
          <Note>{a.warrantyNote}</Note>
        </>
      ) : (
        <>
          {(quote.items.length === 0 || quote.description_of_work !== quote.items.map((item) => item.title).join(', ')) && (
            <TextCard>{quote.description_of_work}</TextCard>
          )}
          <KeyValueRows
            variant="items"
            aria-label={a.quoteItemsLabel}
            rows={itemRows(quote, previous)}
            total={{
              label: a.totalLabel,
              value: (
                <>
                  {previousPrice && previousPrice !== price && <s className="ui-kv__old">{previousPrice}</s>}{' '}
                  {known ? price : strings.offers.priceUnknownTitle}
                </>
              ),
            }}
          />
          {termsLine && <Note>{termsLine}</Note>}
          {visit && <Note>{a.quoteVisitApprovedNote(formatPrice(visit.price))}</Note>}
        </>
      )}

      {decided && !stale && <Note>{a.decisionFinalNote}</Note>}
      {quote.status === 'pending' && countdown.expired && (
        <Banner tone="w" title={a.expiredTitle}>
          {a.expiredNotice}
        </Banner>
      )}
      {runner.feedback && runner.feedback.kind !== 'stale' && (
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      )}

      <Sheet
        open={Boolean(previous) && diffShown !== quote.version}
        role="alertdialog"
        title={a.priceChangedTitle}
        description={a.priceChangedText(provider)}
        onClose={() => setDiffShown(quote.version)}
        actions={<ActionButton onClick={() => setDiffShown(quote.version)}>{a.showNewVersion}</ActionButton>}
      >
        {previousPrice && (
          <div className="request-sheet-compare">
            <span className="request-sheet-compare__was">{a.priceWas(previousPrice)}</span>
            <span className="request-sheet-compare__now">{a.priceNow(price)}</span>
          </div>
        )}
      </Sheet>
    </Screen>
  );
}
