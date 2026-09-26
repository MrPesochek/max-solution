import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type { Location, LocationInput, LocationUpdateInput, Page } from '../types';

export function useLocations() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.locations(scope),
    queryFn: async () => (await api.get<Page<Location>>('/locations')).items,
    enabled: Boolean(scope),
  });
}

export function useLocation(id: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.location(scope, id ?? ''),
    queryFn: () => api.get<Location>(`/locations/${id}`),
    enabled: Boolean(scope && id),
  });
}

export function useCreateLocation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: LocationInput, idempotencyKey) =>
      api.post<Location>('/locations', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.locations(scope) });
    },
  });
}

export function useUpdateLocation(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: LocationUpdateInput, idempotencyKey) =>
      api.patch<Location>(`/locations/${id}`, input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.locations(scope) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.location(scope, id) });
    },
  });
}
