import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiGet, apiPath, type GetResponse } from '../client';
import { messagesChanged, refreshRequest, requestChanged, requestListsChanged } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import { useCursorList, type CursorList } from './cursorList';
import { useMessageFeed, type MessageFeed } from './messageFeed';
import type {
  CancellationIdInput,
  CancellationInput,
  FollowupInput,
  MessageInput,
  MessagesRead,
  Page,
  PublicCardInput,
  PublicCardPreviewInput,
  PublicCardPreview,
  QuoteDecisionInput,
  RejectCompletionInput,
  RequestCustomer,
  RequestDraftCreateInput,
  RequestDraftUpdateInput,
  RequestEvent,
  RequestFormerProvider,
  RequestListItem,
  RequestMessage,
  RequestProvider,
  RequestRoute,
  RequestStatus,
  SelectOfferInput,
  ServiceBinding,
  SubmitToOwnServiceInput,
  UpdateDetailsInput,
  VisitDecisionInput,
} from '../types';

type RequestView = RequestCustomer | RequestProvider | RequestFormerProvider;

export interface RequestListFilters {
  status?: RequestStatus[];
  locationId?: string;
  equipmentId?: string;
  active?: boolean;
}

const LIST_PAGE_SIZE = 20;

export function useRequestsList(filters: RequestListFilters = {}): CursorList<RequestListItem> {
  const scope = getActiveScope();
  const key: Record<string, unknown> = {
    status: filters.status ?? null,
    locationId: filters.locationId ?? null,
    equipmentId: filters.equipmentId ?? null,
    active: filters.active ?? null,
  };
  return useCursorList<RequestListItem>({
    queryKey: queryKeys.requests(scope, key),
    fetchPage: (cursor, signal) =>
      api.get<Page<RequestListItem>>('/requests', {
        query: {
          status: filters.status,
          location_id: filters.locationId,
          equipment_id: filters.equipmentId,
          active: filters.active,
          cursor,
          limit: LIST_PAGE_SIZE,
        },
        signal,
      }),
    enabled: Boolean(scope),
  });
}

export function useActiveRequests() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.requests(scope, { active: true, home: true }),
    queryFn: async ({ signal }) =>
      (await api.get<Page<RequestListItem>>('/requests', { query: { active: true, limit: 30 }, signal }))
        .items,
    enabled: Boolean(scope),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useRequest(id: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.request(scope, id ?? ''),
    queryFn: ({ signal }) => api.get<RequestView>(apiPath`/requests/${id!}`, { signal }),
    enabled: Boolean(scope && id),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

const HISTORY_MAX_PAGES = 10;

export function useRequestHistory(id: string | undefined, enabled: boolean) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.requestHistory(scope, id ?? ''),
    queryFn: async ({ signal }) => {
      const events: RequestEvent[] = [];
      let cursor: string | null = null;
      for (let page = 0; page < HISTORY_MAX_PAGES; page += 1) {
        const result: GetResponse<'/requests/{request_id}/history'> = await apiGet('/requests/{request_id}/history', {
          path: { request_id: id! },
          query: { cursor, limit: 100 },
          signal,
        });
        events.push(...result.items);
        cursor = result.next_cursor ?? null;
        if (!cursor) break;
      }
      return events;
    },
    enabled: Boolean(scope && id && enabled),
  });
}

export function useRequestMessages(
  id: string | undefined,
  enabled: boolean,
  options: { poll?: boolean } = {},
): MessageFeed {
  const scope = getActiveScope();
  return useMessageFeed(
    queryKeys.requestMessages(scope, id ?? ''),
    scope && id ? () => apiPath`/requests/${id}/messages` : null,
    { enabled, poll: options.poll },
  );
}

export function useRefreshRequest(id: string | undefined) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useCallback(async () => {
    if (!id) return;
    await refreshRequest(queryClient, scope, id);
  }, [queryClient, scope, id]);
}

export function useEquipmentServiceBinding(equipmentId: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.equipmentBinding(scope, equipmentId ?? ''),
    queryFn: async () =>
      (
        await api.get<Page<ServiceBinding>>('/service-bindings', {
          query: { equipment_id: equipmentId, status: 'confirmed' },
        })
      ).items[0] ?? null,
    enabled: Boolean(scope && equipmentId),
  });
}

