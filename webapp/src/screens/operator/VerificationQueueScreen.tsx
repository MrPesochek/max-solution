import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useDecideVerificationCase,
  useVerificationQueue,
} from '../../api/hooks/useOperatorVerification';
import type { VerificationCaseOperator } from '../../api/operatorTypes';
import { useConfirm } from '../../components/useConfirm';
import { Banner, Note, SectionCaption, TextCard } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Segmented } from '../../ui/Segmented';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { initials } from '../../ui/format';
import { OperatorScreen } from './OperatorScreen';

const SUBJECT_LABEL = strings.operator.verificationSubjectLabel;

type SubmittableDecision = 'approved' | 'needs_information' | 'rejected';

const DECISIONS: { id: SubmittableDecision; label: string }[] = [
  { id: 'approved', label: strings.operator.decisionApprove },
  { id: 'needs_information', label: strings.operator.decisionNeedsInfo },
  { id: 'rejected', label: strings.operator.decisionReject },
];

function caseSubtitle(item: VerificationCaseOperator): string {
  const kind = SUBJECT_LABEL[item.check_kind] ?? item.check_kind;
  return item.organization_inn
    ? `${kind} · ${strings.operator.innShort(item.organization_inn)}`
    : kind;
}

function CaseSheet({ item, onClose, demo = false }: { item: VerificationCaseOperator; onClose: () => void; demo?: boolean }) {
  const [decision, setDecision] = useState<SubmittableDecision>('approved');
  const [reason, setReason] = useState('');
  const [source, setSource] = useState('');
  const [error, setError] = useState<string | null>(null);
  const decide = useDecideVerificationCase(item.id, demo);
  const { confirm, dialog } = useConfirm();

  const valid = reason.trim().length > 0 && (decision !== 'approved' || source.trim().length > 0);

  const handleSubmit = async () => {
    if (!valid) return;
    const ok = await confirm({
      title: strings.operator.decisionConfirm,
      confirmLabel: strings.operator.confirmYes,
    });
    if (!ok) return;
    setError(null);
    try {
      await decide.mutateAsync({
        decision,
        reason: reason.trim(),
        source: source.trim() || null,
        is_demo: demo,
      });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  return (
    <Sheet
      open
      title={item.organization_name}
      description={caseSubtitle(item)}
      onClose={onClose}
      locked={decide.isPending}
      actions={
        <>
          <ActionButton
            disabled={!valid}
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
      {item.evidence_note && (
        <>
          <SectionCaption>{strings.operator.caseEvidenceLabel}</SectionCaption>
          <TextCard>{item.evidence_note}</TextCard>
        </>
      )}
      <Note>{strings.operator.caseEvidenceNote}</Note>

      <SectionCaption>{strings.operator.decisionCaption}</SectionCaption>
      <Segmented
        items={DECISIONS}
        value={decision}
        onChange={setDecision}
        label={strings.operator.decisionLabel}
      />
      <Note>{strings.operator.decisionNotEvidenceHint}</Note>

      <TextAreaField
        id="decision-reason"
        label={strings.operator.decisionReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {decision === 'approved' && (
        <TextAreaField
          id="decision-source"
          label={strings.operator.decisionSourceLabel}
          value={source}
          onChange={setSource}
          rows={2}
        />
      )}
      {!valid && (reason.length > 0 || source.length > 0) && (
        <Note>{strings.operator.decisionReasonRequired}</Note>
      )}
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function VerificationQueueScreen({ demo = false }: { demo?: boolean }) {
  const queue = useVerificationQueue(demo);
  const [view, setView] = useState<'pending' | 'history'>('pending');
  const [openId, setOpenId] = useState<string | null>(null);
  const items = (queue.data ?? []).filter((item) => !demo ||
    ((item.decision === 'pending' || item.decision === 'needs_information') === (view === 'pending')));
  const decisionLabels = { pending: 'На проверке', approved: 'Подтверждено', rejected: 'Отклонено', needs_information: 'Нужно уточнение', revoked: 'Отозвано' };
  const open = items.find((item) => item.id === openId) ?? null;

  return (
    <OperatorScreen
      title={demo ? 'Демо: проверка организаций' : strings.operator.verificationQueueTitle}
      subtitle={demo ? 'Проверяйте реквизиты и представителей демонстрационных организаций. Решения видны всем участникам.' : undefined}
      actions={demo ? <BottomActions><ActionButton kind="s" to="/organizations">К выбору роли</ActionButton></BottomActions> : undefined}
      toolbar={demo ? <Segmented items={[{ id: 'pending', label: 'На проверке' }, { id: 'history', label: 'Решения' }]} value={view} onChange={setView} label="Проверки" /> : undefined}
      query={queue}
      empty={items.length === 0}
      overlay={
        <>{open && (demo && view === 'history'
          ? <Sheet open title={open.organization_name} description={caseSubtitle(open)} onClose={() => setOpenId(null)}>
              <TextCard>{decisionLabels[open.decision]}</TextCard>
              {open.decision_reason && <TextCard>{open.decision_reason}</TextCard>}
              {open.source && <Note>Источник: {open.source}</Note>}
            </Sheet>
          : <CaseSheet key={open.id} item={open} demo={demo} onClose={() => setOpenId(null)} />)}</>
      }
    >
      <List>
        {items.map((item) => (
          <ListRow
            key={item.id}
            title={item.organization_name}
            subtitle={caseSubtitle(item)}
            icon={initials(item.organization_name)}
            gradient="b"
            tag={{ label: demo ? decisionLabels[item.decision] : strings.operator.caseTag, tone: 'a' }}
            opensDialog
            chevron
            onClick={() => setOpenId(item.id)}
          />
        ))}
      </List>
    </OperatorScreen>
  );
}
