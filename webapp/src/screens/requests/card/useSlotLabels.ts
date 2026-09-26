import { useMemo } from 'react';
import { useEquipmentCategories } from '../../../api/hooks/useDirectories';

export function useSlotLabels(categoryId: string | null | undefined): Record<string, string> {
  const categories = useEquipmentCategories();
  return useMemo(() => {
    const category = categories.data?.find((c) => c.id === categoryId);
    return Object.fromEntries((category?.photo_template ?? []).map((slot) => [slot.code, slot.label]));
  }, [categories.data, categoryId]);
}
