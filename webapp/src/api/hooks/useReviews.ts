import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { reviewsChanged } from '../invalidation';
import { queryKeys } from '../queryKeys';
import type {
  MyReview,
  Page,
  ProviderReview,
  PublicReview,
  RequestReviewState,
  ReviewAppealInput,
  ReviewReplyInput,
  ReviewSubmitInput,
} from '../types';

export function useRequestReviewState(requestId: string | undefined, assignmentId?: string) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: [...queryKeys.requestReview(scope, requestId ?? ''), assignmentId ?? 'current'],
    queryFn: () =>
      api.get<RequestReviewState>(`/requests/${requestId}/review`, {
        query: { assignment_id: assignmentId },
      }),
    enabled: Boolean(scope && requestId),
  });
}

export function useSubmitReview(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: ReviewSubmitInput, idempotencyKey) =>
      api.put<MyReview>(`/requests/${requestId}/review`, input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.requestReview(scope, requestId) });
    },
  });
}

export function useReplyToReview() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (
      { reviewId, input }: { reviewId: string; input: ReviewReplyInput },
      idempotencyKey,
    ) => api.post(`/reviews/${reviewId}/reply`, input, { idempotencyKey }),
    onSuccess: () => reviewsChanged(queryClient, scope),
  });
}

export function useAppealReview(onSuccessInvalidate: () => void) {
  return useIdempotentMutation({
    mutationFn: (
      { reviewId, input }: { reviewId: string; input: ReviewAppealInput },
      idempotencyKey,
    ) => api.post(`/reviews/${reviewId}/appeal`, input, { idempotencyKey }),
    onSuccess: onSuccessInvalidate,
  });
}

const REVIEWS_PAGE_SIZE = 10;

export function useProviderReviewsInfinite(providerId: string | undefined) {
  return useInfiniteQuery({
    queryKey: queryKeys.providerReviews(providerId ?? ''),
    queryFn: ({ pageParam }) =>
      api.get<Page<PublicReview>>(`/providers/${providerId}/reviews`, {
        withoutOrganization: true,
        query: { cursor: pageParam ?? undefined, limit: REVIEWS_PAGE_SIZE },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(providerId),
  });
}

export function useMyReviews(enabled = true) {
  const scope = getActiveScope();
  return useInfiniteQuery({
    queryKey: queryKeys.myReviews(scope),
    queryFn: ({ pageParam }) =>
      api.get<Page<ProviderReview>>('/reviews/mine', {
        query: { cursor: pageParam ?? undefined, limit: 20 },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(scope) && enabled,
  });
}
