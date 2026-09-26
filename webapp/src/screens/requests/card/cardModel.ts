import { strings } from '../../../strings/ru';
import type {
  Offer,
  ProviderRatingSummary,
  RequestCustomer,
  RequestEvent,
  RequestMessage,
  VisitProposal,
} from '../../../api/types';
import { formatTime } from '../../../lib/datetime';
import { formatPrice, isPriceKnown } from '../../../lib/money';
import { requestStatusLabel, requestStatusWhatNext } from '../../../lib/status';
import type { KeyValueRow } from '../../../ui/KeyValueRows';
import type { TimelineEvent } from '../../../ui/EventTimeline';
import { eventKind, eventMarker, eventTitle, lastEvent } from '../../../components/request/historyEvents';
import {
  agoText,
  approvedQuotes,
  approvedVisit,
  atTime,
  eventTime,
  hasNoProviders,
  minutesSince,
  pendingQuote,
  pluralRu,
  relativeWindow,
  reserveLapsed,
  timeOrDate,
  totalPrice,
  workerName,
} from './cardFormat';
import { deliveryProblem, deliveryProblemText, deliveryStep } from './delivery';
import type { HeroContent } from '../../../ui/CardHero';

const SILENT_AFTER_MINUTES = 30;

export const MESSAGE_STATUSES = new Set([
  'awaiting_provider',
  'awaiting_assignment_confirmation',
  'accepted',
  'scheduled',
  'in_progress',
  'completion_reported',
  'cancellation_pending',
]);

export function approvedTotal(request: RequestCustomer): string | null {
  return totalPrice(
    [approvedVisit(request)?.price, ...approvedQuotes(request).map((q) => q.price)].filter(
      (p): p is NonNullable<typeof p> => Boolean(p),
    ),
  );
}

export function timelineEvents(
  events: RequestEvent[],
  proposals: VisitProposal[],
  timezone?: string | null,
  format: (iso: string, timezone?: string | null) => string = eventTime,
): TimelineEvent[] {
  return [...events]
    .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    .map((event, index) => {
      const marker = eventMarker(event);
      return {
        id: event.id,
        title: eventTitle(event, proposals),
        sub: event.actor_display_name ?? undefined,
        time: format(event.occurred_at, timezone),
        tone: marker === 'x' ? 'danger' : index === 0 ? 'accent' : 'neutral',
      };
    });
}

export function ratingLine(rating: ProviderRatingSummary | null): string | null {
  if (!rating) return null;
  if (rating.rating === null || rating.rating === undefined) {
    return rating.rating_label ?? strings.offers.providerFewReviews;
  }
  const value = rating.rating.toFixed(1).replace('.', ',');
  const count = rating.reviews_count;
  return typeof count === 'number'
    ? strings.requests.card.ratingWithCount(value, pluralRu(count, strings.offers.reviewForms))
    : strings.requests.card.rating(value);
}

const OWN = 'customer_membership';

export function openQuestion(messages: RequestMessage[] | undefined, providerOrgId: string | null): RequestMessage | null {
  const thread = (messages ?? []).filter((m) => !m.thread_provider_id || m.thread_provider_id === providerOrgId);
  const last = [...thread].sort((a, b) => a.created_at.localeCompare(b.created_at)).pop();
  return last && last.author_kind !== OWN ? last : null;
}

export function questionAuthor(message: RequestMessage, request: RequestCustomer): { name: string; org: string | null } {
  const provider =
    message.author_organization_name ?? request.assignment?.provider_display_name ?? strings.offers.providerFallback;
  if (message.author_kind === 'integration_client') {
    const crm = strings.requests.card.crmAuthor(provider);
    const label = message.author_label?.trim();
    return label ? { name: label, org: crm } : { name: crm, org: null };
  }
  const name = message.author_display_name ?? provider;
  return { name, org: name === provider ? null : provider };
}

export function messageAuthorLine(message: RequestMessage, request: RequestCustomer): string {
  const author = questionAuthor(message, request);
  return message.author_kind === 'integration_client' && author.org ? `${author.name} · ${author.org}` : author.name;
}

