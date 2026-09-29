import { describe, expect, it } from 'vitest';
import { flattenFeed, mergeFreshPage } from './messageFeed';
import type { Page, RequestMessage } from '../types';

function msg(id: string, body = id): RequestMessage {
  return {
    id,
    request_id: 'r1',
    author_kind: 'customer_membership',
    body,
    created_at: `2026-09-01T10:00:${id.padStart(2, '0')}Z`,
  } as RequestMessage;
}

const page = (ids: string[], next: string | null): Page<RequestMessage> => ({
  items: ids.map((id) => msg(id)),
  next_cursor: next,
});

describe('лента сообщений: страницы от свежих к ранним', () => {
  it('на экране — от старых к новым, повтор на стыке страниц не дублируется', () => {
    const data = { pages: [page(['4', '5'], '4'), page(['2', '3', '4'], null)], pageParams: [null, '4'] };
    expect(flattenFeed(data).map((m) => m.id)).toEqual(['2', '3', '4', '5']);
  });

  it('опрос дописывает новое сообщение и обновляет копии, не трогая подгруженную историю', () => {
    const prev = { pages: [page(['3', '4'], '3'), page(['1', '2'], null)], pageParams: [null, '3'] };
    const fresh = { items: [msg('4', 'доставлено'), msg('5')], next_cursor: '4' };
    const merged = mergeFreshPage(prev, fresh);
    expect(flattenFeed(merged).map((m) => m.id)).toEqual(['1', '2', '3', '4', '5']);
    expect(flattenFeed(merged).find((m) => m.id === '4')?.body).toBe('доставлено');
    expect(merged.pages[1]).toEqual(prev.pages[1]);
    expect(merged.pageParams).toEqual(prev.pageParams);
  });

  it('разрыв (за время опроса пришло больше страницы) — лента начинается заново', () => {
    const prev = { pages: [page(['1', '2'], null)], pageParams: [null] };
    const fresh = page(['8', '9'], '8');
    expect(mergeFreshPage(prev, fresh)).toEqual({ pages: [fresh], pageParams: [null] });
  });
});
