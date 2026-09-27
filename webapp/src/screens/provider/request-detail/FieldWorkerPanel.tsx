import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useSetFieldWorker } from '../../../api/hooks/useProviderRequests';
import { useStaff } from '../../../api/hooks/useMemberships';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note } from '../../../ui/blocks/Blocks';
import { Segmented } from '../../../ui/Segmented';
import { PhoneField, SelectField, TextField } from '../../../ui/FormField';
import { runAndClose, type ProviderSubViewProps } from './types';

type Mode = 'staff' | 'external';

export function FieldWorkerPanel({ request, runner, onDone }: ProviderSubViewProps) {
  const setFieldWorker = useSetFieldWorker(request.id);
  const staff = useStaff();
  const current = request.assignment.field_worker;
  const [mode, setMode] = useState<Mode>(current?.stated_by_company ? 'external' : 'staff');
  const [membershipId, setMembershipId] = useState(current?.membership_id ?? '');
  const [name, setName] = useState(current?.stated_by_company ? (current.display_name ?? '') : '');
  const [phone, setPhone] = useState(
    current?.stated_by_company ? (current.contact_phone ?? '') : '',
  );
  const valid = mode === 'staff' ? Boolean(membershipId) : Boolean(name.trim());

  return (
    <Screen
      title={strings.workspace.fieldWorkerTitle}
      subtitle={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('fieldWorker')}
            disabled={runner.busy || !valid}
            onClick={() =>
              void runAndClose(
                runner,
                'fieldWorker',
                () =>
                  setFieldWorker.mutateAsync({
                    assignment_id: request.assignment.id,
                    membership_id: mode === 'staff' ? membershipId : null,
                    display_name: mode === 'staff' ? null : name.trim(),
                    contact_phone: mode === 'external' ? phone.trim() || null : null,
                    expected_version: request.version,
                  }),
                onDone,
              )
            }
          >
            {strings.workspace.fieldWorkerSave}
          </ActionButton>
        </BottomActions>
      }
    >
      <Segmented
        label={strings.workspace.fieldWorkerTitle}
        items={[
          { id: 'staff', label: strings.workspace.fieldWorkerModeStaff },
          { id: 'external', label: strings.workspace.fieldWorkerModeExternal },
        ]}
        value={mode}
        onChange={setMode}
      />
      {mode === 'staff' ? (
        <SelectField
          id="field-worker-staff"
          label={strings.workspace.fieldWorkerStaffLabel}
          value={membershipId}
          onChange={setMembershipId}
          options={(staff.data ?? []).map((m) => ({ value: m.id, label: m.user.display_name }))}
          placeholder={strings.workspace.fieldWorkerStaffPlaceholder}
        />
      ) : (
        <>
          <TextField
            id="fw-name"
            label={strings.workspace.fieldWorkerNameLabel}
            value={name}
            onChange={setName}
          />
          <PhoneField
            id="fw-phone"
            label={strings.workspace.fieldWorkerPhoneLabel}
            value={phone}
            onChange={setPhone}
          />
          <Note>{strings.workspace.fieldWorkerExternalNote}</Note>
        </>
      )}
      <ActionFeedback feedback={runner.feedback} />
    </Screen>
  );
}
