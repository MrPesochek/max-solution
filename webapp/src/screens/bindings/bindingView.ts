import { strings } from '../../strings/ru';
import type { Tone } from '../../ui/blocks/Blocks';
import type { BindingStatus, ServiceBinding } from '../../api/types';

export { equipmentTitle } from '../requests/components/equipmentName';

export function equipmentLetter(title: string): string {
  return title.trim().charAt(0).toUpperCase() || '?';
}

export function shortDate(iso: string | null | undefined, withYear = true): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const formatted = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    ...(withYear ? { year: 'numeric' } : {}),
  }).format(date);
  return formatted.replace('.', '').replace(/\s*г\.?$/, '');
}

export function bindingName(binding: ServiceBinding): string {
  return (binding.is_contact_only && binding.contact_name?.trim()) || binding.provider.name;
}

const STATUS_TONE: Record<BindingStatus, Tone> = {
  pending: 'y',
  confirmed: 'ok',
  rejected: 'x',
  revoked: 'w',
};

export function bindingTag(binding: ServiceBinding): { label: string; tone: Tone } | undefined {
  if (binding.is_contact_only) return undefined;
  if (binding.status === 'confirmed' && binding.provider_confirmed_at) {
    return {
      label: strings.bindings.confirmedOn(shortDate(binding.provider_confirmed_at, false)),
      tone: 'ok',
    };
  }
  return { label: strings.bindings.statusTag[binding.status], tone: STATUS_TONE[binding.status] };
}

export function bindingSubtitle(binding: ServiceBinding): string {
  if (binding.is_contact_only) {
    return [binding.contact_phone, strings.bindings.contactOnlySubtitle].filter(Boolean).join(' · ');
  }
  const parts: string[] = [];
  parts.push(
    binding.contract_number
      ? strings.bindings.contractShort(binding.contract_number)
      : strings.bindings.basisLabel[binding.basis],
  );
  if (binding.valid_until) parts.push(strings.bindings.until(shortDate(binding.valid_until)));
  return parts.join(' · ');
}

export function hasWarranty(binding: ServiceBinding): boolean {
  return (
    !binding.is_contact_only &&
    (binding.basis === 'warranty' ||
      binding.guarantor_kind !== null ||
      binding.warranty_authorization !== null)
  );
}

export function guarantorName(binding: ServiceBinding): string {
  return (
    binding.guarantor_name ??
    binding.warranty_authorization?.guarantor_name ??
    (binding.guarantor_kind === 'service_org' || binding.guarantor_kind === null
      ? binding.provider.name
      : strings.bindings.guarantorKind[binding.guarantor_kind])
  );
}

export function guarantorStated(binding: ServiceBinding): boolean {
  return binding.guarantor_stated_by_provider === true;
}

export type ServiceState = 'confirmed' | 'pending' | 'contact' | 'none';

export function serviceState(bindings: ServiceBinding[]): ServiceState {
  const live = bindings.filter((b) => b.status === 'pending' || b.status === 'confirmed');
  if (live.some((b) => !b.is_contact_only && b.status === 'confirmed')) return 'confirmed';
  if (live.some((b) => !b.is_contact_only && b.status === 'pending')) return 'pending';
  if (live.some((b) => b.is_contact_only)) return 'contact';
  return 'none';
}
