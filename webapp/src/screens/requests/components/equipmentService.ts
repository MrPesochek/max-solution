import { strings } from '../../../strings/ru';
import type { Equipment, EquipmentBindingSummary } from '../../../api/types';
import { shortDate } from '../../bindings/bindingView';

export interface EquipmentService {
  deliverable: EquipmentBindingSummary | null;
  contact: EquipmentBindingSummary | null;
}

export function equipmentService(item: Pick<Equipment, 'binding'>): EquipmentService {
  const binding = item.binding;
  if (!binding) return { deliverable: null, contact: null };
  if (binding.is_contact_only) return { deliverable: null, contact: binding };
  return binding.status === 'confirmed' ? { deliverable: binding, contact: null } : { deliverable: null, contact: null };
}

export function serviceName(binding: EquipmentBindingSummary): string {
  return binding.provider_name?.trim() || strings.offers.providerFallback;
}

export type BindingSummaryKind = 'confirmed' | 'pending' | 'contact' | 'none';

export interface BindingSummary {
  kind: BindingSummaryKind;
  text: string;
  tone: 'plain' | 'warn';
}

export function bindingSummary(item: Pick<Equipment, 'binding'>): BindingSummary {
  const t = strings.equipment.serviceSummary;
  const b = item.binding;
  if (!b || (b.status !== 'confirmed' && b.status !== 'pending')) {
    return { kind: 'none', text: t.none, tone: 'plain' };
  }
  if (b.is_contact_only) return { kind: 'contact', text: t.contact(serviceName(b)), tone: 'plain' };
  if (b.status === 'pending') {
    return { kind: 'pending', text: t.pending(b.provider_name?.trim() || null), tone: 'warn' };
  }
  const name = serviceName(b);
  const until = b.valid_until ? shortDate(b.valid_until) : null;
  const guarantor = b.guarantor_name?.trim() || null;
  if (b.basis === 'warranty' || b.guarantor_kind || guarantor) {
    const stated = b.guarantor_stated_by_provider && !b.warranty_authorization_id;
    return { kind: 'confirmed', text: t.warranty(guarantor ?? name, until || null, stated), tone: 'plain' };
  }
  if (b.basis === 'service_contract') return { kind: 'confirmed', text: t.contract(name, until || null), tone: 'plain' };
  return { kind: 'confirmed', text: t.preferred(name), tone: 'plain' };
}
