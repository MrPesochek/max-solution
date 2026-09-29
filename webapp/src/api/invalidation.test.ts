import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import {
  attachmentsChanged,
  bindingsChanged,
  equipmentChanged,
  feedPollKey,
  marketplaceChanged,
  messagesChanged,
  requestChanged,
  reviewsChanged,
} from './invalidation';
import { queryKeys } from './queryKeys';

const S = 'mem_1';

function seeded() {
  const client = new QueryClient();
  const keys = {
    item: queryKeys.request(S, 'r1'),
    otherItem: queryKeys.request(S, 'r2'),
    history: queryKeys.requestHistory(S, 'r1'),
    messages: queryKeys.requestMessages(S, 'r1'),
    otherMessages: queryKeys.requestMessages(S, 'r2'),
    list: queryKeys.requests(S, { active: true }),
    queue: queryKeys.providerRequests(S, { assignmentState: 'pending' }),
    approvals: queryKeys.pendingApprovals(S),
    attachments: queryKeys.requestAttachments(S, 'r1'),
    equipmentAll: queryKeys.equipment(S, undefined),
    equipmentOldPoint: queryKeys.equipment(S, 'loc_old'),
    equipmentItem: queryKeys.equipmentItem(S, 'eq1'),
    otherScopeItem: queryKeys.request('mem_2', 'r1'),
    marketCard: queryKeys.marketplaceCard(S, 'r1'),
    marketList: queryKeys.marketplaceList(S),
    publicReviews: queryKeys.providerReviews('prov_1'),
    myReviews: queryKeys.myReviews(S),
    bindings: queryKeys.bindings(S, {}),
    poll: feedPollKey(queryKeys.requestMessages(S, 'r1')),
  };
  for (const key of Object.values(keys)) client.setQueryData(key, { seeded: true });
  const stale = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated ?? false;
  return { client, keys, stale };
}

describe('инвалидация по доменам', () => {
  it('действие над заявкой: карточка, история, списки, очереди, решения и сводка техники', () => {
    const { client, keys, stale } = seeded();
    requestChanged(client, S, 'r1');
    for (const key of [keys.item, keys.history, keys.list, keys.queue, keys.approvals, keys.equipmentAll]) {
      expect(stale(key)).toBe(true);
    }
  });

  it('действие над заявкой не трогает чужие карточки, ленты и другую сторону организации', () => {
    const { client, keys, stale } = seeded();
    requestChanged(client, S, 'r1');
    for (const key of [keys.otherItem, keys.messages, keys.otherMessages, keys.otherScopeItem, keys.marketList]) {
      expect(stale(key)).toBe(false);
    }
  });

  it('новое сообщение: лента помечена, свежая страница опрашивается, соседняя лента не тронута', () => {
    const { client, keys, stale } = seeded();
    messagesChanged(client, keys.messages, S, 'r1');
    expect(stale(keys.messages)).toBe(true);
    expect(stale(keys.poll)).toBe(true);
    expect(stale(keys.item)).toBe(true);
    expect(stale(keys.list)).toBe(true);
    expect(stale(keys.otherMessages)).toBe(false);
    expect(stale(keys.history)).toBe(false);
  });

  it('удаление вложения перечитывает и карточку — там лежат превью (регресс)', () => {
    const { client, keys, stale } = seeded();
    attachmentsChanged(client, S, 'r1');
    expect(stale(keys.attachments)).toBe(true);
    expect(stale(keys.item)).toBe(true);
    expect(stale(keys.otherItem)).toBe(false);
  });

  it('ответ на отзыв обновляет публичную ленту по id исполнителя, а не по членству (регресс)', () => {
    const { client, keys, stale } = seeded();
    reviewsChanged(client, S);
    expect(stale(keys.publicReviews)).toBe(true);
    expect(stale(keys.myReviews)).toBe(true);
    expect(stale(keys.item)).toBe(false);
  });

  it('правка техники обновляет все её списки, в том числе старой точки', () => {
    const { client, keys, stale } = seeded();
    equipmentChanged(client, S);
    expect(stale(keys.equipmentAll)).toBe(true);
    expect(stale(keys.equipmentOldPoint)).toBe(true);
    expect(stale(keys.equipmentItem)).toBe(true);
  });

  it('отклик на бирже обновляет и ленту «Доступные» (регресс), принятие приглашения — привязки', () => {
    const { client, keys, stale } = seeded();
    marketplaceChanged(client, S, 'r1');
    expect(stale(keys.marketCard)).toBe(true);
    expect(stale(keys.marketList)).toBe(true);
    bindingsChanged(client, S);
    expect(stale(keys.bindings)).toBe(true);
    expect(stale(keys.equipmentAll)).toBe(true);
  });
});
