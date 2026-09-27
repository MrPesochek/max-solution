import { useMemo, useState } from 'react';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canManageBindings } from '../../lib/roles';
import { useBindingsList, useRevokeBinding } from '../../api/hooks/useBindings';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { ApiError } from '../../api/errors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import type { ServiceBinding } from '../../api/types';
import { Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { initials } from '../../ui/format';
import {
  bindingSubtitle,
  bindingTag,
  equipmentTitle,
  guarantorName,
  guarantorStated,
  hasWarranty,
  shortDate,
} from './bindingView';

function BindingSheet({
  binding,
  equipmentName,
  canManage,
  onClose,
}: {
  binding: ServiceBinding | null;
  equipmentName: string;
  canManage: boolean;
  onClose: () => void;
}) {
  const revokeBinding = useRevokeBinding();
  const [revoking, setRevoking] = useState(false);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setRevoking(false);
    setReason('');
    setError(null);
    onClose();
  };

  if (!binding) return null;
  const revocable = canManage && (binding.status === 'pending' || binding.status === 'confirmed');

  const handleRevoke = async () => {
    setError(null);
    if (!reason.trim()) return;
    try {
      await revokeBinding.mutateAsync({ id: binding.id, reason: reason.trim() });
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.common.unknownError);
    }
  };

  return (
    <Sheet
      open
      title={binding.provider.name}
      description={binding.status_explanation}
      onClose={close}
      locked={revokeBinding.isPending}
      actions={
        revocable ? (
          revoking ? (
            <>
              <ActionButton
                kind="d"
                disabled={!reason.trim()}
                loading={revokeBinding.isPending}
                onClick={() => void handleRevoke()}
              >
                {strings.bindings.revokeConfirm}
              </ActionButton>
              <ActionButton kind="s" onClick={() => setRevoking(false)}>
                {strings.common.cancel}
              </ActionButton>
            </>
          ) : (
            <ActionButton kind="d" onClick={() => setRevoking(true)}>
              {strings.bindings.revokeButton}
            </ActionButton>
          )
        ) : undefined
      }
    >
      <List>
        <ListRow title={strings.bindings.detailEquipment} value={equipmentName} />
        <ListRow
          title={strings.bindings.detailStatus}
          value={binding.is_contact_only ? strings.bindings.contactOnlyBadge : strings.bindings.statusLabel[binding.status]}
        />
        {binding.contract_number && (
          <ListRow title={strings.bindings.detailContract} value={strings.bindings.contractNo(binding.contract_number)} />
        )}
        {!binding.is_contact_only && (
          <ListRow title={strings.bindings.detailBasis} value={strings.bindings.basisLabel[binding.basis]} />
        )}
        {binding.valid_until && (
          <ListRow title={strings.bindings.detailTerm} value={strings.bindings.until(shortDate(binding.valid_until))} />
        )}
        {hasWarranty(binding) && (
          <ListRow
            title={strings.bindings.guarantorLabel}
            subtitle={guarantorStated(binding) ? strings.bindings.acceptGuarantorHint : undefined}
            value={guarantorName(binding)}
          />
        )}
      </List>
      {binding.status_reason && <Note>{binding.status_reason}</Note>}
      {revoking && (
        <TextAreaField
          label={strings.bindings.revokeReasonLabel}
          value={reason}
          onChange={setReason}
          error={error ?? undefined}
        />
      )}
    </Sheet>
  );
}

export function BindingsListScreen() {
  const { activeMembership } = useSession();
  const bindings = useBindingsList();
  const equipment = useOrgEquipment();
  const [openId, setOpenId] = useState<string | null>(null);

  const equipmentNames = useMemo(
    () => new Map((equipment.data ?? []).map((item) => [item.id, equipmentTitle(item)])),
    [equipment.data],
  );

  if (!activeMembership) return null;
  const canManage = canManageBindings(activeMembership.role);
  const title = strings.bindings.title;

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

  const items = bindings.data as ServiceBinding[];
  const opened = items.find((b) => b.id === openId) ?? null;
  const nameOf = (binding: ServiceBinding) => equipmentNames.get(binding.equipment_id) ?? strings.common.notSpecified;

  return (
    <Screen title={title}>
      {items.length === 0 ? (
        <EmptyState title={strings.bindings.empty} description={strings.bindings.emptyText} />
      ) : (
        <List>
          {items.map((binding) => (
            <ListRow
              key={binding.id}
              title={binding.provider.name}
              subtitle={`${nameOf(binding)} · ${bindingSubtitle(binding)}`}
              icon={initials(binding.provider.name)}
              gradient={binding.is_contact_only ? 'n' : 'g'}
              tag={binding.is_contact_only ? { label: strings.bindings.contactOnlyBadge, tone: 'w' } : bindingTag(binding)}
              extra={
                binding.invitation_item_index !== null ? (
                  <span className="ui-row__sub">{strings.bindings.invitationItem(binding.invitation_item_index, binding.invitation_item_description)}</span>
                ) : undefined
              }
              onClick={() => setOpenId(binding.id)}
              chevron
            />
          ))}
        </List>
      )}

      <List>
        {canManage && <ListRow title={strings.bindings.addButton} action="accent" to="/bindings/new" />}
        <ListRow title={strings.bindings.catalogLink} to="/providers" chevron />
      </List>

      <BindingSheet
        key={opened?.id ?? 'none'}
        binding={opened}
        equipmentName={opened ? nameOf(opened) : ''}
        canManage={canManage}
        onClose={() => setOpenId(null)}
      />
    </Screen>
  );
}
