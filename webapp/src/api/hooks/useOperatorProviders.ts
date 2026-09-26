import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { operatorApi } from '../client';
import { queryKeys } from '../queryKeys';
import type { OperatorPage, OperatorProviderProfile, ProfileStatusInput } from '../operatorTypes';

export function useOperatorProviderProfiles(status?: string) {
  return useQuery({
    queryKey: queryKeys.operatorProviders(status),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<OperatorProviderProfile>>('/provider-profiles', {
          query: { status, limit: 50 },
        })
      ).items,
  });
}

export function useSuspendProvider(organizationId: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: ProfileStatusInput, idempotencyKey) =>
      operatorApi.post(`/provider-profiles/${organizationId}/suspend`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.operatorProvidersAll }),
  });
}

export function useReinstateProvider(organizationId: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: ProfileStatusInput, idempotencyKey) =>
      operatorApi.post(`/provider-profiles/${organizationId}/reinstate`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.operatorProvidersAll }),
  });
}
