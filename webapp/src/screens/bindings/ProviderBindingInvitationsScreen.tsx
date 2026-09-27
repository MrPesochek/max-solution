import { useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canRespondToBindings } from '../../lib/roles';
import {
  useBindingInvitations,
  useCreateBindingInvitation,
  useRevokeBindingInvitation,
} from '../../api/hooks/useBindings';
import { ApiError } from '../../api/errors';
import { haptics, openExternalLink } from '../../max/bridge';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { NoAccessState } from '../../components/states/NoAccessState';
import type {
  BindingInvitation,
  BindingInvitationIssued,
  BindingInvitationItemInput,
  InvitationState,
} from '../../api/types';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, SectionCaption, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { SelectField, TextField } from '../../ui/FormField';
import { StatusHero } from '../../ui/StatusHero';
import { shortDate } from './bindingView';
import './bindings.css';

const STATE_TONE: Record<InvitationState, Tone> = {
  active: 'w',
  used: 'ok',
  revoked: 'x',
  expired: 'w',
  declined: 'x',
};

function invitationTitle(invitation: BindingInvitation): string {
  return (
    invitation.customer_name?.trim() ||
    strings.bindings.invitationTitle(invitation.contract_number ?? strings.common.notSpecified)
  );
}

function InvitationSheet({ invitation, onClose }: { invitation: BindingInvitation | null; onClose: () => void }) {
  const revokeInvitation = useRevokeBindingInvitation();
  const [error, setError] = useState<string | null>(null);
  if (!invitation) return null;

  const handleRevoke = async () => {
    setError(null);
    try {
      await revokeInvitation.mutateAsync(invitation.id);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.common.unknownError);
    }
  };

  return (
    <Sheet
      open
      title={invitationTitle(invitation)}
      description={strings.bindings.invitationsState[invitation.state]}
      onClose={onClose}
      locked={revokeInvitation.isPending}
      actions={
        invitation.state === 'active' ? (
          <ActionButton kind="d" loading={revokeInvitation.isPending} onClick={() => void handleRevoke()}>
            {strings.bindings.invitationRevoke}
          </ActionButton>
        ) : undefined
      }
    >
      <List>
        {invitation.customer_name && invitation.contract_number && (
          <ListRow
            title={strings.bindings.detailContract}
            value={strings.bindings.contractNo(invitation.contract_number)}
          />
        )}
        {invitation.state === 'declined' && (
          <ListRow
            title={strings.bindings.invitationDeclinedAt}
            value={invitation.declined_at ? shortDate(invitation.declined_at) : undefined}
            subtitle={
              invitation.decline_reason ? strings.bindings.invitationDeclineReason(invitation.decline_reason) : undefined
            }
          />
        )}
        {invitation.equipment_items.map((item) => (
          <ListRow
            key={item.index}
            title={item.description ?? strings.bindings.acceptItemFallback(item.index + 1)}
            subtitle={[item.model, item.serial_number].filter(Boolean).join(' · ') || undefined}
          />
        ))}
        <ListRow title={strings.bindings.acceptExpires} value={shortDate(invitation.expires_at)} />
      </List>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Sheet>
  );
}

export function InvitationRows({ invitations, footer }: { invitations: BindingInvitation[]; footer?: ReactNode }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const opened = invitations.find((i) => i.id === openId) ?? null;
  return (
    <>
      <List>
        {invitations.map((invitation) => (
          <ListRow
            key={invitation.id}
            title={invitationTitle(invitation)}
            subtitle={
              invitation.state === 'declined' && invitation.decline_reason
                ? strings.bindings.invitationDeclineReason(invitation.decline_reason)
                : strings.bindings.invitationSubtitle(
                    strings.bindings.invitationUnits(invitation.equipment_items.length),
                    shortDate(invitation.expires_at, false),
                  )
            }
            tag={{ label: strings.bindings.invitationTag[invitation.state], tone: STATE_TONE[invitation.state] }}
            onClick={() => setOpenId(invitation.id)}
            chevron
          />
        ))}
        {footer}
      </List>
      <InvitationSheet key={opened?.id ?? 'none'} invitation={opened} onClose={() => setOpenId(null)} />
    </>
  );
}

