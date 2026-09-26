import {
  useInfiniteQuery,
  type InfiniteData,
  type QueryKey,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { POLL_INTERVAL_MS } from '../queryClient';
import type { Page } from '../types';

export type CursorList<T> = UseInfiniteQueryResult<T[], Error>;

export function flattenPages<T extends { id: string }>(data: InfiniteData<Page<T>, string | null>): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const page of data.pages) {
    for (const item of page.items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      out.push(item);
    }
  }
  return out;
}

export function useCursorList<T extends { id: string }>({
  queryKey,
  fetchPage,
  enabled,
  poll = true,
}: {
  queryKey: QueryKey;
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<Page<T>>;
  enabled: boolean;
  poll?: boolean;
}): CursorList<T> {
  return useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => fetchPage(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    select: flattenPages<T>,
    enabled,
    refetchInterval: (query) =>
      poll && (query.state.data?.pages.length ?? 0) <= 1 ? POLL_INTERVAL_MS : false,
  });
}
