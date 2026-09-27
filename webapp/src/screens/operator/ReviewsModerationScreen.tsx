import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useDecideReview,
  useOperatorReviewQueue,
  useSetReviewFraudFlag,
} from '../../api/hooks/useOperatorReputation';
import type { ReviewOperator, ReviewOperatorDecision } from '../../api/operatorTypes';
import { useConfirm } from '../../components/useConfirm';
import { Banner, Note, SectionCaption, TextCard } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Segmented } from '../../ui/Segmented';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { initials } from '../../ui/format';
import { OperatorScreen } from './OperatorScreen';
import './operator.css';

const STATUS = 'pending';

const DECISIONS: { id: ReviewOperatorDecision; label: string }[] = [
  { id: 'published', label: strings.operator.reviewsPublish },
  { id: 'rejected', label: strings.operator.reviewsReject },
  { id: 'removed', label: strings.operator.reviewsRemove },
];

function FraudSignals({ signals }: { signals: Record<string, unknown> }) {
  const entries = Object.entries(signals ?? {});
  return (
    <section aria-label={strings.operator.reviewsFraudSignalsTitle}>
      <SectionCaption>{strings.operator.reviewsFraudSignalsTitle}</SectionCaption>
      {entries.length === 0 ? (
        <Note>{strings.operator.reviewsFraudSignalsNone}</Note>
      ) : (
        <>
          <List>
            {entries.map(([key, value]) => (
              <ListRow key={key} title={key} value={String(value)} valueTone="secondary" />
            ))}
          </List>
          <Note>{strings.operator.reviewsFraudSignalsHint}</Note>
        </>
      )}
    </section>
  );
}

function ReviewSheet({ item, onClose }: { item: ReviewOperator; onClose: () => void }) {
  const [decision, setDecision] = useState<ReviewOperatorDecision>('published');
  const [reason, setReason] = useState('');
  const [fraudReason, setFraudReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const decide = useDecideReview(item.id, STATUS);
  const setFraud = useSetReviewFraudFlag(item.id, STATUS);
  const { confirm, dialog } = useConfirm();

  const requiresReason = decision === 'rejected' || decision === 'removed';
  const busy = decide.isPending || setFraud.isPending;

  const handleDecide = async () => {
    if (requiresReason && !reason.trim()) return;
    const ok = await confirm({
      title: strings.operator.decisionConfirm,
      confirmLabel: strings.operator.confirmYes,
    });
    if (!ok) return;
    setError(null);
    try {
      await decide.mutateAsync({ decision, reason: reason.trim() || null });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  const handleFraud = async (suspected: boolean) => {
    if (!fraudReason.trim()) return;
    setError(null);
    try {
      await setFraud.mutateAsync({ suspected, reason: fraudReason.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  return (
    <Sheet
      open
      title={item.provider_organization_name}
      description={`${item.customer_organization_name} · ${strings.operator.rating(item.rating)}`}
      onClose={onClose}
      locked={busy}
      actions={
        <>
          <ActionButton
            disabled={requiresReason && !reason.trim()}
            loading={decide.isPending}
            onClick={() => void handleDecide()}
          >
            {strings.operator.decisionSubmit}
          </ActionButton>
          <ActionButton kind="s" disabled={busy} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextCard>{item.text ?? strings.common.notSpecified}</TextCard>
      {item.suspected_fraud && <Banner tone="y" title={strings.operator.fraudTag} />}
      <FraudSignals signals={item.fraud_signals} />

      <SectionCaption>{strings.operator.decisionCaption}</SectionCaption>
      <Segmented
        items={DECISIONS}
        value={decision}
        onChange={setDecision}
        label={strings.operator.decisionLabel}
      />
      <TextAreaField
        id={`review-decision-reason-${item.id}`}
        label={strings.operator.reviewsDecisionReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />

      <SectionCaption>{strings.operator.fraudCaption}</SectionCaption>
      <Note>{strings.operator.reviewsFraudNotice}</Note>
      <TextAreaField
        id={`review-fraud-reason-${item.id}`}
        label={strings.operator.reviewsFraudReasonLabel}
        value={fraudReason}
        onChange={setFraudReason}
        rows={2}
      />
      <div className="operator-sheet-row">
        <ActionButton
          kind="s"
          compact
          disabled={!fraudReason.trim() || busy || item.suspected_fraud}
          onClick={() => void handleFraud(true)}
        >
          {strings.operator.reviewsMarkFraud}
        </ActionButton>
        <ActionButton
          kind="s"
          compact
          disabled={!fraudReason.trim() || busy || !item.suspected_fraud}
          onClick={() => void handleFraud(false)}
        >
          {strings.operator.reviewsUnmarkFraud}
        </ActionButton>
      </div>
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function ReviewsModerationScreen() {
  const queue = useOperatorReviewQueue(STATUS);
  const [openId, setOpenId] = useState<string | null>(null);
  const items = queue.data ?? [];
  const open = items.find((item) => item.id === openId) ?? null;

  return (
    <OperatorScreen
      title={strings.operator.reviewsQueueTitle}
      query={queue}
      empty={items.length === 0}
      emptyTitle={strings.operator.reviewsEmpty}
      overlay={open && <ReviewSheet key={open.id} item={open} onClose={() => setOpenId(null)} />}
    >
      <List>
        {items.map((item) => (
          <ListRow
            key={item.id}
            title={item.provider_organization_name}
            subtitle={`${item.customer_organization_name} · ${strings.operator.rating(item.rating)}`}
            icon={initials(item.provider_organization_name)}
            gradient="a"
            tag={item.suspected_fraud ? { label: strings.operator.fraudTag, tone: 'y' } : undefined}
            opensDialog
            chevron
            onClick={() => setOpenId(item.id)}
          />
        ))}
      </List>
    </OperatorScreen>
  );
}
