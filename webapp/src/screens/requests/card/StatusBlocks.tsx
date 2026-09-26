import { strings } from '../../../strings/ru';
import type { Attachment, RequestCustomer } from '../../../api/types';
import { formatPrice } from '../../../lib/money';
import { Note } from '../../../ui/blocks/Blocks';
import { KeyValueRows } from '../../../ui/KeyValueRows';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../../ui/PhotoGrid';
import { approvedQuotes, approvedVisit, dayMonth, pendingQuote } from './cardFormat';
import { approvedTotal, type CardView } from './cardModel';
import { CardHero } from '../../../ui/CardHero';
import { CardPerson } from './CardPerson';

function reportTileState(attachment: Attachment): PhotoState {
  if (attachment.processing_state === 'rejected') return 'e';
  if (attachment.processing_state === 'quarantined') return 'q';
  return 'ok';
}

export function ReportPhotos({
  report,
  requestNumber,
}: {
  report: NonNullable<RequestCustomer['completion_report']>;
  requestNumber: number;
}) {
  const c = strings.requests.card;
  const tiles = [
    ...report.photos_before.map((a) => ({ attachment: a as Attachment, label: c.reportPhotoBefore })),
    ...report.photos_after.map((a) => ({ attachment: a as Attachment, label: c.reportPhotoAfter })),
  ];
  if (tiles.length === 0) return null;
  return (
    <PhotoGrid label={c.reportPhotosLabel}>
      {tiles.map(({ attachment, label }, index) => (
        <PhotoTile
          key={attachment.id}
          label={label}
          state={reportTileState(attachment)}
          attachmentId={attachment.id}
          alt={c.reportPhotoAlt(label, requestNumber, index + 1)}
        />
      ))}
    </PhotoGrid>
  );
}

export function PriceRows({ request, isManager }: { request: RequestCustomer; isManager: boolean }) {
  const c = strings.requests.card;
  const visit = approvedVisit(request);
  const quotes = approvedQuotes(request);
  const pending = pendingQuote(request);
  const tz = request.location.timezone;
  const lastQuote = [...quotes].sort((a, b) => b.version - a.version)[0];
  const total = request.status === 'closed' ? approvedTotal(request) : null;

  return (
    <ul className="request-prices" aria-label={c.pricesLabel}>
      {visit && (
        <li className="request-prices__row">
          <span className="request-prices__label">
            {c.visitPriceRow}
            <span className="request-prices__hint">
              {pending || lastQuote ? (visit.scope_description ?? c.visitApproved) : c.repairOnSite}
            </span>
          </span>
          <span className="request-prices__value">{formatPrice(visit.price)}</span>
        </li>
      )}
      {pending ? (
        <li className="request-prices__row">
          <span className="request-prices__label">
            {c.repairRow}
            <span className="request-prices__hint request-prices__hint--accent">
              {isManager ? c.repairAwaiting : c.repairAwaitingManager}
            </span>
          </span>
          <span className="request-prices__value">{formatPrice(pending.price)}</span>
        </li>
      ) : lastQuote ? (
        <li className="request-prices__row">
          <span className="request-prices__label">
            {c.repairRow}
            {lastQuote.responded_at && (
              <span className="request-prices__hint">{c.approvedOn(dayMonth(lastQuote.responded_at, tz))}</span>
            )}
          </span>
          <span className="request-prices__value">{formatPrice(lastQuote.price)}</span>
        </li>
      ) : !visit ? (
        <li className="request-prices__row">
          <span className="request-prices__label">{c.repairRow}</span>
          <span className="request-prices__value request-prices__value--muted">{c.repairAfterDiagnostics}</span>
        </li>
      ) : null}
      {total && (
        <li className="request-prices__row">
          <span className="request-prices__label">{c.totalApproved}</span>
          <span className="request-prices__value">{total}</span>
        </li>
      )}
    </ul>
  );
}

export function StatusBlocks({ view, request }: { view: CardView; request: RequestCustomer }) {
  const person = view.person;
  return (
    <>
      <CardHero {...view.hero} size={view.size} />
      {person && (
        <CardPerson
          name={person.name}
          company={person.company}
          phone={person.phone}
          rating={person.withRating ? (request.assignment?.provider ?? null) : null}
        />
      )}
      {view.report && view.report.rows.length > 0 && (
        <KeyValueRows rows={view.report.rows} aria-label={strings.requests.card.reportLabel} />
      )}
      {view.report?.photos && request.completion_report && (
        <ReportPhotos report={request.completion_report} requestNumber={request.request_number} />
      )}
      {view.note && <Note>{view.note}</Note>}
    </>
  );
}
