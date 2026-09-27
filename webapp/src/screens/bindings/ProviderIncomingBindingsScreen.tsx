import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canRespondToBindings } from '../../lib/roles';
import { useBindingInvitations, useBindingsList, useRespondBinding } from '../../api/hooks/useBindings';
import { ApiError } from '../../api/errors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import type { ProviderBinding } from '../../api/types';
import { Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { equipmentTitle, shortDate } from './bindingView';
import { InvitationRows } from './ProviderBindingInvitationsScreen';

const INVITATIONS_PREVIEW = 5;

function equipmentLabel(equipment: ProviderBinding['equipment']): string {
  if (!equipment) return strings.common.notSpecified;
  const title = equipmentTitle(equipment);
  return title === strings.common.notSpecified ? equipment.serial_number || equipment.id : title;
}

function RequestSheet({ binding, onClose }: { binding: ProviderBinding | null; onClose: () => void }) {
  const respond = useRespondBinding();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  if (!binding) return null;

  const run = async (decision: 'confirm' | 'reject') => {
    setError(null);
    if (decision === 'reject' && !reason.trim()) return;
    try {
      await respond.mutateAsync(
        decision === 'confirm' ? { id: binding.id, decision } : { id: binding.id, decision, reason: reason.trim() },
      );
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.common.unknownError);
    }
  };

  return (
    <Sheet
      open
      title={binding.customer.name}
      description={strings.bindings.incomingOnlyDeclared}
      onClose={onClose}
      locked={respond.isPending}
      actions={
        rejecting ? (
          <>
            <ActionButton kind="d" disabled={!reason.trim()} loading={respond.isPending} onClick={() => void run('reject')}>
              {strings.bindings.incomingReject}
            </ActionButton>
            <ActionButton kind="s" onClick={() => setRejecting(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        ) : (
          <>
            <ActionButton loading={respond.isPending} onClick={() => void run('confirm')}>
              {strings.bindings.incomingConfirm}
            </ActionButton>
            <ActionButton kind="s" disabled={respond.isPending} onClick={() => setRejecting(true)}>
              {strings.bindings.incomingReject}
            </ActionButton>
          </>
        )
      }
    >
      <List>
        <ListRow
          title={strings.bindings.detailContract}
          value={binding.contract_number ? strings.bindings.contractNo(binding.contract_number) : strings.common.notSpecified}
        />
        <ListRow title={strings.bindings.detailBasis} value={strings.bindings.basisLabel[binding.basis]} />
        <ListRow
          title={strings.bindings.detailEquipment}
          value={equipmentLabel(binding.equipment)}
        />
        {binding.equipment?.serial_number && (
          <ListRow title={strings.equipment.serialNumber} value={binding.equipment.serial_number} />
        )}
      </List>
      {rejecting && (
        <TextAreaField
          label={strings.bindings.incomingRejectReasonLabel}
          value={reason}
          onChange={setReason}
        />
      )}
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Sheet>
  );
}

export function ProviderIncomingBindingsScreen() {
  const { activeMembership } = useSession();
  const bindings = useBindingsList();
  const invitations = useBindingInvitations();
  const [openId, setOpenId] = useState<string | null>(null);

  const title = strings.bindings.clientsTitle;
  if (!activeMembership) return null;
  if (!canRespondToBindings(activeMembership.role)) {
    return (
      <Screen title={title}>
        <NoAccessState />
      </Screen>
    );
  }
  if (bindings.isPending) {
    return (
      <Screen title={title}>
        <Skeleton lines={4} />
      </Screen>
    );
  }
  if (bindings.isError) {
    return (
      <Screen title={title}>
        <ErrorState error={bindings.error} onRetry={() => void bindings.refetch()} />
      </Screen>
    );
  }

  const items = bindings.data as ProviderBinding[];
  const pending = items.filter((b) => b.status === 'pending');
  const confirmed = items.filter((b) => b.status === 'confirmed');
  const opened = pending.find((b) => b.id === openId) ?? null;
  const invitationItems = invitations.data ?? [];

  return (
    <Screen title={title}>
      <section aria-labelledby="clients-requests">
        <SectionCaption id="clients-requests">{strings.bindings.requestsCaption}</SectionCaption>
        {pending.length === 0 ? (
          <Note>{strings.bindings.incomingEmpty}</Note>
        ) : (
          <List>
            {pending.map((binding) => (
              <ListRow
                key={binding.id}
                title={binding.customer.name}
                subtitle={strings.bindings.requestSubtitle(
                  binding.contract_number ?? strings.common.notSpecified,
                  equipmentLabel(binding.equipment),
                )}
                tag={{ label: strings.bindings.requestTag, tone: 'a' }}
                onClick={() => setOpenId(binding.id)}
                chevron
              />
            ))}
          </List>
        )}
      </section>

      <section aria-labelledby="clients-invitations">
        <SectionCaption id="clients-invitations">{strings.bindings.invitationsCaption}</SectionCaption>
        {invitations.isPending && <Skeleton lines={2} />}
        {invitations.isError && (
          <ErrorState error={invitations.error} onRetry={() => void invitations.refetch()} />
        )}
        {invitations.isSuccess && (
          <InvitationRows
            invitations={invitationItems.slice(0, INVITATIONS_PREVIEW)}
            footer={
              <>
                {invitationItems.length > INVITATIONS_PREVIEW && (
                  <ListRow title={strings.bindings.invitationsAll} to="/bindings/invitations" chevron />
                )}
                <ListRow title={strings.bindings.invitationsCreate} action="accent" to="/bindings/invitations?new=1" />
              </>
            }
          />
        )}
      </section>

      <section aria-labelledby="clients-confirmed">
        <SectionCaption id="clients-confirmed">{strings.bindings.confirmedTitle}</SectionCaption>
        {confirmed.length === 0 ? (
          <Note>{strings.bindings.confirmedEmpty}</Note>
        ) : (
          <List>
            {confirmed.map((binding) => (
              <ListRow
                key={binding.id}
                title={binding.customer.name}
                subtitle={[
                  equipmentLabel(binding.equipment),
                  binding.valid_until ? strings.bindings.until(shortDate(binding.valid_until)) : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                tag={{ label: strings.bindings.statusLabel.confirmed, tone: 'ok' }}
              />
            ))}
          </List>
        )}
      </section>

      <Note>{strings.bindings.clientsNote}</Note>

      <RequestSheet key={opened?.id ?? 'none'} binding={opened} onClose={() => setOpenId(null)} />
    </Screen>
  );
}
