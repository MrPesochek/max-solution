import { useQuery } from '@tanstack/react-query';
import { api } from '../client';
import { queryKeys } from '../queryKeys';
import type { Page, ProviderCatalogItem, ProviderCount, ProviderPublicProfile } from '../types';

export interface ProviderCatalogFilters {
  categoryId?: string;
  cityId?: string;
  districtId?: string;
}

export function useProvidersCatalog(filters: ProviderCatalogFilters) {
  return useQuery({
    queryKey: queryKeys.providersCatalog(filters),
    queryFn: async () =>
      (
        await api.get<Page<ProviderCatalogItem>>('/providers', {
          withoutOrganization: true,
          query: {
            category_id: filters.categoryId,
            city_id: filters.cityId,
            district_id: filters.districtId,
          },
        })
      ).items,
  });
}

export function useProviderPublicProfile(providerId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.providerPublic(providerId ?? ''),
    queryFn: () =>
      api.get<ProviderPublicProfile>(`/providers/${providerId}`, { withoutOrganization: true }),
    enabled: Boolean(providerId),
  });
}

export function providerSearchReady(query: string): boolean {
  const q = query.trim();
  return /^[\d\s]+$/.test(q) ? q.replace(/\s/g, '').length >= 10 : q.length >= 3;
}

export function useProviderSearch(query: string) {
  const q = query.trim();
  return useQuery({
    queryKey: queryKeys.providerSearch(q),
    queryFn: async () =>
      (
        await api.get<Page<ProviderCatalogItem>>('/providers', {
          withoutOrganization: true,
          query: { q, limit: 20 },
        })
      ).items,
    enabled: providerSearchReady(q),
  });
}

export function useProvidersCount(filters: ProviderCatalogFilters, enabled = true) {
  return useQuery({
    queryKey: queryKeys.providersCount(filters),
    queryFn: async () =>
      (
        await api.get<ProviderCount>('/providers/count', {
          withoutOrganization: true,
          query: {
            category_id: filters.categoryId,
            city_id: filters.cityId,
            district_id: filters.districtId,
          },
        })
      ).count,
    enabled,
  });
}
