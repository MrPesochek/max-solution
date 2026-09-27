import { equipmentShortName } from '../../requests/components/equipmentName';

interface CardPlace {
  city_name?: string | null;
  district_name?: string | null;
  equipment_category_name?: string | null;
  brand?: string | null;
  model?: string | null;
}

export function cardAreaName(card: CardPlace): string | null {
  return card.district_name ?? card.city_name ?? null;
}

export function cardTitle(card: CardPlace): string {
  return equipmentShortName({
    category: card.equipment_category_name,
    brand: card.brand,
    model: card.model,
  });
}
