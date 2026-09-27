import { useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useBindingsList } from '../../api/hooks/useBindings';
import { useEquipmentItem } from '../../api/hooks/useEquipment';
import type { ServiceBinding } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { Screen } from '../../ui/layout/Screen';
import { Note, PageTitle } from '../../ui/blocks/Blocks';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { List, ListRow } from '../../ui/List';
import { equipmentTitle } from '../requests/components/equipmentName';
import { guarantorName, guarantorStated, hasWarranty, shortDate } from './bindingView';

export function WarrantyScreen() {
  const { equipmentId } = useParams<{ equipmentId: string }>();
  const bindings = useBindingsList({ equipmentId });
  const item = useEquipmentItem(equipmentId);
  const title = strings.bindings.warrantyTitle;
  const headerTitle = item.data ? equipmentTitle(item.data) : strings.equipment.title;

  if (!equipmentId) return null;
  if (bindings.isPending) {
    return (
      <Screen title={headerTitle}>
        <Skeleton lines={4} />
      </Screen>
    );
  }
  if (bindings.isError) {
    return (
      <Screen title={headerTitle}>
        <ErrorState error={bindings.error} onRetry={() => void bindings.refetch()} />
      </Screen>
    );
  }

  const binding = (bindings.data as ServiceBinding[]).find((b) => b.status === 'confirmed' && hasWarranty(b));
  if (!binding) {
    return (
      <Screen title={headerTitle}>
        <EmptyState title={strings.bindings.warrantyNone} description={strings.bindings.warrantyNoneText} />
      </Screen>
    );
  }

  const authority = binding.warranty_authorization;
  const authorityActive = authority?.status === 'active';
  const validUntil = binding.valid_until ?? null;
  const authorityName = authority?.guarantor_name ?? guarantorName(binding);
  const authorityText = `${strings.bindings.warrantyAuthorityOk(authorityName)}${
    authority?.is_demo && !authorityName.includes(strings.bindings.warrantyAuthorityDemo)
      ? ` · ${strings.bindings.warrantyAuthorityDemo}`
      : ''
  }${authority?.valid_until ? ` · ${strings.bindings.warrantyAuthorityUntil(shortDate(authority.valid_until))}` : ''}`;
  const confirmations: KeyValueRow[] = [];
  if (binding.provider_confirmed_at) {
    confirmations.push({ label: strings.bindings.warrantyConfirmedByProvider, value: shortDate(binding.provider_confirmed_at) });
  }
  if (binding.customer_confirmed_at) {
    confirmations.push({ label: strings.bindings.warrantyConfirmedByCustomer, value: shortDate(binding.customer_confirmed_at) });
  }

  return (
    <Screen title={headerTitle}>
      <SceneBanner name="service-linked" height={130} />
      <PageTitle size="m">{title}</PageTitle>
      <KeyValueRows
        rows={[
          {
            label: strings.bindings.warrantyGuarantor,
            value: guarantorName(binding),
            hint: guarantorStated(binding) ? strings.bindings.acceptGuarantorHint : undefined,
          },
          { label: strings.bindings.warrantyServicer, value: binding.provider.name },
          { label: strings.bindings.warrantySource, value: strings.bindings.basisLabel[binding.basis] },
          {
            label: strings.bindings.warrantyTerm,
            value: validUntil ? strings.bindings.until(shortDate(validUntil)) : strings.bindings.warrantyNoTerm,
          },
          ...confirmations,
        ]}
      />
      <List>
        <ListRow
          title={strings.bindings.warrantyAuthority}
          subtitle={authority && authorityActive ? authorityText : strings.bindings.warrantyAuthorityNone(item.data?.brand ?? null)}
          marker={authority && authorityActive ? 'ok' : '-'}
        />
      </List>
      <Note>{strings.bindings.warrantyNote}</Note>
    </Screen>
  );
}
