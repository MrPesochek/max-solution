import { useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiPath } from '../client';
import { requestChanged } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import { useCursorList, type CursorList } from './cursorList';
import type {
  AssignmentAcceptInput,
  AssignmentCancellationResponseInput,
  AssignmentDeclineInput,
  AssignmentFieldWorkerInput,
  AssignmentMarkEnRouteInput,
  AssignmentProposeVisitInput,
  AssignmentReportCompletionInput,
  AssignmentRepairQuoteInput,
  AssignmentStartWorkInput,
  AssignmentWarrantyDecisionInput,
  AssignmentWithdrawInput,
  Page,
  RequestListItem,
  RequestProvider,
} from '../types';

const QUEUE_PAGE_SIZE = 50;

function useProviderQueue(state: 'pending' | 'accepted', { poll = true }: { poll?: boolean }) {
  const scope = getActiveScope();
  return useCursorList<RequestListItem>({
    queryKey: queryKeys.providerRequests(scope, { assignmentState: state }),
    fetchPage: (cursor, signal) =>
      api.get<Page<RequestListItem>>('/requests', {
        query: { assignment_state: [state], cursor, limit: QUEUE_PAGE_SIZE },
        signal,
      }),
    enabled: Boolean(scope),
    poll,
  });
}

export function useProviderIncoming(options: { poll?: boolean } = {}): CursorList<RequestListItem> {
  return useProviderQueue('pending', options);
}

export function useProviderInWork(options: { poll?: boolean } = {}): CursorList<RequestListItem> {
  return useProviderQueue('accepted', options);
}

export function isProviderView(data: unknown): data is RequestProvider {
  return Boolean(data) && typeof data === 'object' && 'contacts_disclosed' in (data as object);
}

function makeAssignmentAction<TInput>(path: string) {
  return function useAssignmentAction(id: string) {
    const queryClient = useQueryClient();
    const scope = getActiveScope();
    return useIdempotentMutation({
      mutationFn: (input: TInput, idempotencyKey) =>
        api.post<RequestProvider>(apiPath`/requests/${id}/actions/${path}`, input, { idempotencyKey }),
      onSuccess: () => requestChanged(queryClient, scope, id),
    });
  };
}

export const useAcceptAssignment = makeAssignmentAction<AssignmentAcceptInput>('accept');
export const useDeclineAssignment = makeAssignmentAction<AssignmentDeclineInput>('decline');
export const useWithdrawAssignment = makeAssignmentAction<AssignmentWithdrawInput>('withdraw');
export const useProposeVisit = makeAssignmentAction<AssignmentProposeVisitInput>('propose-visit');
export const useCreateRepairQuote =
  makeAssignmentAction<AssignmentRepairQuoteInput>('create-repair-quote');
export const useStartWork = makeAssignmentAction<AssignmentStartWorkInput>('start-work');
export const useMarkEnRoute = makeAssignmentAction<AssignmentMarkEnRouteInput>('mark-en-route');
export const useReportCompletion =
  makeAssignmentAction<AssignmentReportCompletionInput>('report-completion');
export const useRespondToCancellation =
  makeAssignmentAction<AssignmentCancellationResponseInput>('respond-cancellation');
export const useProviderWarrantyDecision =
  makeAssignmentAction<AssignmentWarrantyDecisionInput>('warranty-decision');
export const useSetFieldWorker = makeAssignmentAction<AssignmentFieldWorkerInput>('field-worker');
