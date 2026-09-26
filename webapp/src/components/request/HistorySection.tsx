import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useRequestHistory } from '../../api/hooks/useRequests';
import type { VisitProposal } from '../../api/types';
import { formatPrice } from '../../lib/money';
import { shortDateTime } from '../../ui/format';
import { List, ListRow } from '../../ui/List';
import { Note } from '../../ui/blocks/Blocks';
import { Skeleton } from '../states/Skeleton';
import { ErrorState } from '../states/ErrorState';
import { eventKind, eventMarker, eventProposal, eventTitle } from './historyEvents';

export function HistorySection({
  requestId,
  embedded = false,
  proposals = [],
  timezone,
}: {
  requestId: string;
  embedded?: boolean;
  proposals?: VisitProposal[];
  timezone?: string | null;
}) {
  const [openState, setOpen] = useState(false);
  const open = embedded || openState;
  const history = useRequestHistory(requestId, open);

  return (
    <>
      {!embedded && (
        <List>
          <ListRow
            title={open ? strings.requests.card.historyHide : strings.requests.card.historyShow}
            chevron
            expanded={open}
            onClick={() => setOpen((v) => !v)}
          />
        </List>
      )}
      {open && history.isPending && <Skeleton lines={3} />}
      {open && history.isError && (
        <ErrorState error={history.error} onRetry={() => void history.refetch()} />
      )}
      {open && history.isSuccess && history.data.length === 0 && (
        <Note>{strings.requests.card.historyEmpty}</Note>
      )}
      {open && history.isSuccess && history.data.length > 0 && (
        <List aria-label={strings.requests.history.title}>
          {history.data.map((event) => {
            const kind = eventKind(event);
            const proposal =
              kind === 'VisitProposed' || kind === 'VisitProposalSuperseded'
                ? eventProposal(event, proposals)
                : undefined;
            const when = shortDateTime(event.occurred_at, timezone);
            return (
              <ListRow
                key={event.id}
                marker={eventMarker(event)}
                title={eventTitle(event, proposals)}
                subtitle={[proposal ? formatPrice(proposal.price) : event.actor_display_name, when]
                  .filter(Boolean)
                  .join(' · ')}
              />
            );
          })}
        </List>
      )}
    </>
  );
}
