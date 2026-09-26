import { strings } from '../../../strings/ru';
import { useForceCancellation, useWithdrawCancellation } from '../../../api/hooks/useRequests';
import type { RequestCustomer } from '../../../api/types';
import type { ActionRunner } from '../../../components/actions/useActionRunner';
import { Note } from '../../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../../ui/KeyValueRows';
import { List, ListRow } from '../../../ui/List';
import { shortDateTime } from '../../../ui/format';
import { atTime, forceDeadlinePassed } from './cardFormat';

type Confirm = (options: {
  title: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
}) => Promise<boolean>;

export function CancellationNotice({
  request,
  isManager,
  runner,
  confirm,
  withdrawRow = false,
}: {
  request: RequestCustomer;
  isManager: boolean;
  runner: ActionRunner;
  confirm: Confirm;
  withdrawRow?: boolean;
}) {
  const withdraw = useWithdrawCancellation(request.id);
  const force = useForceCancellation(request.id);
  const cancellation = request.cancellation;
  if (!cancellation || !['pending', 'disputed'].includes(cancellation.status)) return null;
  const c = strings.requests.card;
  const tz = request.location.timezone;
  const disputed = cancellation.status === 'disputed';
  const deadline = cancellation.dispute_deadline_at;
  const deadlinePassed = forceDeadlinePassed(cancellation);
  const showWithdraw = withdrawRow || disputed;
  const showForce = disputed || deadlinePassed;

  const handleWithdraw = async () => {
    const ok = await confirm({ title: c.withdrawRequestConfirm, description: c.withdrawRequestConfirmText });
    if (!ok) return;
    void runner.run('withdrawCancellation', () =>
      withdraw.mutateAsync({ cancellation_id: cancellation.id, expected_version: request.version }),
    );
  };

  const handleForce = async () => {
    const ok = await confirm({
      title: c.cancelForceClose,
      description: disputed ? c.cancelDisputedDescription : c.cancelSilentDescription,
      confirmLabel: c.cancelForceClose,
      destructive: true,
    });
    if (!ok) return;
    void runner.run('forceCancellation', () =>
      force.mutateAsync({ cancellation_id: cancellation.id, expected_version: request.version }),
    );
  };

  const rows: KeyValueRow[] = [
    { label: c.cancellationTargetRow, value: c.cancellationTarget[cancellation.target] ?? cancellation.target },
  ];
  if (cancellation.reason) rows.push({ label: c.cancellationReasonRow, value: cancellation.reason });
  rows.push({ label: c.cancellationRequestedRow, value: atTime(cancellation.created_at, tz) });
  if (cancellation.provider_response) {
    rows.push({ label: c.cancelProviderResponse, value: cancellation.provider_response, tone: disputed ? 'error' : undefined });
  }

  return (
    <section aria-label={disputed ? c.cancelDisputedTitle : c.cancellationPendingTitle}>
      <KeyValueRows rows={rows} />
      {isManager && (showWithdraw || showForce) && (
        <List>
          {showWithdraw && (
            <ListRow
              title={c.withdrawRequest}
              action="accent"
              disabled={runner.busy}
              loading={runner.isRunning('withdrawCancellation')}
              onClick={() => void handleWithdraw()}
            />
          )}
          {showForce && (
            <ListRow
              title={c.cancelForceClose}
              action="danger"
              disabled={!deadlinePassed || runner.busy}
              loading={runner.isRunning('forceCancellation')}
              onClick={() => void handleForce()}
            />
          )}
        </List>
      )}
      {isManager && disputed && deadline && !deadlinePassed && (
        <Note>{c.cancelForceCloseLockedUntil(shortDateTime(deadline, tz))}</Note>
      )}
    </section>
  );
}
