import { useEffect } from 'react';
import {
  useInfiniteQuery,
  useQueries,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryKey,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api, apiPath } from '../client';
import { feedPollKey } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import type { Page, RequestMessage } from '../types';

export const MESSAGE_PAGE_SIZE = 50;

type FeedData = InfiniteData<Page<RequestMessage>, string | null>;

export type MessageFeed = UseInfiniteQueryResult<RequestMessage[], Error>;

export type FeedPath = () => string;

async function fetchPage(path: FeedPath, cursor: string | null, signal?: AbortSignal, limit = MESSAGE_PAGE_SIZE) {
  return api.get<Page<RequestMessage>>(path(), {
    query: { direction: 'backward', cursor: cursor ?? undefined, limit },
    signal,
  });
}

export function flattenFeed(data: FeedData): RequestMessage[] {
  const seen = new Set<string>();
  const out: RequestMessage[] = [];
  for (let i = data.pages.length - 1; i >= 0; i -= 1) {
    for (const message of data.pages[i]!.items) {
      if (seen.has(message.id)) continue;
      seen.add(message.id);
      out.push(message);
    }
  }
  return out;
}

export function mergeFreshPage(prev: FeedData | undefined, fresh: Page<RequestMessage>): FeedData {
  const restart: FeedData = { pages: [fresh], pageParams: [null] };
  if (!prev || prev.pages.length === 0) return restart;
  const known = new Set(prev.pages.flatMap((page) => page.items.map((m) => m.id)));
  const overlaps = fresh.items.some((m) => known.has(m.id));
  if (!overlaps && fresh.next_cursor && known.size > 0) return restart;
  const freshIds = new Set(fresh.items.map((m) => m.id));
  const [first, ...rest] = prev.pages;
  return {
    pages: [
      { items: [...first!.items.filter((m) => !freshIds.has(m.id)), ...fresh.items], next_cursor: first!.next_cursor },
      ...rest.map((page) => ({ ...page, items: page.items.filter((m) => !freshIds.has(m.id)) })),
    ],
    pageParams: prev.pageParams,
  };
}

export function useMessageFeed(
  feedKey: QueryKey,
  path: FeedPath | null,
  { enabled, poll = true }: { enabled: boolean; poll?: boolean },
): MessageFeed {
  const queryClient = useQueryClient();
  const active = Boolean(path) && enabled;

  const feed = useInfiniteQuery({
    queryKey: feedKey,
    queryFn: ({ pageParam, signal }) => fetchPage(path!, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    select: flattenFeed,
    enabled: active,
  });

  const fresh = useQuery({
    queryKey: feedPollKey(feedKey),
    queryFn: ({ signal }) => fetchPage(path!, null, signal),
    enabled: active && feed.isSuccess,
    refetchInterval: poll ? POLL_INTERVAL_MS : false,
    initialData: () => queryClient.getQueryData<FeedData>(feedKey)?.pages[0],
    initialDataUpdatedAt: () => queryClient.getQueryState(feedKey)?.dataUpdatedAt,
  });

  useEffect(() => {
    if (!fresh.data || !active) return;
    const page = fresh.data;
    queryClient.setQueryData<FeedData>(feedKey, (prev) => (prev ? mergeFreshPage(prev, page) : prev));
    // feedKey — новый массив на каждом рендере; сравниваем по времени обновления данных.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fresh.dataUpdatedAt, active]);

  return feed;
}

export function fetchLatestMessage(path: FeedPath, signal?: AbortSignal): Promise<RequestMessage | null> {
  return fetchPage(path, null, signal, 1).then((page) => page.items[page.items.length - 1] ?? null);
}

export interface PreviewSource {
  kind: 'request' | 'marketplace';
  requestId: string;
}

export function useMessagePreviews(sources: readonly PreviewSource[]) {
  const scope = getActiveScope();
  return useQueries({
    queries: sources.map((source) => ({
      queryKey: [
        ...(source.kind === 'request'
          ? queryKeys.requestMessages(scope, source.requestId)
          : queryKeys.marketplaceMessages(scope, source.requestId)),
        'preview',
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        fetchLatestMessage(
          source.kind === 'request'
            ? () => apiPath`/requests/${source.requestId}/messages`
            : () => apiPath`/marketplace/requests/${source.requestId}/messages`,
          signal,
        ),
      enabled: Boolean(scope),
    })),
  });
}
