import type { QueryClient, QueryKey } from '@tanstack/react-query';
import { queryKeys } from './queryKeys';

type Scope = string | null;

export function feedPollKey(feedKey: QueryKey): QueryKey {
  return ['message-feed-poll', ...feedKey];
}

export function requestChanged(queryClient: QueryClient, scope: Scope, id: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.request(scope, id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestHistory(scope, id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestOffers(scope, id) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestReview(scope, id) });
  requestListsChanged(queryClient, scope);
}

export function requestListsChanged(queryClient: QueryClient, scope: Scope): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestLists(scope) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.pendingApprovals(scope) });
  void queryClient.invalidateQueries({ queryKey: ['equipment', scope] });
}

export function refreshRequest(queryClient: QueryClient, scope: Scope, id: string): Promise<void> {
  requestListsChanged(queryClient, scope);
  return queryClient.invalidateQueries({
    predicate: ({ queryKey }) => queryKey[0] === 'requests' && queryKey[1] === scope && queryKey[3] === id,
  });
}

export function messagesChanged(queryClient: QueryClient, feedKey: QueryKey, scope: Scope, requestId: string): void {
  void queryClient.invalidateQueries({ queryKey: feedKey, refetchType: 'none' });
  void queryClient.invalidateQueries({ queryKey: feedPollKey(feedKey) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.request(scope, requestId), exact: true });
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestLists(scope) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.pendingApprovals(scope) });
}

export function attachmentsChanged(queryClient: QueryClient, scope: Scope, requestId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.requestAttachments(scope, requestId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.request(scope, requestId), exact: true });
}

export function marketplaceChanged(queryClient: QueryClient, scope: Scope, requestId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.marketplaceCard(scope, requestId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.marketplaceList(scope) });
}

export function equipmentChanged(queryClient: QueryClient, scope: Scope): void {
  void queryClient.invalidateQueries({ queryKey: ['equipment', scope] });
}

export function bindingsChanged(queryClient: QueryClient, scope: Scope): void {
  void queryClient.invalidateQueries({ queryKey: ['service-bindings', scope] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.bindingInvitations(scope) });
  void queryClient.invalidateQueries({
    predicate: ({ queryKey }) =>
      queryKey[0] === 'requests' && queryKey[1] === scope && queryKey[2] === 'equipment-binding',
  });
  equipmentChanged(queryClient, scope);
}

export function reviewsChanged(queryClient: QueryClient, scope: Scope): void {
  void queryClient.invalidateQueries({ queryKey: ['reviews', scope] });
  void queryClient.invalidateQueries({
    predicate: ({ queryKey }) => queryKey[0] === 'providers' && queryKey[2] === 'reviews',
  });
}
