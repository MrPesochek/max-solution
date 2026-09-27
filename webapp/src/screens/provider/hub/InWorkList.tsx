import { strings } from '../../../strings/ru';
import type { CursorList } from '../../../api/hooks/cursorList';
import type { RequestListItem, RequestStatus } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { StatusHero } from '../../../ui/StatusHero';
import { List, ListRow } from '../../../ui/List';
import { listItemEquipmentName } from '../../requests/components/equipmentName';
import { JobCard, JobList, type JobTagTone } from '../components/JobCard';
import { itemArt } from '../components/jobTags';

const TAG_TONE: Partial<Record<RequestStatus, JobTagTone>> = {
  accepted: 'x',
  scheduled: 'ok',
  in_progress: 'a',
  action_required: 'x',
  cancellation_pending: 'y',
};

const TAG_LABEL: Partial<Record<RequestStatus, string>> = strings.workspace.inWorkTag;

function inWorkTag(item: RequestListItem): { label: string; tone: JobTagTone } {
  if (item.status === 'scheduled' && item.en_route_at) {
    return { label: strings.workspace.phaseTitle.enRoute!, tone: 'a' };
  }
  return {
    label: TAG_LABEL[item.status] ?? strings.requests.status[item.status],
    tone: TAG_TONE[item.status] ?? 'w',
  };
}

export function InWorkList({ query }: { query: CursorList<RequestListItem> }) {
  const w = strings.workspace;
  if (query.isPending) return <Skeleton lines={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  if (query.data.length === 0) {
    return (
      <StatusHero
        illustration="performer-empty"
        illustrationWidth={210}
        top={8}
        title={w.inWorkEmpty}
      >
        {w.inWorkEmptyText}
      </StatusHero>
    );
  }

  const jobs = (
    <JobList>
      {query.data.map((item) => (
        <JobCard
          key={item.id}
          to={`/provider/requests/${item.id}`}
          art={itemArt(item)}
          title={listItemEquipmentName(item)}
          place={w.rowSubtitle(item.customer_org_name, item.location_name)}
          tag={inWorkTag(item)}
          text={item.symptom_description}
        />
      ))}
    </JobList>
  );
  return (
    <>
      {jobs}
      {/* Очередь приходит страницами с сервера: остальное — по кнопке, а не молча обрезано. */}
      {query.hasNextPage && (
        <List>
          <ListRow
            title={strings.requests.loadMore}
            action="accent"
            loading={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          />
        </List>
      )}
    </>
  );
}
