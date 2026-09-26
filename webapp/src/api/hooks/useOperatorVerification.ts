import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, operatorApi } from '../client';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import type {
  OperatorPage,
  VerificationCaseOperator,
  VerificationDecisionInput,
} from '../operatorTypes';

export function useVerificationQueue(demo = false) {
  return useQuery({
    queryKey: demo ? ['showcase-verification'] : queryKeys.operatorVerificationQueue,
    queryFn: async () =>
      (
        await (demo ? api : operatorApi).get<OperatorPage<VerificationCaseOperator>>(
          demo ? '/showcase/verification-cases' : '/verification-cases', {
            withoutOrganization: demo,
            query: demo ? { limit: 100 } : { decision: 'pending', limit: 50 },
          })
      ).items,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useDecideVerificationCase(id: string, demo = false) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: VerificationDecisionInput, idempotencyKey) =>
      (demo ? api : operatorApi).post(`${demo ? '/showcase' : ''}/verification-cases/${id}/decision`, input, { idempotencyKey, withoutOrganization: demo }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: demo ? ['showcase-verification'] : queryKeys.operatorVerificationQueue }),
  });
}
