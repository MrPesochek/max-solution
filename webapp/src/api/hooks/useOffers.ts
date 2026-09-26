import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiPath } from '../client';
import { messagesChanged } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import type { DialogMessageInput, Offer, RequestMessage } from '../types';
import { useMessageFeed, type MessageFeed } from './messageFeed';

export function useRequestOffers(requestId: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.requestOffers(scope, requestId ?? ''),
    queryFn: ({ signal }) => api.get<Offer[]>(apiPath`/requests/${requestId!}/offers`, { signal }),
    enabled: Boolean(scope && requestId),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useOfferMessages(requestId: string | undefined, offerId: string | undefined): MessageFeed {
  const scope = getActiveScope();
  return useMessageFeed(
    queryKeys.offerMessages(scope, requestId ?? '', offerId ?? ''),
    scope && requestId && offerId ? () => apiPath`/requests/${requestId}/offers/${offerId}/messages` : null,
    { enabled: true },
  );
}

export function usePostOfferMessage(requestId: string, offerId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: DialogMessageInput, idempotencyKey) =>
      api.post<RequestMessage>(apiPath`/requests/${requestId}/offers/${offerId}/messages`, input, { idempotencyKey }),
    onSuccess: () =>
      messagesChanged(queryClient, queryKeys.offerMessages(scope, requestId, offerId), scope, requestId),
  });
}
