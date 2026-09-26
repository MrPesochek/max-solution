import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import { queryKeys } from '../queryKeys';
import type { City, EquipmentCategory, Page } from '../types';

export function useCities() {
  return useQuery({
    queryKey: queryKeys.cities,
    queryFn: async () =>
      (await api.get<Page<City>>('/directories/cities', { withoutOrganization: true })).items,
    staleTime: 5 * 60_000,
  });
}

export function useEquipmentCategories() {
  return useQuery({
    queryKey: queryKeys.equipmentCategories,
    queryFn: async () =>
      (
        await api.get<Page<EquipmentCategory>>('/directories/equipment-categories', {
          withoutOrganization: true,
        })
      ).items,
    staleTime: 5 * 60_000,
  });
}
