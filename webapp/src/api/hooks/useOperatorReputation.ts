import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { operatorApi } from '../client';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import type {
  CaseDecisionInput,
  FraudFlagInput,
  ModerationCaseOperator,
  OperatorPage,
  ReviewDecisionInput,
  ReviewOperator,
} from '../operatorTypes';

const reviewsKey = queryKeys.operatorReviews;
const casesKey = queryKeys.operatorModerationCases;

export function useOperatorReviewQueue(status: string) {
  return useQuery({
    queryKey: reviewsKey(status),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<ReviewOperator>>('/reviews', {
          query: { status, limit: 50 },
        })
      ).items,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useDecideReview(reviewId: string, status: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: ReviewDecisionInput, idempotencyKey) =>
      operatorApi.post(`/reviews/${reviewId}/decision`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: reviewsKey(status) }),
  });
}

export function useSetReviewFraudFlag(reviewId: string, status: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: FraudFlagInput, idempotencyKey) =>
      operatorApi.post(`/reviews/${reviewId}/fraud`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: reviewsKey(status) }),
  });
}

export function useOperatorModerationCases(subjectType: string, status: string, kind?: string) {
  return useQuery({
    queryKey: casesKey(subjectType, status, kind),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<ModerationCaseOperator>>('/moderation-cases', {
          query: {
            subject_type: subjectType === 'all' ? undefined : subjectType,
            status,
            kind,
            limit: 50,
          },
        })
      ).items,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useDecideModerationCase(caseId: string, subjectType: string, status: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: CaseDecisionInput, idempotencyKey) =>
      operatorApi.post(`/moderation-cases/${caseId}/decision`, input, { idempotencyKey }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: casesKey(subjectType, status) }),
  });
}
