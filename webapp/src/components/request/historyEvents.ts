import { strings } from '../../strings/ru';
import type { RequestEvent } from '../../api/types';
import type { RowMarker } from '../../ui/List';

const ALIASES: Record<string, string> = {
  'request.created': 'RequestDrafted',
  'request.updated': 'RequestDraftUpdated',
  'request.approval_requested': 'RequestSubmittedForApproval',
  'request.returned_to_draft': 'RequestReturnedToDraft',
  'request.submitted': 'RequestSubmittedToOwnService',
  'request.published': 'SearchPublished',
  'request.cancelled': 'RequestCancelled',
  'request.accepted': 'AssignmentAccepted',
  'request.declined': 'AssignmentDeclined',
  'request.work_started': 'WorkStarted',
  'request.completion_reported': 'CompletionReported',
  'request.completion_rejected': 'CompletionRejected',
  'request.closed': 'RequestClosed',
  'assignment.revoked': 'AssignmentRevoked',
  'assignment.withdrawn': 'AssignmentWithdrawn',
  'assignment.confirmed': 'AssignmentConfirmed',
  'assignment.warranty_decision': 'WarrantyDecisionStated',
  'assignment.field_worker_set': 'FieldWorkerAssigned',
  'offer.submitted': 'OfferSubmitted',
  'offer.withdrawn': 'OfferWithdrawn',
  'offer.selected': 'OfferSelected',
  'visit_proposal.proposed': 'VisitProposed',
  'visit_proposal.approved': 'VisitAgreed',
  'visit_proposal.rejected': 'VisitProposalRejected',
  'repair_quote.proposed': 'RepairQuoteCreated',
  'repair_quote.approved': 'RepairQuoteApproved',
  'repair_quote.rejected': 'RepairQuoteRejected',
  'cancellation.requested': 'CancellationRequested',
  'cancellation.disputed': 'CancellationDisputed',
  'cancellation.withdrawn': 'CancellationWithdrawn',
  'cancellation.force_closed': 'CancellationForced',
  'cancellation.accepted': 'RequestCancelled',
};

export function eventKind(event: Pick<RequestEvent, 'event_type'>): string {
  return ALIASES[event.event_type] ?? event.event_type;
}

const POSITIVE = new Set([
  'RequestSubmittedForApproval',
  'RequestSubmittedToOwnService',
  'SearchPublished',
  'AssignmentAccepted',
  'AssignmentConfirmed',
  'OfferSelected',
  'VisitAgreed',
  'RepairQuoteApproved',
  'FieldWorkerEnRoute',
  'WorkStarted',
  'CompletionReported',
  'RequestClosed',
  'ExternalReferenceLinked',
]);

const NEGATIVE = new Set([
  'AssignmentDeclined',
  'AssignmentWithdrawn',
  'AssignmentExpired',
  'SearchFoundNoProviders',
  'SearchExpired',
  'VisitProposalRejected',
  'VisitProposalExpired',
  'RepairQuoteRejected',
  'RepairQuoteExpired',
  'CompletionRejected',
  'RequestCancelled',
  'CancellationDisputed',
  'CancellationForced',
]);

export function eventMarker(event: RequestEvent): RowMarker {
  const kind = eventKind(event);
  if (POSITIVE.has(kind)) return 'ok';
  if (NEGATIVE.has(kind)) return 'x';
  return '-';
}

function payloadNumber(event: RequestEvent, key: string): number | null {
  const value = event.payload?.[key];
  return typeof value === 'number' ? value : null;
}

function payloadString(event: RequestEvent, key: string): string | null {
  const value = event.payload?.[key];
  return typeof value === 'string' ? value : null;
}

interface Versioned {
  id: string;
  version: number;
}

export function eventProposal<T extends Versioned>(event: RequestEvent, proposals: T[]): T | undefined {
  const id = payloadString(event, 'visit_proposal_id') ?? payloadString(event, 'proposal_id');
  return id ? proposals.find((p) => p.id === id) : undefined;
}

export function eventTitle(event: RequestEvent, proposals: Versioned[] = []): string {
  const kind = eventKind(event);
  const proposalVersion =
    payloadNumber(event, 'proposal_version') ?? eventProposal(event, proposals)?.version ?? null;
  if (kind === 'VisitProposed' && proposalVersion) {
    return proposalVersion > 1
      ? strings.requests.history.visitSuperseded(proposalVersion)
      : strings.requests.history.visitProposed(proposalVersion);
  }
  if (kind === 'VisitProposalSuperseded' && proposalVersion) {
    return strings.requests.history.visitSuperseded(proposalVersion);
  }
  const quoteVersion = payloadNumber(event, 'quote_version');
  if (kind === 'RepairQuoteCreated' && quoteVersion) return strings.requests.history.quoteCreated(quoteVersion);
  const labels = strings.requests.card.historyEvents;
  return labels[kind] ?? labels[event.event_type] ?? event.event_type;
}

export function lastEvent(events: RequestEvent[] | undefined, kinds: string[]): RequestEvent | undefined {
  if (!events) return undefined;
  const wanted = new Set(kinds);
  let found: RequestEvent | undefined;
  for (const event of events) {
    if (!wanted.has(eventKind(event))) continue;
    if (!found || event.occurred_at >= found.occurred_at) found = event;
  }
  return found;
}