export function useCreateDraft() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: RequestDraftCreateInput, idempotencyKey) =>
      api.post<RequestCustomer>('/requests', input, { idempotencyKey }),
    onSuccess: () => requestListsChanged(queryClient, scope),
  });
}

export function useUpdateDraft(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: RequestDraftUpdateInput, idempotencyKey) =>
      api.patch<RequestCustomer>(apiPath`/requests/${id}`, input, { idempotencyKey }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

interface VersionedInput {
  expected_version: number;
}

function makeAction<TInput = void>(path: string) {
  return function useRequestAction(id: string) {
    const queryClient = useQueryClient();
    const scope = getActiveScope();
    return useIdempotentMutation({
      mutationFn: (input: TInput, idempotencyKey) =>
        api.post<RequestCustomer>(apiPath`/requests/${id}/actions/${path}`, input ?? {}, {
          idempotencyKey,
        }),
      onSuccess: () => requestChanged(queryClient, scope, id),
    });
  };
}

export const useSubmitToOwnService = makeAction<SubmitToOwnServiceInput>('submit-to-own-service');
export const useRequestApproval = makeAction<{ comment?: string | null } & VersionedInput>(
  'request-approval',
);
export const useReturnToDraft = makeAction<{ comment: string } & VersionedInput>('return-to-draft');
export const useCancelDraft = makeAction<{ reason?: string | null } & VersionedInput>(
  'cancel-draft',
);
export const useRevokeAssignment = makeAction<
  { assignment_id: string; reason?: string | null } & VersionedInput
>('revoke-assignment');
export const usePublishSearch = makeAction<PublicCardInput>('publish-search');
export const useRequestCancellation = makeAction<CancellationInput>('request-cancellation');
export const useWithdrawCancellation = makeAction<CancellationIdInput>('withdraw-cancellation');
export const useForceCancellation = makeAction<CancellationIdInput>('force-cancellation');
export const useConfirmCompletion = makeAction<VersionedInput>('confirm-completion');
export const useRejectCompletion = makeAction<RejectCompletionInput>('reject-completion');
export const useUpdateDetails = makeAction<UpdateDetailsInput>('update-details');

export function useCreateFollowup() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: ({ id, input }: { id: string; input: FollowupInput }, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/create-followup`, input, {
        idempotencyKey,
      }),
    onSuccess: (_, { id }) => requestChanged(queryClient, scope, id),
  });
}

export function usePreviewPublicCard() {
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: PublicCardPreviewInput }) =>
      api.post<PublicCardPreview>(apiPath`/requests/${id}/actions/preview-public-card`, input),
  });
}

export function useSelectOffer(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: SelectOfferInput, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/select-offer`, input, { idempotencyKey }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

export function useApproveVisitProposal(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: VisitDecisionInput, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/approve-visit-proposal`, input, {
        idempotencyKey,
      }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

export function useRejectVisitProposal(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: VisitDecisionInput, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/reject-visit-proposal`, input, {
        idempotencyKey,
      }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

export function useApproveRepairQuote(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: QuoteDecisionInput, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/approve-repair-quote`, input, {
        idempotencyKey,
      }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

export function useRejectRepairQuote(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: QuoteDecisionInput, idempotencyKey) =>
      api.post<RequestCustomer>(apiPath`/requests/${id}/actions/reject-repair-quote`, input, {
        idempotencyKey,
      }),
    onSuccess: () => requestChanged(queryClient, scope, id),
  });
}

export function usePostMessage(id: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: MessageInput, idempotencyKey) =>
      api.post<RequestMessage>(apiPath`/requests/${id}/messages`, input, { idempotencyKey }),
    onSuccess: () => messagesChanged(queryClient, queryKeys.requestMessages(scope, id), scope, id),
  });
}

export function useMarkMessagesRead(id: string | undefined) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useMutation({
    mutationFn: () => api.post<MessagesRead>(apiPath`/requests/${id!}/messages/read`, {}),
    onSuccess: (result) => {
      if (!id) return;
      queryClient.setQueryData<RequestView>(queryKeys.request(scope, id), (prev) =>
        prev && 'status' in prev ? { ...prev, unread_messages_count: result.unread_messages_count } : prev,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.request(scope, id), exact: true });
    },
  });
}

export type { RequestRoute };
