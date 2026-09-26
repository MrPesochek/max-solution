import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { operatorApi } from '../client';
import { queryKeys } from '../queryKeys';
import type { OperatorBinding, OperatorPage, RevokeInput } from '../operatorTypes';

export function useOperatorBindings(status?: string) {
  return useQuery({
    queryKey: queryKeys.operatorBindings(status),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<OperatorBinding>>('/service-bindings', {
          query: { status, limit: 100 },
        })
      ).items,
  });
}

export function useRevokeOperatorBinding(bindingId: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: RevokeInput, idempotencyKey) =>
      operatorApi.post(`/service-bindings/${bindingId}/revoke`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.operatorBindingsAll }),
  });
}