export function deliveredToCrm(message: RequestMessage): boolean {
  return message.delivery?.channel === 'crm' && message.delivery.state === 'delivered';
}

export function chatPartner(request: RequestCustomer): string {
  return (
    request.assignment?.field_worker?.display_name ??
    request.assignment?.provider_display_name ??
    strings.offers.providerFallback
  );
}

export interface CardView {
  hero: HeroContent;
  size: 'xl' | 'l' | 'm';
  person?: { name: string; company?: string | null; phone?: string | null; withRating?: boolean };
  report?: { rows: KeyValueRow[]; photos: boolean };
  note?: string;
  steps?: TimelineEvent[];
  historyOpen?: boolean;
  prices?: boolean;
}

interface CardViewInput {
  request: RequestCustomer;
  isManager: boolean;
  history: RequestEvent[] | undefined;
  offers: Offer[] | undefined;
  waiting?: boolean;
}

function providerPerson(request: RequestCustomer, withRating = true): CardView['person'] {
  const assignment = request.assignment;
  if (!assignment) return undefined;
  const provider = assignment.provider_display_name ?? strings.offers.providerFallback;
  const worker = assignment.field_worker?.display_name;
  return {
    name: worker ?? provider,
    company: worker ? provider : null,
    phone: assignment.field_worker?.contact_phone ?? assignment.provider_contact_phone,
    withRating,
  };
}

function deliverySteps(request: RequestCustomer): TimelineEvent[] {
  const c = strings.requests.card;
  const tz = request.location.timezone;
  const delivery = deliveryStep(request);
  const problem = deliveryProblem(request);
  const provider = request.assignment?.provider_display_name;
  const steps: TimelineEvent[] = [];
  if (!problem) steps.push({ id: 'accepted', title: c.timelineAccepted, time: c.timelineWaiting, tone: 'neutral' });
  if (delivery) {
    steps.push({
      id: 'delivered',
      title: delivery.title,
      time: delivery.value,
      tone: delivery.marker === 'x' ? 'danger' : delivery.pending ? 'neutral' : 'accent',
    });
  }
  steps.push({
    id: 'sent',
    title: provider ? c.timelineSentTo(provider) : c.timelineSent,
    time: request.submitted_at ? eventTime(request.submitted_at, tz) : undefined,
    tone: delivery ? 'neutral' : 'accent',
  });
  return steps;
}

