import { strings } from '../../../strings/ru';

interface EquipmentNameParts {
  category?: string | null;
  brand?: string | null;
  model?: string | null;
}

export function equipmentShortName({ category, brand, model }: EquipmentNameParts): string {
  const kind = category?.trim() ?? '';
  const maker = brand?.trim() ?? '';
  if (kind && maker) return `${strings.requests.categoryShort[kind] ?? kind} ${maker}`;
  if (kind) return kind;
  return [maker, model?.trim()].filter(Boolean).join(' ') || strings.common.notSpecified;
}

export function equipmentFullName(parts: EquipmentNameParts): string {
  const model = parts.model?.trim();
  const base = equipmentShortName({ ...parts, model: null });
  const hasBase = Boolean(parts.category?.trim() || parts.brand?.trim());
  if (!hasBase) return model || strings.common.notSpecified;
  return model ? `${base} ${model}` : base;
}

export function equipmentTitle(
  item: { category_name?: string | null; brand?: string | null; model?: string | null } | null | undefined,
): string {
  if (!item) return strings.common.notSpecified;
  return equipmentFullName({ category: item.category_name, brand: item.brand, model: item.model });
}

export function listItemEquipmentName(item: {
  equipment_category_name?: string | null;
  equipment_brand?: string | null;
  equipment_model?: string | null;
  equipment_title?: string | null;
}): string {
  if (!item.equipment_category_name && !item.equipment_brand && !item.equipment_model) {
    return item.equipment_title || strings.common.notSpecified;
  }
  return equipmentFullName({
    category: item.equipment_category_name,
    brand: item.equipment_brand,
    model: item.equipment_model,
  });
}

export function requestEquipmentFullName(request: {
  equipment_category_name?: string | null;
  equipment: { category_name?: string | null; brand?: string | null; model?: string | null };
}): string {
  return equipmentFullName({
    category: request.equipment_category_name ?? request.equipment.category_name,
    brand: request.equipment.brand,
    model: request.equipment.model,
  });
}
