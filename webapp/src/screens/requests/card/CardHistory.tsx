import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { useRequestHistory } from '../../../api/hooks/useRequests';
import type { VisitProposal } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { EventTimeline, type TimelineEvent } from '../../../ui/EventTimeline';
import { Note } from '../../../ui/blocks/Blocks';
import { timelineEvents } from './cardModel';

const CARD_LIMIT = 5;

export function CardHistory({
  requestId,
  proposals,
  timezone,
  steps,
  defaultOpen = false,
}: {
  requestId: string;
  proposals: VisitProposal[];
  timezone?: string | null;
  steps?: TimelineEvent[];
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const listId = useId();
  const history = useRequestHistory(requestId, open && !steps);
  const events = steps ?? (history.data ? timelineEvents(history.data, proposals, timezone) : []);
  const c = strings.requests.card;

  return (
    <section className="request-history" aria-label={c.historyTitle}>
      <button
        type="button"
        className="request-history__head"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="request-history__title">{c.historyTitle}</span>
        <span className="request-history__toggle">{open ? strings.ui.hide : strings.ui.show}</span>
      </button>
      {open && (
        <div id={listId}>
          {!steps && history.isPending && <Skeleton lines={3} />}
          {!steps && history.isError && (
            <ErrorState error={history.error} onRetry={() => void history.refetch()} />
          )}
          {(steps || history.isSuccess) && events.length === 0 && <Note>{c.historyEmpty}</Note>}
          {events.length > 0 && <EventTimeline events={events.slice(0, CARD_LIMIT)} />}
          {!steps && events.length > CARD_LIMIT && (
            <Link className="request-history__all" to={`/requests/${requestId}/history`}>
              {c.historyAll(events.length)}
            </Link>
          )}
        </div>
      )}
    </section>
  );
}
