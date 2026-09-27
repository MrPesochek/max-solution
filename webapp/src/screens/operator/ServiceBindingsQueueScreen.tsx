import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { useOperatorBindings, useRevokeOperatorBinding } from '../../api/hooks/useOperatorBindings';
import type { OperatorBinding } from '../../api/operatorTypes';
import { useConfirm } from '../../components/useConfirm';
import { formatDateTime } from '../../lib/datetime';
import { Banner, Note, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { OperatorScreen } from './OperatorScreen';

const STATUS_TONE: Record<string, Tone> = {
  pending: 'y',
  confirmed: 'ok',
  rejected: 'x',
  revoked: 'w',
};

function statusLabel(status: string): string {
  return (strings.bindings.statusLabel as Record<string, string>)[status] ?? status;
}

function basisLabel(basis: string): string {
  return (strings.bindings.basisLabel as Record<string, string>)[basis] ?? basis;
}

function bindingTitle(item: OperatorBinding): string {
  return strings.operator.bindingTitle(
    item.customer_name,
    item.provider_name ?? strings.requests.card.providerUnknown,
  );
}

function BindingSheet({ item, onClose }: { item: OperatorBinding; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const revoke = useRevokeOperatorBinding(item.id);
  const { confirm, dialog } = useConfirm();

  const handleRevoke = async () => {
    if (!reason.trim()) return;
    const ok = await confirm({ title: strings.operator.bindingsRevoke, destructive: true });
    if (!ok) return;
    setError(null);
    try {
      await revoke.mutateAsync({ reason: reason.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  return (
    <Sheet
      open
      title={bindingTitle(item)}
      description={`${statusLabel(item.status)} · ${formatDateTime(item.created_at)}`}
      onClose={onClose}
      locked={revoke.isPending}
      actions={
        <>
          <ActionButton
            kind="d"
            disabled={!reason.trim()}
            loading={revoke.isPending}
            onClick={() => void handleRevoke()}
          >
            {strings.operator.bindingsRevoke}
          </ActionButton>
          <ActionButton kind="s" disabled={revoke.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <List>
        <ListRow
          title={strings.operator.bindingsBasisLabel}
          value={basisLabel(item.basis)}
          valueTone="secondary"
        />
        {item.contract_number && (
          <ListRow
            title={strings.operator.bindingsContractLabel}
            value={item.contract_number}
            valueTone="secondary"
          />
        )}
      </List>
      {item.status_reason && <Note>{item.status_reason}</Note>}
      <TextAreaField
        id={`binding-revoke-${item.id}`}
        label={strings.operator.bindingsRevokeReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function ServiceBindingsQueueScreen() {
  const list = useOperatorBindings();
  const [openId, setOpenId] = useState<string | null>(null);
  const items = list.data ?? [];
  const open = items.find((item) => item.id === openId) ?? null;

  return (
    <OperatorScreen
      title={strings.operator.bindingsQueueTitle}
      query={list}
      empty={items.length === 0}
      emptyTitle={strings.operator.bindingsEmpty}
      overlay={open && <BindingSheet key={open.id} item={open} onClose={() => setOpenId(null)} />}
    >
      <List>
        {items.map((item) => {
          const canRevoke = item.status !== 'revoked';
          return (
            <ListRow
              key={item.id}
              title={bindingTitle(item)}
              subtitle={`${basisLabel(item.basis)} · ${formatDateTime(item.created_at)}`}
              tag={{ label: statusLabel(item.status), tone: STATUS_TONE[item.status] ?? 'w' }}
              chevron={canRevoke}
              opensDialog={canRevoke}
              onClick={canRevoke ? () => setOpenId(item.id) : undefined}
            />
          );
        })}
      </List>
    </OperatorScreen>
  );
}
