import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiPath } from '../client';
import { marketplaceChanged, messagesChanged } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import { useMessageFeed, type MessageFeed } from './messageFeed';
import type {
  DialogMessageInput,
  MarketplaceCard,
  MarketplaceListItem,
  MarketplaceOfferInput,
  MarketplaceOfferWithdrawInput,
  Offer,
  Page,
  RequestMessage,
} from '../types';

function marketplaceListQuery(scope: ReturnType<typeof getActiveScope>) {
  return {
    queryKey: queryKeys.marketplaceList(scope),
    queryFn: () =>
      api.get<Page<MarketplaceListItem>>('/marketplace/requests', { query: { limit: 50 } }),
    enabled: Boolean(scope),
    refetchInterval: POLL_INTERVAL_MS,
  };
}

export function useMarketplaceList() {
  const scope = getActiveScope();
  return useQuery({ ...marketplaceListQuery(scope), select: (page) => page.items });
}

export function useMarketplaceHasMore(): boolean {
  const scope = getActiveScope();
  return useQuery({ ...marketplaceListQuery(scope), select: (page) => Boolean(page.next_cursor) })
    .data ?? false;
}

export function useMarketplaceCard(id: string | undefined) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.marketplaceCard(scope, id ?? ''),
    queryFn: ({ signal }) => api.get<MarketplaceCard>(apiPath`/marketplace/requests/${id!}`, { signal }),
    enabled: Boolean(scope && id),
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useSubmitOffer(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: MarketplaceOfferInput, idempotencyKey) =>
      api.post<Offer>(apiPath`/marketplace/requests/${requestId}/offers`, input, { idempotencyKey }),
    onSuccess: () => marketplaceChanged(queryClient, scope, requestId),
  });
}

export function useWithdrawOffer(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (
      { offerId, input }: { offerId: string; input: MarketplaceOfferWithdrawInput },
      idempotencyKey,
    ) => api.post<Offer>(apiPath`/offers/${offerId}/withdraw`, input, { idempotencyKey }),
    onSuccess: () => marketplaceChanged(queryClient, scope, requestId),
  });
}

export function useMarketplaceMessages(requestId: string | undefined, enabled = true): MessageFeed {
  const scope = getActiveScope();
  return useMessageFeed(
    queryKeys.marketplaceMessages(scope, requestId ?? ''),
    scope && requestId ? () => apiPath`/marketplace/requests/${requestId}/messages` : null,
    { enabled },
  );
}

export function usePostMarketplaceMessage(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: DialogMessageInput, idempotencyKey) =>
      api.post<RequestMessage>(apiPath`/marketplace/requests/${requestId}/messages`, input, { idempotencyKey }),
    onSuccess: () => {
      messagesChanged(queryClient, queryKeys.marketplaceMessages(scope, requestId), scope, requestId);
      marketplaceChanged(queryClient, scope, requestId);
    },
  });
}