function IssuedLink({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      haptics.notification('success');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // буфер обмена недоступен — ссылку можно скопировать вручную из поля
    }
  };
  return (
    <>
      <TextField
        label={label}
        value={value}
        readOnly
        className="ui-field__control--mono"
        onFocus={(event) => event.target.select()}
      />
      <div className="bd-link-actions">
        <ActionButton kind="s" compact onClick={() => void copy()}>
          {copied ? strings.common.copied : strings.common.copy}
        </ActionButton>
        <ActionButton kind="g" compact onClick={() => openExternalLink(value)}>
          {strings.common.open}
        </ActionButton>
      </div>
    </>
  );
}

interface ItemDraft {
  key: number;
  description: string;
  serialNumber: string;
  model: string;
}

let itemKeySeq = 0;
function emptyItem(): ItemDraft {
  itemKeySeq += 1;
  return { key: itemKeySeq, description: '', serialNumber: '', model: '' };
}

type Basis = 'warranty' | 'service_contract' | 'preferred_provider';

export function ProviderBindingInvitationsScreen() {
  const { activeMembership } = useSession();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const showForm = searchParams.get('new') === '1';
  const invitations = useBindingInvitations();
  const createInvitation = useCreateBindingInvitation();

  const [customerInn, setCustomerInn] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [contractNumber, setContractNumber] = useState('');
  const [basis, setBasis] = useState<Basis>('service_contract');
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [items, setItems] = useState<ItemDraft[]>(() => [emptyItem()]);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<BindingInvitationIssued | null>(null);

  const closeForm = () => {
    setCreated(null);
    setFormError(null);
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) {
      navigate(-1);
      return;
    }
    const params = new URLSearchParams(searchParams);
    params.delete('new');
    setSearchParams(params, { replace: true });
  };

  if (!activeMembership) return null;
  if (!canRespondToBindings(activeMembership.role)) {
    return (
      <Screen title={strings.bindings.invitationsTitle}>
        <NoAccessState />
      </Screen>
    );
  }

  if (created) {
    return (
      <Screen
        title={strings.bindings.invitationsNewTitle}
        back={closeForm}
        actions={
          <BottomActions>
            <ActionButton onClick={closeForm}>{strings.bindings.done}</ActionButton>
          </BottomActions>
        }
      >
        <StatusHero icon="✓" tone="ok" top={40} title={strings.bindings.invitationsCreatedTitle} role="status">
          {strings.bindings.invitationsLinkNotice}
        </StatusHero>
        {created.webapp_link && <IssuedLink label={strings.organization.inviteLinkWebapp} value={created.webapp_link} />}
        {created.bot_link && <IssuedLink label={strings.organization.inviteLinkBot} value={created.bot_link} />}
        <Note>{strings.bindings.invitationsCopyReminder}</Note>
      </Screen>
    );
  }

  if (showForm) {
    const itemsValid = items.length > 0 && items.every((item) => item.description.trim());
    const canSubmit = Boolean(customerInn.trim() && contractNumber.trim() && itemsValid);
    const updateItem = (key: number, patch: Partial<ItemDraft>) => {
      setItems((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)));
    };

    const handleCreate = async (event: FormEvent) => {
      event.preventDefault();
      setFormError(null);
      if (!canSubmit || createInvitation.isPending) return;
      const equipmentItems: BindingInvitationItemInput[] = items.map((item) => ({
        description: item.description.trim(),
        serial_number: item.serialNumber.trim() || null,
        model: item.model.trim() || null,
      }));
      try {
        const issued = await createInvitation.mutateAsync({
          customer_inn: customerInn.trim(),
          contract_number: contractNumber.trim(),
          basis,
          valid_from: validFrom || undefined,
          valid_until: validUntil || undefined,
          customer_name: customerName.trim() || undefined,
          equipment_items: equipmentItems,
        });
        setCreated(issued);
        setCustomerInn('');
        setCustomerName('');
        setContractNumber('');
        setValidFrom('');
        setValidUntil('');
        setItems([emptyItem()]);
      } catch (error) {
        setFormError(error instanceof ApiError ? error.message : strings.common.unknownError);
      }
    };

    return (
      <Screen
        title={strings.bindings.invitationsNewTitle}
        back={closeForm}
        actions={
          <BottomActions>
            <ActionButton
              type="submit"
              form="invitation-form"
              disabled={!canSubmit}
              loading={createInvitation.isPending}
            >
              {strings.bindings.invitationsSubmit}
            </ActionButton>
          </BottomActions>
        }
      >
        <form id="invitation-form" onSubmit={(event) => void handleCreate(event)}>
          <TextField
            id="invitation-customer-inn"
            label={strings.bindings.invitationsCustomerInn}
            value={customerInn}
            inputMode="numeric"
            onChange={(value) => setCustomerInn(value.replace(/\D/g, ''))}
          />
          <TextField
            id="invitation-customer-name"
            label={strings.bindings.invitationsCustomerName}
            placeholder={strings.equipment.optionalPlaceholder}
            value={customerName}
            onChange={setCustomerName}
          />
          <TextField
            id="invitation-contract-number"
            label={strings.bindings.invitationsContract}
            value={contractNumber}
            onChange={setContractNumber}
          />
          <SelectField
            id="invitation-basis"
            label={strings.bindings.invitationsBasis}
            value={basis}
            onChange={(value) => setBasis(value as Basis)}
            options={[
              { value: 'service_contract', label: strings.bindings.basisLabel.service_contract },
              { value: 'warranty', label: strings.bindings.basisLabel.warranty },
              { value: 'preferred_provider', label: strings.bindings.basisLabel.preferred_provider },
            ]}
          />
          <TextField
            id="invitation-valid-from"
            type="date"
            label={strings.bindings.invitationsValidFrom}
            value={validFrom}
            onChange={setValidFrom}
          />
          <TextField
            id="invitation-valid-until"
            type="date"
            label={strings.bindings.invitationsValidUntil}
            value={validUntil}
            onChange={setValidUntil}
          />

          <SectionCaption>{strings.bindings.invitationsItemsTitle}</SectionCaption>
          <Note>{strings.bindings.invitationsItemsHint}</Note>
          {items.map((item, index) => {
            const label = strings.bindings.invitationsItemLabel(index + 1);
            return (
              <section key={item.key} role="group" aria-label={label}>
                <SectionCaption as="div">{label}</SectionCaption>
                <TextField
                  id={`invitation-item-${item.key}-description`}
                  label={strings.bindings.invitationsItemDescription}
                  value={item.description}
                  placeholder={strings.bindings.invitationsEquipmentPlaceholder}
                  onChange={(value) => updateItem(item.key, { description: value })}
                />
                <TextField
                  id={`invitation-item-${item.key}-model`}
                  label={strings.bindings.invitationsItemModel}
                  placeholder={strings.equipment.optionalPlaceholder}
                  value={item.model}
                  onChange={(value) => updateItem(item.key, { model: value })}
                />
                <TextField
                  id={`invitation-item-${item.key}-serial`}
                  label={strings.bindings.invitationsItemSerial}
                  placeholder={strings.equipment.optionalPlaceholder}
                  value={item.serialNumber}
                  onChange={(value) => updateItem(item.key, { serialNumber: value })}
                />
                {items.length > 1 && (
                  <List>
                    <ListRow
                      title={strings.bindings.invitationsItemRemove}
                      action="danger"
                      aria-label={`${strings.bindings.invitationsItemRemove}: ${label}`}
                      onClick={() => setItems((prev) => prev.filter((i) => i.key !== item.key))}
                    />
                  </List>
                )}
              </section>
            );
          })}
          <List>
            <ListRow
              title={strings.bindings.invitationsItemAdd}
              action="accent"
              onClick={() => setItems((prev) => [...prev, emptyItem()])}
            />
          </List>

          {formError && (
            <Note tone="error" role="alert">
              {formError}
            </Note>
          )}
        </form>
      </Screen>
    );
  }

  const title = strings.bindings.invitationsTitle;
  if (invitations.isPending) {
    return (
      <Screen title={title}>
        <Skeleton lines={4} />
      </Screen>
    );
  }
  if (invitations.isError) {
    return (
      <Screen title={title}>
        <ErrorState error={invitations.error} onRetry={() => void invitations.refetch()} />
      </Screen>
    );
  }

  const openForm = () => {
    const params = new URLSearchParams(searchParams);
    params.set('new', '1');
    setSearchParams(params);
  };

  return (
    <Screen title={title}>
      {invitations.data.length === 0 && <EmptyState title={strings.bindings.invitationsEmpty} />}
      <InvitationRows
        invitations={invitations.data}
        footer={<ListRow title={strings.bindings.invitationsCreate} action="accent" onClick={openForm} />}
      />
      <Note>{strings.bindings.clientsNote}</Note>
    </Screen>
  );
}
