import { useState } from 'react';
import { strings } from '../../../strings/ru';
import type { RequestCustomer } from '../../../api/types';
import { formatPrice, isPriceKnown, vatModeLabel } from '../../../lib/money';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { Banner, Note, PageTitle } from '../../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../../ui/KeyValueRows';
import { SceneBanner } from '../../../ui/SceneBanner';
import { BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Sheet } from '../../../ui/Sheet';
import { TextAreaField } from '../../../ui/FormField';
import { shortDateTime } from '../../../ui/format';
import { CardPerson } from '../../requests/card/CardPerson';
import { relativeWindow } from '../../requests/card/cardFormat';
import type { VisitDecision } from './useVisitDecision';

export function VisitProposalBlocks({
  request,
  decision,
  isManager,
}: {
  request: RequestCustomer;
  decision: VisitDecision;
  isManager: boolean;
}) {
  const { proposal, previous, stale, countdown, runner } = decision;
  if (!proposal) return null;
  const a = strings.approvals;
  const tz = request.location.timezone;
  const visitWindow = relativeWindow(proposal.visit_window_start, proposal.visit_window_end, tz, true);
  const previousWindow = previous
    ? relativeWindow(previous.visit_window_start, previous.visit_window_end, tz, true)
    : null;
  const previousPrice = previous ? formatPrice(previous.price) : null;
  const known = isPriceKnown(proposal.price);
  const price = known ? formatPrice(proposal.price) : strings.offers.priceUnknownTitle;
  const assignment = request.assignment;
  const master = assignment?.field_worker?.display_name;
  const provider = assignment?.provider_display_name ?? strings.offers.providerFallback;
  const vat = known ? vatModeLabel(proposal.price.vat_mode) : null;

  const rows: KeyValueRow[] = [
    {
      label: a.whenLabel,
      value: visitWindow,
      oldValue: previousWindow && previousWindow !== visitWindow ? previousWindow : undefined,
      tone: previousWindow && previousWindow !== visitWindow ? 'accent' : undefined,
    },
  ];
  if (proposal.scope_description) rows.push({ label: a.scopeLabel, value: proposal.scope_description });
  if (isManager && master) rows.push({ label: a.masterLabel, value: master });
  if (isManager && proposal.comment) rows.push({ label: a.reasonLabel, value: proposal.comment });
  if (isManager && proposal.access_requirements) {
    rows.push({ label: a.accessRequirementsLabel, value: proposal.access_requirements });
  }
  if (proposal.price.amount_minor === 0 && proposal.price.zero_cost_reason) {
    rows.push({ label: a.basisLabel, value: proposal.price.zero_cost_reason });
  }
  if (vat) rows.push({ label: a.vatLabel, value: vat });
  if (isManager) rows.push({ label: a.replyUntilLabel, value: shortDateTime(proposal.valid_until, tz) });

  return (
    <>
      <SceneBanner name="status-price" height={130} />
      <PageTitle subtitle={isManager ? a.visitOfferCaption(proposal.version) : a.visitOfferCaptionShort}>
        {isManager ? a.visitHeading : a.visitHeadingEmployee}
      </PageTitle>
      <CardPerson
        name={master ?? provider}
        company={master ? provider : null}
        phone={assignment?.provider_contact_phone}
      />
      {previous && (
        <Banner tone="y" role="alert" title={a.replacedTitle(proposal.version, previous.version)}>
          {a.replacedText}
        </Banner>
      )}
      {stale && !previous && (
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      )}

      <KeyValueRows
        rows={rows}
        total={{
          label: a.totalLabel,
          value: (
            <>
              {previousPrice && previousPrice !== formatPrice(proposal.price) && (
                <s className="ui-kv__old">{previousPrice}</s>
              )}{' '}
              {price}
            </>
          ),
        }}
      />

      {proposal.status !== 'pending' && !stale && <Note>{a.respondedNotice}</Note>}
      {proposal.status === 'pending' && countdown.expired && (
        <Banner tone="w" title={a.expiredTitle}>
          {a.expiredNotice}
        </Banner>
      )}
      {!isManager && proposal.status === 'pending' && (
        <Banner tone="w" title={a.managerDecidesTitle}>
          {a.managerDecidesText}
        </Banner>
      )}
      {isManager && decision.pending && !previous && <Note>{a.repairLaterNote}</Note>}
      {runner.feedback && runner.feedback.kind !== 'stale' && (
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      )}
    </>
  );
}

export function VisitDecisionActions({
  decision,
  onDone,
}: {
  decision: VisitDecision;
  onDone?: () => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState('');
  const { proposal, runner } = decision;
  if (!proposal || !decision.pending) return null;

  const price = isPriceKnown(proposal.price) ? formatPrice(proposal.price) : null;

  return (
    <>
      <BottomActions layout="row" note={strings.approvals.notPaymentNote}>
        <ActionButton kind="s" disabled={runner.busy} onClick={() => setRejecting(true)}>
          {strings.approvals.rejectButton}
        </ActionButton>
        <ActionButton
          loading={runner.isRunning('approve')}
          disabled={runner.busy}
          aria-label={price ? strings.approvals.approveWithPrice(price) : undefined}
          onClick={async () => {
            if (await decision.approve()) onDone?.();
          }}
        >
          {strings.approvals.approveButton}
        </ActionButton>
      </BottomActions>
      <Sheet
        open={rejecting}
        title={strings.approvals.rejectSheetTitle}
        description={strings.approvals.rejectSheetText}
        onClose={() => setRejecting(false)}
        locked={runner.busy}
        actions={
          <>
            <ActionButton
              kind="d"
              loading={runner.isRunning('reject')}
              disabled={runner.busy}
              onClick={async () => {
                const done = await decision.reject(comment);
                setRejecting(false);
                if (done) {
                  setComment('');
                  onDone?.();
                }
              }}
            >
              {strings.approvals.rejectConfirm}
            </ActionButton>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setRejecting(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        <TextAreaField
          label={strings.approvals.rejectReasonLabel}
          value={comment}
          onChange={setComment}
          rows={3}
        />
      </Sheet>
    </>
  );
}
