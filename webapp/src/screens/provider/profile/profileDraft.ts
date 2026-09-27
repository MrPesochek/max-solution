import type { ProviderProfile, ProviderProfileUpdateInput } from '../../../api/types';

export type TypeChoice = 'company' | 'ip' | 'self_employed';

export interface AreaDraft {
  city_id: string;
  district_ids: string[];
}

export interface ProfileDraft {
  typeChoice: TypeChoice;
  inn: string;
  contactName: string;
  representativePosition: string;
  contactPhone: string;
  contactEmail: string;
  categoryIds: string[];
  areas: AreaDraft[];
  brandsByCategory: Record<string, string>;
  visitTerms: string;
  visitPriceFrom: string;
  canProvideDocuments: boolean;
  description: string;
}

function typeChoiceOf(providerKind: string, legalForm: string | null): TypeChoice {
  if (providerKind === 'independent_specialist') {
    return legalForm === 'self_employed' ? 'self_employed' : 'ip';
  }
  return 'company';
}

export function rubToMinor(value: string): number | null {
  const rub = Number.parseFloat(value.replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(rub) && rub > 0 ? Math.round(rub * 100) : null;
}

export function draftFromProfile(p: ProviderProfile): ProfileDraft {
  const mergedAreas = new Map<string, string[]>();
  for (const a of p.service_areas) {
    const districtIds = mergedAreas.get(a.city_id) ?? [];
    if (a.district_id) districtIds.push(a.district_id);
    mergedAreas.set(a.city_id, districtIds);
  }
  const brandMap: Record<string, string> = {};
  for (const r of p.brand_restrictions) {
    brandMap[r.equipment_category_id] = [brandMap[r.equipment_category_id], r.brand]
      .filter(Boolean)
      .join(', ');
  }
  return {
    typeChoice: typeChoiceOf(p.provider_kind, p.legal_form),
    inn: p.inn ?? '',
    contactName: p.contact_name ?? '',
    representativePosition: p.representative_position ?? '',
    contactPhone: p.contact_phone ?? '',
    contactEmail: p.contact_email ?? '',
    categoryIds: p.categories.map((c) => c.id),
    areas: Array.from(mergedAreas.entries()).map(([city_id, district_ids]) => ({
      city_id,
      district_ids,
    })),
    brandsByCategory: brandMap,
    visitTerms: p.visit_terms ?? '',
    visitPriceFrom: p.visit_price_from_minor ? String(p.visit_price_from_minor / 100) : '',
    canProvideDocuments: p.can_provide_documents,
    description: p.description ?? '',
  };
}

function legalFormOf(d: ProfileDraft): string {
  if (d.typeChoice !== 'company') return d.typeChoice;
  return d.inn.trim().length === 12 ? 'ip' : 'ooo';
}

export function payloadFromDraft(
  d: ProfileDraft,
  editableRequisites: boolean,
): ProviderProfileUpdateInput {
  const requisites: Partial<ProviderProfileUpdateInput> = editableRequisites
    ? {
        provider_kind: d.typeChoice === 'company' ? 'company' : 'independent_specialist',
        legal_form: legalFormOf(d),
        inn: d.inn.trim() || null,
        contact_name: d.contactName.trim() || null,
        representative_position: d.representativePosition.trim() || null,
        contact_phone: d.contactPhone.trim() || null,
        contact_email: d.contactEmail.trim() || null,
      }
    : {};
  return {
    ...requisites,
    visit_terms: d.visitTerms.trim() || null,
    visit_price_from_minor: rubToMinor(d.visitPriceFrom),
    can_provide_documents: d.canProvideDocuments,
    description: d.description.trim() || null,
    category_ids: d.categoryIds,
    service_areas: d.areas,
    brand_restrictions: d.categoryIds
      .filter((id) => (d.brandsByCategory[id] ?? '').trim().length > 0)
      .map((id) => ({
        equipment_category_id: id,
        brands: (d.brandsByCategory[id] ?? '')
          .split(',')
          .map((b) => b.trim())
          .filter(Boolean),
      })),
  };
}
