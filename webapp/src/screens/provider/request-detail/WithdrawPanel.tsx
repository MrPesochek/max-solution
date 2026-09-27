import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useWithdrawAssignment } from '../../../api/hooks/useProviderRequests';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { List, ListRow } from '../../../ui/List';
import { Sheet } from '../../../ui/Sheet';
import { TextAreaField } from '../../../ui/FormField';
import { runAndClose, type ProviderPanelProps } from './types';

export function WithdrawPanel({ request, runner }: ProviderPanelProps) {
  const withdraw = useWithdrawAssignment(request.id);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');

  return (
    <>
      <List>
        <ListRow
          title={strings.workspace.actionWithdrawAssignment}
          action="danger"
          disabled={runner.busy}
          onClick={() => setOpen(true)}
        />
      </List>
      <Sheet
        open={open}
        role="alertdialog"
        title={strings.workspace.withdrawSheetTitle}
        description={strings.workspace.withdrawConfirm}
        onClose={() => setOpen(false)}
        locked={runner.busy}
        actions={
          <>
            <ActionButton
              kind="d"
              loading={runner.isRunning('withdraw')}
              disabled={!reason.trim() || runner.busy}
              onClick={() =>
                void runAndClose(
                  runner,
                  'withdraw',
                  () =>
                    withdraw.mutateAsync({
                      assignment_id: request.assignment.id,
                      reason: reason.trim(),
                      expected_version: request.version,
                    }),
                  () => setOpen(false),
                )
              }
            >
              {strings.workspace.actionWithdrawAssignment}
            </ActionButton>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setOpen(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        <TextAreaField
          label={strings.workspace.withdrawReasonLabel}
          placeholder={strings.workspace.withdrawReasonLabel}
          value={reason}
          onChange={setReason}
          rows={3}
        />
        <ActionFeedback feedback={open ? runner.feedback : null} />
      </Sheet>
    </>
  );
}