export function cardView({ request, isManager, history, offers, waiting }: CardViewInput): CardView {
  const c = strings.requests.card;
  const tz = request.location.timezone;
  const assignment = request.assignment;
  const provider = assignment?.provider_display_name ?? null;
  const join = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(' · ');

  switch (request.status) {
    case 'approval_required':
      return {
        size: 'l',
        hero: {
          scene: 'status-waiting',
          title: isManager ? c.approvalTitle : requestStatusLabel(request.status),
          text: isManager
            ? request.route === 'own_service'
              ? c.approvalTextOwnService
              : c.approvalTextMarketplace
            : c.approvalEmployeeText(request.approver_name),
        },
      };

    case 'awaiting_provider': {
      const delivery = deliveryStep(request);
      const problem = deliveryProblem(request);
      const since = request.delivery?.delivered_at ?? request.submitted_at;
      const silent = minutesSince(since) >= SILENT_AFTER_MINUTES;
      const reminder = assignment?.reminder_at;
      const canRevoke = isManager && assignment?.state === 'pending' && request.route === 'own_service';
      return {
        size: 'l',
        hero: problem
          ? { scene: 'status-waiting', title: c.deliveryFailedTitle, text: deliveryProblemText(request, problem) }
          : {
              scene: 'status-waiting',
              title: silent && provider ? c.silentTitle(provider) : c.waitingProviderTitle,
              text: [
                delivery && !delivery.pending
                  ? c.waitingProviderDeliveredAgo(agoText(since, tz))
                  : c.waitingProviderSentAgo(agoText(request.submitted_at, tz)),
                canRevoke ? c.waitOrFindOther : null,
              ]
                .filter(Boolean)
                .join(' '),
              note: waiting
                ? reminder
                  ? c.remindAt(formatTime(reminder, tz))
                  : c.remindSoon
                : undefined,
            },
        steps: deliverySteps(request),
        historyOpen: true,
      };
    }

    case 'searching': {
      const active = (offers ?? []).filter((o) => o.state === 'active');
      if (hasNoProviders(request, offers)) {
        return {
          size: 'l',
          hero: {
            scene: 'equipment-empty',
            title: c.noProvidersTitle,
            text: c.noProvidersText,
          },
        };
      }
      if (reserveLapsed(request)) {
        return {
          size: 'l',
          hero: {
            scene: 'status-waiting',
            title: c.reserveExpiredTitle,
            text: c.reserveExpiredText(
              provider ?? strings.offers.providerFallback,
              active.length ? pluralRu(active.length, c.offerForms) : null,
            ),
          },
        };
      }
      const published = request.search?.public_card?.published_at;
      return {
        size: 'l',
        hero: {
          scene: active.length > 0 ? 'status-offers' : 'status-search',
          title: c.searchingTitle,
          text: c.searchingText(
            pluralRu(request.search?.matched_providers ?? 0, c.matchedForms),
            active.length ? pluralRu(active.length, c.offerForms) : null,
          ),
          note: published ? c.publishedAt(formatTime(published, tz)) : undefined,
        },
      };
    }

    case 'awaiting_assignment_confirmation': {
      const chosen = (offers ?? []).find((o) => o.state === 'selected');
      const name = provider ?? chosen?.provider?.display_name ?? strings.offers.providerFallback;
      return {
        size: 'l',
        hero: {
          scene: 'status-waiting',
          title: requestStatusLabel(request.status),
          text: assignment?.expires_at
            ? c.awaitingConfirmText(timeOrDate(assignment.expires_at, tz))
            : strings.offers.awaitingConfirmationDescription,
          accent: chosen
            ? join(
                relativeWindow(chosen.visit_window_start, chosen.visit_window_end, tz),
                isPriceKnown(chosen.price) ? formatPrice(chosen.price) : strings.offers.priceUnknownTitle,
              )
            : undefined,
        },
        person: { name, withRating: false },
      };
    }

    case 'accepted':
      return {
        size: 'l',
        hero: {
          scene: 'status-waiting',
          title: requestStatusLabel(request.status),
          text:
            provider && assignment?.responded_at
              ? `${c.acceptedAt(provider, formatTime(assignment.responded_at, tz))}. ${c.acceptedText}`
              : c.acceptedText,
        },
        person: providerPerson(request),
        prices: Boolean(pendingQuote(request)),
      };

    case 'scheduled': {
      const visit = approvedVisit(request);
      const enRoute = assignment?.en_route_at;
      const who = workerName(request);
      return {
        size: 'xl',
        hero: {
          scene: 'status-travel',
          title: enRoute ? c.enRouteTitle : c.scheduledTitle,
          accent: visit ? relativeWindow(visit.visit_window_start, visit.visit_window_end, tz, true) : undefined,
          text: enRoute
            ? c.enRouteText(who, formatTime(enRoute, tz))
            : visit
              ? c.scheduledText(who)
              : requestStatusWhatNext(request.status),
        },
        person: providerPerson(request),
        prices: true,
      };
    }

    case 'in_progress': {
      const pending = pendingQuote(request);
      return {
        size: 'l',
        hero: {
          scene: pending ? 'status-price' : 'status-repair',
          title: c.inProgressTitle,
          text: pending
            ? isManager
              ? c.quoteWaitingText(workerName(request))
              : c.quoteWaitingEmployee
            : c.inProgressText(
                workerName(request),
                request.work_started_at ? formatTime(request.work_started_at, tz) : null,
              ),
        },
        person: providerPerson(request),
        prices: true,
      };
    }

    case 'completion_reported': {
      const report = request.completion_report;
      const total = approvedTotal(request);
      const rows: KeyValueRow[] = [];
      if (report?.summary) rows.push({ label: c.reportDone, value: report.summary });
      if (total) rows.push({ label: c.reportSum, value: c.reportSumValue(total) });
      return {
        size: 'm',
        hero: {
          scene: 'status-done',
          title: c.reportTitle,
          text: c.reportText,
        },
        report: { rows, photos: Boolean(report) },
        note: c.reportNote,
        person: providerPerson(request),
      };
    }

    case 'action_required': {
      if (hasNoProviders(request, offers)) {
        return {
          size: 'l',
          hero: {
            scene: 'equipment-empty',
            title: c.noProvidersTitle,
            text: c.noProvidersText,
          },
        };
      }
      const reasonEvent = lastEvent(history, [
        'AssignmentDeclined',
        'AssignmentWithdrawn',
        'AssignmentExpired',
        'AssignmentRevoked',
        'SearchStopped',
        'SearchExpired',
      ]);
      const kind = assignment
        ? {
            declined: 'AssignmentDeclined',
            withdrawn: 'AssignmentWithdrawn',
            expired: 'AssignmentExpired',
            revoked: 'AssignmentRevoked',
          }[assignment.state as string]
        : reasonEvent
          ? eventKind(reasonEvent)
          : undefined;
      const eventReason = typeof reasonEvent?.payload?.reason === 'string' ? reasonEvent.payload.reason : null;
      let title: string = c.approvalTitle;
      let text: string = requestStatusWhatNext(request.status);
      if (kind === 'AssignmentDeclined') {
        title = c.declinedTitleNoName;
        text = c.declinedText(provider, assignment?.decline_reason ?? eventReason);
      } else if (kind === 'AssignmentWithdrawn') {
        title = c.withdrawnTitleNoName;
        text = c.declinedText(provider, assignment?.withdrawal_reason ?? eventReason);
      } else if (kind === 'AssignmentExpired') {
        title = c.expiredAssignmentTitle;
        text = c.declinedText(null, null);
      } else if (kind === 'AssignmentRevoked') {
        title = c.revokedTitle;
        text = c.declinedText(null, null);
      } else if (kind === 'SearchStopped' || kind === 'SearchExpired' || request.search?.public_card) {
        title = c.searchStoppedTitle;
        text = c.declinedText(null, null);
      }
      return {
        size: 'l',
        hero: { scene: 'status-cancel', title, text },
        note: isManager ? c.noAutoSearchNote : undefined,
      };
    }

    case 'cancellation_pending':
      return {
        size: 'l',
        hero: {
          scene: 'status-cancel',
          title: request.cancellation?.status === 'disputed' ? c.cancelDisputedTitle : c.cancellationPendingTitle,
          text: request.cancellation?.status === 'disputed' ? c.cancelDisputedDescription : c.cancellationPendingText,
        },
        person: providerPerson(request),
      };

    case 'closed': {
      const auto = Boolean(request.closure_kind?.startsWith('auto'));
      const when = atTime(request.closed_at, tz);
      return {
        size: 'm',
        hero: {
          scene: 'thanks',
          title: auto ? c.autoClosedTitle : c.closedTitle,
          text: when ? (auto ? c.autoClosedText(when) : c.closedText(when)) : requestStatusWhatNext(request.status),
        },
        person: providerPerson(request),
        prices: true,
      };
    }

    case 'cancelled': {
      const when = request.cancelled_at ? atTime(request.cancelled_at, tz) : '';
      return {
        size: 'l',
        hero: {
          scene: 'status-cancel',
          title: c.cancelledTitle,
          text: when ? c.cancelledText(when, !request.accepted_at) : c.cancelledTextNoDate,
        },
      };
    }

    default:
      return {
        size: 'l',
        hero: {
          scene: 'status-waiting',
          title: requestStatusLabel(request.status),
          text: requestStatusWhatNext(request.status),
        },
      };
  }
}

