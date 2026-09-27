import { strings } from '../../../strings/ru';
import type { CursorList } from '../../../api/hooks/cursorList';
import type { RequestListItem } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { StatusHero } from '../../../ui/StatusHero';
import { List, ListRow } from '../../../ui/List';
import { listItemEquipmentName } from '../../requests/components/equipmentName';
import { JobCard, JobList } from '../components/JobCard';
import { itemArt, urgencyTag } from '../components/jobTags';

export function IncomingList({
  query,
  paused,
}: {
  query: CursorList<RequestListItem>;
  paused: boolean;
}) {
  const w = strings.workspace;
  if (query.isPending) return <Skeleton lines={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  if (query.data.length === 0) {
    return (
      <StatusHero
        illustration="performer-empty"
        illustrationWidth={210}
        top={8}
        title={w.jobsEmpty}
      >
        {paused ? w.pausedEmptyText : w.jobsEmptyText}
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
          tag={urgencyTag(item.urgency)}
          text={item.symptom_description}
          meta={item.contract_number ? w.contractNumberMeta(item.contract_number) : undefined}
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
