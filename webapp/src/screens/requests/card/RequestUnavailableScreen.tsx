import type { ReactNode } from 'react';
import { strings } from '../../../strings/ru';
import { useRequestAccess } from '../../../api/hooks/useMemberships';
import { useSession } from '../../../session/SessionContext';
import { canManageLocationsAndEquipment, isCustomer } from '../../../lib/roles';
import { NoAccessState } from '../../../components/states/NoAccessState';
import { actionErrorMessage } from '../../../components/actions/actionErrors';
import { Note } from '../../../ui/blocks/Blocks';
import { Screen, BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';

export function RequestUnavailableScreen({ title, back }: { title: ReactNode; back?: string }) {
  const { activeMembership } = useSession();
  const requestAccess = useRequestAccess();
  const t = strings.requests;
  const canAsk = Boolean(
    activeMembership &&
      isCustomer(activeMembership.role) &&
      !canManageLocationsAndEquipment(activeMembership.role),
  );
  const sent = requestAccess.isSuccess;

  return (
    <Screen
      title={title}
      back={back}
      actions={
        <BottomActions>
          {canAsk && (
            <ActionButton
              kind={sent ? 's' : 'p'}
              loading={requestAccess.isPending}
              disabled={sent}
              onClick={() => requestAccess.mutate({})}
            >
              {sent ? t.accessRequested : t.requestAccess}
            </ActionButton>
          )}
          <ActionButton kind={canAsk ? 'g' : 'p'} to="/requests">
            {t.toMyRequests}
          </ActionButton>
        </BottomActions>
      }
    >
      <NoAccessState title={t.unavailableTitle} description={t.unavailableDescription} />
      {sent && <Note role="status">{t.accessRequestedText}</Note>}
      {requestAccess.isError && (
        <Note tone="error" role="alert">
          {actionErrorMessage(requestAccess.error, strings.common.unknownError)}
        </Note>
      )}
    </Screen>
  );
}
