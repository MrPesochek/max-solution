import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type { Complaint, ComplaintCreateInput, Page } from '../types';

const PAGE_SIZE = 20;

export function useMyComplaints() {
  const scope = getActiveScope();
  return useInfiniteQuery({
    queryKey: queryKeys.myComplaints(scope),
    queryFn: ({ pageParam }) =>
      api.get<Page<Complaint>>('/complaints', {
        query: { cursor: pageParam ?? undefined, limit: PAGE_SIZE },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    enabled: Boolean(scope),
  });
}

export function useCreateComplaint() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: ComplaintCreateInput, idempotencyKey) =>
      api.post<Complaint>('/complaints', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myComplaints(scope) });
    },
  });
}

export function useWithdrawComplaint() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (complaintId: string, idempotencyKey) =>
      api.post<Complaint>(`/complaints/${complaintId}/withdraw`, undefined, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.myComplaints(scope) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.myReviews(scope) });
    },
  });
}
