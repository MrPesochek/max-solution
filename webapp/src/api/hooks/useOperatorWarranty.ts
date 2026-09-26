import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { operatorApi } from '../client';
import { queryKeys } from '../queryKeys';
import type {
  OperatorPage,
  OperatorWarrantyAuthorization,
  RevokeInput,
  WarrantyAuthorizationInput,
} from '../operatorTypes';

export function useOperatorWarrantyAuthorizations(providerOrganizationId?: string) {
  return useQuery({
    queryKey: queryKeys.operatorWarranty(providerOrganizationId),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<OperatorWarrantyAuthorization>>(
          '/warranty-authorizations',
          {
            query: { provider_organization_id: providerOrganizationId, limit: 100 },
          },
        )
      ).items,
  });
}

export function useCreateWarrantyAuthorization() {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: WarrantyAuthorizationInput, idempotencyKey) =>
      operatorApi.post('/warranty-authorizations', input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.operatorWarrantyAll }),
  });
}

export function useRevokeWarrantyAuthorization(authorizationId: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: RevokeInput, idempotencyKey) =>
      operatorApi.post(`/warranty-authorizations/${authorizationId}/revoke`, input, {
        idempotencyKey,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.operatorWarrantyAll }),
  });
}
