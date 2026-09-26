import { useParams } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { useRequestHistory } from '../../../api/hooks/useRequests';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { EventTimeline } from '../../../ui/EventTimeline';
import { Note, PageTitle } from '../../../ui/blocks/Blocks';
import { Screen } from '../../../ui/layout/Screen';
import { requestNo, shortDateTime } from '../../../ui/format';
import { requestFallback, useCustomerRequest } from './customerRequest';
import { timelineEvents } from './cardModel';
import { requestEquipmentFullName } from '../components/equipmentName';

export function RequestHistoryScreen() {
  const { id } = useParams<{ id: string }>();
  const { query, request } = useCustomerRequest(id);
  const history = useRequestHistory(id, Boolean(request));
  const back = id ? `/requests/${id}` : undefined;
  const title = strings.requests.history.title;

  const fallback = requestFallback({ query, request, title, back });
  if (fallback || !request) return fallback;
  const tz = request.location.timezone;

  return (
    <Screen title={requestNo(request.request_number)} back={back}>
      <PageTitle subtitle={requestEquipmentFullName(request)}>{title}</PageTitle>
      {history.isPending && <Skeleton lines={5} />}
      {history.isError && <ErrorState error={history.error} onRetry={() => void history.refetch()} />}
      {history.isSuccess && history.data.length === 0 && <Note>{strings.requests.card.historyEmpty}</Note>}
      {history.isSuccess && history.data.length > 0 && (
        <section aria-label={title}>
          <EventTimeline events={timelineEvents(history.data, request.visit_proposals, tz, shortDateTime)} />
        </section>
      )}
    </Screen>
  );
}
