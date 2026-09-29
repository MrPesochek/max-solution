import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { server } from '../../mocks/server';
import { feedPollKey } from '../invalidation';
import { setActiveContext } from '../orgStore';
import { useCursorList } from './cursorList';
import { useMessageFeed } from './messageFeed';
import { api } from '../client';
import type { Page } from '../types';

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, Wrapper };
}

const msg = (n: number) => ({
  id: `m${String(n).padStart(3, '0')}`,
  request_id: 'r1',
  author_kind: 'customer_membership',
  body: `Сообщение ${n}`,
  created_at: new Date(Date.UTC(2026, 8, 1, 10, 0, n)).toISOString(),
});

describe('ленты с курсором', () => {
  it('переписка длиннее страницы: сначала свежие, «ранние» догружаются, новое приходит опросом', async () => {
    setActiveContext({ membershipId: 'mem_1', organizationId: 'org_1' });
    let messages = Array.from({ length: 130 }, (_, i) => msg(i));
    server.use(
      http.get('/app-api/v1/__feed/messages', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get('direction')).toBe('backward');
        const cursor = url.searchParams.get('cursor');
        const end = cursor ? messages.findIndex((m) => m.id === cursor) : messages.length;
        const start = Math.max(0, end - 50);
        return HttpResponse.json({ items: messages.slice(start, end), next_cursor: start > 0 ? messages[start]!.id : null });
      }),
    );
    const { client, Wrapper } = wrapper();
    const key = ['requests', 'mem_1', 'messages', 'r1'];
    const { result } = renderHook(() => useMessageFeed(key, () => '/__feed/messages', { enabled: true, poll: false }), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.at(-1)?.body).toBe('Сообщение 129');
    expect(result.current.data).toHaveLength(50);
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    await act(() => result.current.fetchNextPage());
    expect(result.current.data).toHaveLength(130);
    expect(result.current.data?.[0]?.body).toBe('Сообщение 0');
    expect(result.current.hasNextPage).toBe(false);

    messages = [...messages, msg(130)];
    await act(() => client.invalidateQueries({ queryKey: feedPollKey(key) }));
    await waitFor(() => expect(result.current.data).toHaveLength(131));
    const ids = result.current.data!.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.at(-1)).toBe('m130');
  });

  it('опрос списка после «Показать ещё» не дублирует строки (регресс quality-webapp-03)', async () => {
    let version = 0;
    server.use(
      http.get('/app-api/v1/__list', ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        const page: Page<{ id: string; v: number }> = cursor
          ? { items: [{ id: 'c', v: version }, { id: 'd', v: version }], next_cursor: null }
          : { items: [{ id: 'a', v: version }, { id: 'b', v: version }], next_cursor: 'b' };
        return HttpResponse.json(page);
      }),
    );
    const { Wrapper } = wrapper();
    const { result } = renderHook(
      () =>
        useCursorList<{ id: string; v: number }>({
          queryKey: ['__list'],
          fetchPage: (cursor, signal) =>
            api.get<Page<{ id: string; v: number }>>('/__list', { query: { cursor }, signal }),
          enabled: true,
        }),
      { wrapper: Wrapper },
    );
    await waitFor(() => expect(result.current.data).toHaveLength(2));
    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.data?.map((r) => r.id)).toEqual(['a', 'b', 'c', 'd']));
    version = 1;
    await act(() => result.current.refetch());
    await act(() => result.current.refetch());
    expect(result.current.data?.map((r) => r.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(result.current.data?.every((r) => r.v === 1)).toBe(true);
  });
});
