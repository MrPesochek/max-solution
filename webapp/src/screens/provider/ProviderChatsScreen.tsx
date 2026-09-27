import { strings } from '../../strings/ru';
import { useMessagePreviews } from '../../api/hooks/messageFeed';
import { useProviderIncoming, useProviderInWork } from '../../api/hooks/useProviderRequests';
import { useMarketplaceList } from '../../api/hooks/useMarketplace';
import type { MarketplaceListItem, RequestListItem, RequestMessage } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { messageTime } from '../../lib/datetime';
import { Screen } from '../../ui/layout/Screen';
import { Note } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { initials, requestNo } from '../../ui/format';
import { listItemEquipmentName } from '../requests/components/equipmentName';
import { cardTitle } from './components/cardText';
import { WorkspaceHeader } from '../../ui/WorkspaceHeader';

const PREVIEW_THREADS = 10;
const MAX_MARKET_THREADS = 10;

const OWN_AUTHORS = new Set(['provider_membership', 'integration_client']);

interface ChatSource {
  key: string;
  kind: 'request' | 'marketplace';
  requestId: string;
  title: string;
  about: string;
  to: string;
  lastAt: string | null;
  timezone?: string | null;
  unread?: number;
}

function fromRequest(item: RequestListItem): ChatSource {
  const equipment = listItemEquipmentName(item);
  return {
    key: `r:${item.id}`,
    kind: 'request',
    requestId: item.id,
    title: item.customer_org_name ?? item.location_name ?? equipment,
    about: strings.workspace.rowSubtitle(equipment, requestNo(item.request_number)),
    to: `/provider/requests/${item.id}?panel=messages`,
    lastAt: item.last_message_at ?? null,
    timezone: item.timezone ?? null,
    unread: item.unread_messages_count || undefined,
  };
}

function fromMarketplace(card: MarketplaceListItem): ChatSource {
  return {
    key: `m:${card.request_id}`,
    kind: 'marketplace',
    requestId: card.request_id,
    title: cardTitle(card),
    about: strings.workspace.rowSubtitle(
      strings.workspace.chatsBeforeChoice,
      requestNo(card.request_number),
    ),
    to: `/provider/available/${card.request_id}?view=ask`,
    lastAt: null,
  };
}

function preview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > 90 ? `${flat.slice(0, 89)}…` : flat;
}

export function ProviderChatsScreen() {
  const incoming = useProviderIncoming();
  const inWork = useProviderInWork();
  const market = useMarketplaceList();

  const requestChats = [...(inWork.data ?? []), ...(incoming.data ?? [])]
    .map(fromRequest)
    .filter((source) => source.lastAt !== null)
    .sort((a, b) => (b.lastAt ?? '').localeCompare(a.lastAt ?? ''));
  const marketChats = (market.data ?? [])
    .filter((card) => card.has_open_question || card.has_clarification)
    .slice(0, MAX_MARKET_THREADS)
    .map(fromMarketplace);
  const feeds = [...requestChats.slice(0, PREVIEW_THREADS), ...marketChats];

  const threads = useMessagePreviews(feeds);
  const lastByKey = new Map<string, RequestMessage | undefined>(
    feeds.map((source, index) => [source.key, threads[index]?.data ?? undefined] as const),
  );

  const lists = [incoming, inWork, market];
  const marketPending = threads.some(
    (t, index) => feeds[index]?.kind === 'marketplace' && t.isPending,
  );
  const loading = lists.some((q) => q.isPending) || marketPending;
  const failed = lists.find((q) => q.isError);

  const chats = [
    ...requestChats,
    ...marketChats
      .map((source) => ({ ...source, lastAt: lastByKey.get(source.key)?.created_at ?? null }))
      .filter((source) => source.lastAt !== null),
  ]
    .map((source) => ({ source, last: lastByKey.get(source.key) }))
    .sort((a, b) => (b.source.lastAt ?? '').localeCompare(a.source.lastAt ?? ''));
  const threadErrors = threads.filter(
    (t, index) => feeds[index]?.kind === 'marketplace' && t.isError,
  ).length;

  let body;
  if (failed) {
    body = <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  } else if (loading) {
    body = <Skeleton lines={5} />;
  } else if (chats.length === 0) {
    body = (
      <EmptyState
        illustration="chat"
        top={24}
        title={strings.workspace.chatsEmpty}
        description={strings.workspace.chatsEmptyText}
      />
    );
  } else {
    body = (
      <List aria-label={strings.workspace.chatsTitle}>
        {chats.map(({ source, last }) => (
          <ListRow
            key={source.key}
            icon={initials(source.title)}
            title={source.title}
            subtitle={
              !last
                ? undefined
                : OWN_AUTHORS.has(last.author_kind)
                  ? strings.workspace.chatsMine(preview(last.body))
                  : preview(last.body)
            }
            extra={<span className="ui-row__sub">{source.about}</span>}
            value={source.lastAt ? messageTime(source.lastAt, source.timezone, 'list') : undefined}
            valueTone="secondary"
            count={source.unread}
            to={source.to}
          />
        ))}
      </List>
    );
  }

  return (
    <Screen title={strings.ui.appTitle}>
      <WorkspaceHeader title={strings.workspace.chatsTitle} />
      {body}
      {threadErrors > 0 && !loading && (
        <Note tone="error">{strings.workspace.chatsPartialError}</Note>
      )}
    </Screen>
  );
}
