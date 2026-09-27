import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useCreateWarrantyAuthorization,
  useOperatorWarrantyAuthorizations,
  useRevokeWarrantyAuthorization,
} from '../../api/hooks/useOperatorWarranty';
import type { OperatorWarrantyAuthorization } from '../../api/operatorTypes';
import type { GuarantorKind, WarrantyAuthorizationStatus } from '../../api/types';
import { useConfirm } from '../../components/useConfirm';
import { Banner, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { SelectField, TextAreaField, TextField } from '../../ui/FormField';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { OperatorScreen } from './OperatorScreen';

const GUARANTOR_OPTIONS: { value: GuarantorKind; label: string }[] = [
  { value: 'manufacturer', label: strings.operator.warrantyGuarantorKind.manufacturer },
  { value: 'seller', label: strings.operator.warrantyGuarantorKind.seller },
  { value: 'service_org', label: strings.operator.warrantyGuarantorKind.service_org },
];

const STATUS_TONE: Record<WarrantyAuthorizationStatus, Tone> = {
  pending: 'y',
  active: 'ok',
  expired: 'w',
  revoked: 'x',
};

function IssueSheet({ onClose, onIssued }: { onClose: () => void; onIssued: () => void }) {
  const [providerOrgId, setProviderOrgId] = useState('');
  const [guarantorKind, setGuarantorKind] = useState<GuarantorKind>('manufacturer');
  const [guarantorName, setGuarantorName] = useState('');
  const [brands, setBrands] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [cityId, setCityId] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [source, setSource] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const create = useCreateWarrantyAuthorization();

  const valid =
    providerOrgId.trim().length > 0 && source.trim().length > 0 && reason.trim().length > 0;

  const handleSubmit = async () => {
    if (!valid) return;
    setError(null);
    try {
      await create.mutateAsync({
        provider_organization_id: providerOrgId.trim(),
        guarantor_kind: guarantorKind,
        guarantor_name: guarantorName.trim() || null,
        brands: brands
          .split(',')
          .map((b) => b.trim())
          .filter(Boolean),
        equipment_category_id: categoryId.trim() || null,
        city_id: cityId.trim() || null,
        valid_until: validUntil || null,
        source: source.trim(),
        reason: reason.trim(),
        is_demo: false,
      });
      onIssued();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.warrantyIssueError);
    }
  };

  return (
    <Sheet
      open
      title={strings.operator.warrantyIssueTitle}
      onClose={onClose}
      locked={create.isPending}
      actions={
        <>
          <ActionButton
            disabled={!valid}
            loading={create.isPending}
            onClick={() => void handleSubmit()}
          >
            {strings.operator.warrantyIssueSubmit}
          </ActionButton>
          <ActionButton kind="s" disabled={create.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextField
        id="warranty-provider"
        label={strings.operator.warrantyProviderLabel}
        value={providerOrgId}
        onChange={setProviderOrgId}
      />
      <SelectField
        id="warranty-guarantor-kind"
        label={strings.operator.warrantyGuarantorKindLabel}
        value={guarantorKind}
        onChange={(v) => setGuarantorKind(v as GuarantorKind)}
        options={GUARANTOR_OPTIONS}
      />
      <TextField
        id="warranty-guarantor-name"
        label={strings.operator.warrantyGuarantorNameLabel}
        value={guarantorName}
        onChange={setGuarantorName}
      />
      <TextField
        id="warranty-brands"
        label={strings.operator.warrantyBrandsLabel}
        value={brands}
        onChange={setBrands}
      />
      <TextField
        id="warranty-category"
        label={strings.operator.warrantyCategoryLabel}
        value={categoryId}
        onChange={setCategoryId}
      />
      <TextField
        id="warranty-city"
        label={strings.operator.warrantyCityLabel}
        value={cityId}
        onChange={setCityId}
      />
      <TextField
        id="warranty-valid-until"
        type="date"
        label={strings.operator.warrantyValidUntilLabel}
        value={validUntil}
        onChange={setValidUntil}
      />
      <TextAreaField
        id="warranty-source"
        label={strings.operator.warrantySourceLabel}
        value={source}
        onChange={setSource}
        rows={2}
      />
      <TextAreaField
        id="warranty-reason"
        label={strings.operator.warrantyReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
    </Sheet>
  );
}

function RevokeSheet({
  item,
  onClose,
}: {
  item: OperatorWarrantyAuthorization;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const revoke = useRevokeWarrantyAuthorization(item.id);
  const { confirm, dialog } = useConfirm();

  const handleRevoke = async () => {
    if (!reason.trim()) return;
    const ok = await confirm({ title: strings.operator.warrantyRevoke, destructive: true });
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
      title={item.guarantor_name ?? item.provider_organization_id}
      description={strings.operator.warrantyStatus[item.status]}
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
            {strings.operator.warrantyRevoke}
          </ActionButton>
          <ActionButton kind="s" disabled={revoke.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id={`warranty-revoke-${item.id}`}
        label={strings.operator.warrantyRevokeReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
      {dialog}
    </Sheet>
  );
}

export function WarrantyAuthorizationsScreen() {
  const [issuing, setIssuing] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const list = useOperatorWarrantyAuthorizations();
  const items = list.data ?? [];
  const open = items.find((item) => item.id === openId) ?? null;

  return (
    <OperatorScreen
      title={strings.operator.warrantyQueueTitle}
      query={list}
      empty={items.length === 0}
      emptyTitle={strings.operator.warrantyEmpty}
      overlay={
        <>
          {open && <RevokeSheet key={open.id} item={open} onClose={() => setOpenId(null)} />}
          {issuing && (
            <IssueSheet
              onClose={() => setIssuing(false)}
              onIssued={() => {
                setIssuing(false);
                void list.refetch();
              }}
            />
          )}
        </>
      }
      actions={
        <BottomActions>
          <ActionButton kind="s" onClick={() => setIssuing(true)}>
            {strings.operator.warrantyIssueTitle}
          </ActionButton>
        </BottomActions>
      }
    >
      <List>
        {items.map((item) => {
          const canRevoke = item.status === 'active' || item.status === 'pending';
          return (
            <ListRow
              key={item.id}
              title={item.guarantor_name ?? item.provider_organization_id}
              subtitle={item.brands.join(', ') || strings.operator.warrantyBrandsAll}
              tag={{
                label: strings.operator.warrantyStatus[item.status],
                tone: STATUS_TONE[item.status],
              }}
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
