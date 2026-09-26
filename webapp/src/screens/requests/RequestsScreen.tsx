import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useLocations } from '../../api/hooks/useLocations';
import { useActiveRequests, useRequestsList } from '../../api/hooks/useRequests';
import { usePendingApprovals } from '../../api/hooks/useApprovals';
import type { RequestStatus } from '../../api/types';
import { useSession } from '../../session/SessionContext';
import { canManageRequestApprovals } from '../../lib/roles';
import { isActiveRequestStatus } from '../../lib/status';
import { ErrorState } from '../../components/states/ErrorState';
import { Screen } from '../../ui/layout/Screen';
import { PageTitle } from '../../ui/blocks/Blocks';
import { Segmented } from '../../ui/Segmented';
import { Chip, Chips, FilterChip } from '../../ui/Chips';
import { List, ListRow } from '../../ui/List';
import { SkeletonRows } from '../../ui/Skeleton';
import { StatusHero } from '../../ui/StatusHero';
import { equipmentIllustration } from '../../ui/illustrations';
import { relativeDay } from '../../ui/format';
import { listItemEquipmentName } from './components/equipmentName';
import { listDate, listItemDate, listStatus } from './components/listStatus';

const STATUS_OPTIONS: RequestStatus[] = [
  'draft',
  'approval_required',
  'awaiting_provider',
  'searching',
  'awaiting_assignment_confirmation',
  'accepted',
  'scheduled',
  'in_progress',
  'completion_reported',
  'action_required',
  'cancellation_pending',
  'closed',
  'cancelled',
];

type Scope = 'active' | 'done';

const t = strings.requests;

export function RequestsScreen() {
  const { activeMembership } = useSession();
  const isManager = Boolean(activeMembership && canManageRequestApprovals(activeMembership.role));
  const [locationId, setLocationId] = useState('');
  const [status, setStatus] = useState<RequestStatus | ''>('');
  const [scope, setScope] = useState<Scope>('active');

  const locations = useLocations();
  const activeAll = useActiveRequests();
  const approvals = usePendingApprovals();
  const list = useRequestsList({
    locationId: locationId || undefined,
    status: status ? [status] : undefined,
    active: status ? undefined : scope === 'active',
  });
  const items = list.data ?? [];

  const resetFilters = () => {
    setLocationId('');
    setStatus('');
  };

  const visible = status
    ? items
    : items.filter((item) => isActiveRequestStatus(item.status) === (scope === 'active'));
  const filtered = Boolean(locationId || status);
  const activeCount = activeAll.data?.length;
  const statusOptions = STATUS_OPTIONS.filter(
    (s) => isActiveRequestStatus(s) === (scope === 'active'),
  ).map((s) => ({ value: s, label: t.status[s] }));
  const approvalByRequest = new Map(
    approvals.approvals.filter((a) => a.kind !== 'question').map((a) => [a.requestId, a]),
  );

  const neverCreated =
    scope === 'active' && !filtered && list.isSuccess && items.length === 0 && activeCount === 0;
  const showPoints = (locations.data?.length ?? 0) > 1;

  return (
    <Screen title={t.title} hideHeader>
      <PageTitle size="m" as="h1">
        {t.title}
      </PageTitle>

      <Segmented
        label={t.listScopeLabel}
        items={[
          {
            id: 'active',
            label: activeCount !== undefined ? t.scopeActiveCount(activeCount) : t.scopeActive,
          },
          { id: 'done', label: t.scopeDone },
        ]}
        value={scope}
        onChange={(next) => {
          setScope(next);
          setStatus('');
        }}
      />

      {!neverCreated && (
        <Chips label={t.filtersLabel} scroll>
          {showPoints && (
            <>
              <Chip
                variant="outline"
                size="s"
                selected={locationId === ''}
                onClick={() => setLocationId('')}
              >
                {t.filterAllLocations}
              </Chip>
              {(locations.data ?? []).map((location) => (
                <Chip
                  key={location.id}
                  variant="outline"
                  size="s"
                  selected={locationId === location.id}
                  onClick={() => setLocationId(location.id)}
                >
                  {location.name}
                </Chip>
              ))}
            </>
          )}
          <FilterChip
            label={t.filterStatus}
            allLabel={t.filterAllStatuses}
            value={status}
            options={statusOptions}
            onChange={(value) => setStatus(value as RequestStatus | '')}
          />
        </Chips>
      )}

      {list.isPending && items.length === 0 && <SkeletonRows rows={5} media />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}

      {!list.isError && list.isSuccess && visible.length === 0 && (
        <>
          {neverCreated ? (
            <StatusHero illustration="request-sent" illustrationWidth={188} top={24} title={t.emptyTitle}>
              {t.emptyText}
            </StatusHero>
          ) : locationId && !status ? (
            <StatusHero top={32} title={t.pointEmptyTitle}>
              {t.pointEmptyText}
            </StatusHero>
          ) : filtered ? (
            <StatusHero top={32} title={t.noResultsTitle}>
              {t.noResultsText}
            </StatusHero>
          ) : (
            <StatusHero top={32} title={t.doneEmptyTitle} />
          )}
          {filtered ? (
            <List>
              <ListRow title={t.resetFilters} action="accent" onClick={resetFilters} />
            </List>
          ) : scope === 'active' ? (
            <List>
              <ListRow title={strings.home.newRequest} action="accent" to="/requests/new" />
            </List>
          ) : null}
        </>
      )}

      {visible.length > 0 && (
        <List>
          {visible.map((item) => {
            const isDraft = item.status === 'draft';
            const line = listStatus(item, { isManager, approval: approvalByRequest.get(item.id) });
            const unread = item.unread_messages_count ?? 0;
            return (
              <ListRow
                key={item.id}
                media={equipmentIllustration(null, item.equipment_category_name ?? item.equipment_title)}
                title={listItemEquipmentName(item)}
                subtitle={isDraft ? strings.home.draftSaved(relativeDay(item.updated_at, item.timezone)) : line.text}
                subtitleTone={!isDraft && line.accent ? 'accent' : undefined}
                value={listDate(listItemDate(item), item.timezone)}
                valueTone="secondary"
                count={unread > 0 ? unread : undefined}
                aria-label={unread > 0 ? `${listItemEquipmentName(item)}. ${line.text}. ${t.unreadMessages(unread)}` : undefined}
                to={`/requests/${item.id}`}
              />
            );
          })}
          {list.hasNextPage && (
            <ListRow
              title={t.loadMore}
              action="accent"
              loading={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            />
          )}
        </List>
      )}
    </Screen>
  );
}
