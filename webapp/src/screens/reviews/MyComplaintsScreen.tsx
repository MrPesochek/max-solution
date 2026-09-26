import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useMyComplaints, useWithdrawComplaint } from '../../api/hooks/useComplaints';
import type { Complaint, ComplaintStatus } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { useConfirm } from '../../components/useConfirm';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { Screen } from '../../ui/layout/Screen';
import { List, ListRow } from '../../ui/List';
import { StatusHero } from '../../ui/StatusHero';
import { Note, SectionCaption, type Tone } from '../../ui/blocks/Blocks';
import { shortDateTime } from '../../ui/format';

const STATUS_TONE: Record<ComplaintStatus, Tone> = {
  pending: 'a',
  published: 'ok',
  removed: 'ok',
  rejected: 'x',
  withdrawn: 'w',
};

function subtitleOf(c: Complaint): string {
  const parts = [shortDateTime(c.created_at)];
  if (c.reason_code) parts.push(strings.complaints.reasonCode[c.reason_code]);
  if (c.decision_reason)
    parts.push(`${strings.complaints.decisionReasonLabel}: ${c.decision_reason}`);
  if (c.appeal_status)
    parts.push(strings.complaints.appealLine(strings.complaints.status[c.appeal_status]));
  return parts.join(' · ');
}

export function MyComplaintsScreen() {
  const complaints = useMyComplaints();
  const withdraw = useWithdrawComplaint();
  const { confirm, dialog } = useConfirm();
  const [withdrawing, setWithdrawing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runWithdraw = async (complaint: Complaint) => {
    if (
      !(await confirm({
        title: strings.complaints.withdrawConfirm,
        confirmLabel: strings.complaints.withdrawConfirmLabel,
        destructive: true,
      }))
    )
      return;
    setError(null);
    setWithdrawing(complaint.id);
    try {
      await withdraw.mutateAsync(complaint.id);
    } catch (e) {
      setError(actionErrorMessage(e, strings.complaints.withdrawError));
      void complaints.refetch();
    } finally {
      setWithdrawing(null);
    }
  };

  let body;
  if (complaints.isPending) {
    body = <Skeleton lines={4} />;
  } else if (complaints.isError) {
    body = <ErrorState error={complaints.error} onRetry={() => void complaints.refetch()} />;
  } else {
    const items = complaints.data.pages.flatMap((page) => page.items);
    body =
      items.length === 0 ? (
        <StatusHero
          illustration="review"
          illustrationWidth={188}
          top={24}
          title={strings.complaints.empty}
        >
          {strings.complaints.emptyText}
        </StatusHero>
      ) : (
        <>
          <SectionCaption>{strings.complaints.listCaption}</SectionCaption>
          <List>
            {items.map((c) => {
              const status = c.status;
              return (
                <ListRow
                  key={c.id}
                  title={strings.complaints.subjectLabel[c.subject_type]}
                  subtitle={subtitleOf(c)}
                  tag={{ label: strings.complaints.status[status], tone: STATUS_TONE[status] }}
                />
              );
            })}
            {complaints.hasNextPage && (
              <ListRow
                title={strings.complaints.loadMore}
                action="accent"
                loading={complaints.isFetchingNextPage}
                onClick={() => void complaints.fetchNextPage()}
              />
            )}
          </List>
          {items.some((c) => c.status === 'pending') && (
            <List aria-label={strings.complaints.withdraw}>
              {items
                .filter((c) => c.status === 'pending')
                .map((c) => (
                  <ListRow
                    key={c.id}
                    title={strings.complaints.withdraw}
                    subtitle={`${strings.complaints.subjectLabel[c.subject_type]} · ${shortDateTime(c.created_at)}`}
                    action="danger"
                    loading={withdrawing === c.id}
                    disabled={withdrawing !== null}
                    onClick={() => void runWithdraw(c)}
                  />
                ))}
            </List>
          )}
          {error && (
            <Note tone="error" role="alert">
              {error}
            </Note>
          )}
        </>
      );
  }

  return (
    <Screen title={strings.complaints.myTitle}>
      {body}
      {dialog}
    </Screen>
  );
}
