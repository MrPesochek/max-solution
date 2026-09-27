import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useDecideModerationCase,
  useOperatorModerationCases,
} from '../../api/hooks/useOperatorReputation';
import type { ModerationCaseOperator } from '../../api/operatorTypes';
import { useConfirm } from '../../components/useConfirm';
import { formatDateTime } from '../../lib/datetime';
import { Banner, SectionCaption, TextCard } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Segmented } from '../../ui/Segmented';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { OperatorScreen } from './OperatorScreen';

const STATUS = 'pending';
const SUBJECT_LABEL = strings.operator.complaintSubjectLabel;

type CaseDecision = 'published' | 'rejected' | 'removed';

const DECISIONS: { id: CaseDecision; label: string }[] = [
  { id: 'published', label: strings.operator.casesDecidePublish },
  { id: 'rejected', label: strings.operator.casesDecideReject },
  { id: 'removed', label: strings.operator.casesDecideRemove },
];

function caseSubtitle(item: ModerationCaseOperator): string {
  return `${item.filer_organization_name ?? strings.common.notSpecified} · ${formatDateTime(item.created_at)}`;
}

function CaseSheet({ item, onClose }: { item: ModerationCaseOperator; onClose: () => void }) {
  const [decision, setDecision] = useState<CaseDecision>('published');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const decide = useDecideModerationCase(item.id, 'all', STATUS);
  const { confirm, dialog } = useConfirm();

  const requiresReason = decision === 'rejected' || decision === 'removed';
  const description = item.evidence.description as string | undefined;

  const handleSubmit = async () => {
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

  return (
    <Sheet
      open
      title={SUBJECT_LABEL[item.subject_type] ?? item.subject_type}
      description={caseSubtitle(item)}
      onClose={onClose}
      locked={decide.isPending}
      actions={
        <>
          <ActionButton
            disabled={requiresReason && !reason.trim()}
            loading={decide.isPending}
            onClick={() => void handleSubmit()}
          >
            {strings.operator.decisionSubmit}
          </ActionButton>
          <ActionButton kind="s" disabled={decide.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <SectionCaption>{strings.operator.casesEvidenceTitle}</SectionCaption>
      <TextCard>{description ?? strings.common.notSpecified}</TextCard>
      {item.evidence.reason != null && <TextCard>{String(item.evidence.reason)}</TextCard>}
      {item.appeal_status && (
        <Banner tone="y" title={strings.operator.casesAppealLabel}>
          {item.appeal_status}
        </Banner>
      )}

      <SectionCaption>{strings.operator.decisionCaption}</SectionCaption>
      <Segmented
        items={DECISIONS}
        value={decision}
        onChange={setDecision}
        label={strings.operator.decisionLabel}
      />
      <TextAreaField
        id={`case-reason-${item.id}`}
        label={strings.operator.casesReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function ComplaintsQueueScreen() {
  const queue = useOperatorModerationCases('all', STATUS);
  const [openId, setOpenId] = useState<string | null>(null);
  const items = queue.data ?? [];
  const open = items.find((item) => item.id === openId) ?? null;

  return (
    <OperatorScreen
      title={strings.operator.casesQueueTitle}
      query={queue}
      empty={items.length === 0}
      emptyTitle={strings.operator.casesEmpty}
      overlay={open && <CaseSheet key={open.id} item={open} onClose={() => setOpenId(null)} />}
    >
      <List>
        {items.map((item) => (
          <ListRow
            key={item.id}
            title={SUBJECT_LABEL[item.subject_type] ?? item.subject_type}
            subtitle={caseSubtitle(item)}
            tag={item.appeal_status ? { label: strings.operator.appealTag, tone: 'y' } : undefined}
            opensDialog
            chevron
            onClick={() => setOpenId(item.id)}
          />
        ))}
      </List>
    </OperatorScreen>
  );
}
