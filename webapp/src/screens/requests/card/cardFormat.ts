import { strings } from '../../../strings/ru';
import type { Offer, Price, RequestCustomer, RequestEvent } from '../../../api/types';
import { formatTime } from '../../../lib/datetime';
import { formatAmountMinor, isPriceKnown } from '../../../lib/money';
import { relativeDay, shortDateTime, visitWindowShort } from '../../../ui/format';
import { equipmentShortName } from '../components/equipmentName';
import { eventKind } from '../../../components/request/historyEvents';

export function pluralRu(n: number, forms: readonly [string, string, string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const form = mod10 === 1 && mod100 !== 11 ? forms[0] : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? forms[1] : forms[2];
  return `${n} ${form}`;
}

export function equipmentName(request: RequestCustomer): string {
  return equipmentShortName({
    category: request.equipment_category_name ?? request.equipment.category_name,
    brand: request.equipment.brand,
    model: request.equipment.model,
  });
}

export function returnedToDraft(
  history: RequestEvent[] | undefined,
): { comment: string; by: string | null; at: string } | null {
  const last = [...(history ?? [])]
    .filter((e) => ['RequestReturnedToDraft', 'RequestSubmittedForApproval'].includes(eventKind(e)))
    .sort((a, b) => a.occurred_at.localeCompare(b.occurred_at))
    .pop();
  if (!last || eventKind(last) !== 'RequestReturnedToDraft') return null;
  const comment = typeof last.payload?.comment === 'string' ? last.payload.comment.trim() : '';
  if (!comment) return null;
  return { comment, by: last.actor_display_name ?? null, at: last.occurred_at };
}

export function atTime(iso: string | null | undefined, timezone?: string | null): string {
  if (!iso) return '';
  const day = relativeDay(iso, timezone);
  if (day.includes(' в ')) return day;
  return strings.requests.card.atTime(day, formatTime(iso, timezone));
}

export function dayMonth(iso: string | null | undefined, timezone?: string | null): string {
  return shortDateTime(iso, timezone).split(',')[0] ?? '';
}

export function approvedVisit(request: RequestCustomer) {
  return request.visit_proposals
    .filter((p) => p.status === 'approved')
    .sort((a, b) => b.version - a.version)[0];
}

export function approvedQuotes(request: RequestCustomer) {
  return request.repair_quotes.filter((q) => q.status === 'approved');
}

export function pendingQuote(request: RequestCustomer) {
  return request.repair_quotes.find((q) => q.status === 'pending');
}

export function totalPrice(prices: Price[]): string | null {
  const known = prices.filter(isPriceKnown);
  if (known.length === 0) return null;
  const currency = known[0]!.currency ?? 'RUB';
  const sum = known.reduce((acc, p) => acc + p.amount_minor, 0);
  return formatAmountMinor(sum, currency);
}

export function workerName(request: RequestCustomer): string {
  return (
    request.assignment?.field_worker?.display_name ??
    request.assignment?.provider_display_name ??
    strings.requests.card.providerTitle
  );
}

export function timeOrDate(iso: string | null | undefined, timezone?: string | null): string {
  if (!iso) return '';
  if (relativeDay(iso, timezone).startsWith('сегодня')) return formatTime(iso, timezone);
  const tomorrow = dayMonth(new Date(Date.now() + 86_400_000).toISOString(), timezone);
  if (dayMonth(iso, timezone) === tomorrow) {
    return `${strings.requests.card.tomorrow.toLowerCase()}, ${formatTime(iso, timezone)}`;
  }
  return shortDateTime(iso, timezone);
}

export function hasNoProviders(request: RequestCustomer, offers: Offer[] | undefined): boolean {
  if (!['searching', 'action_required'].includes(request.status)) return false;
  if (!request.search || request.search.matched_providers > 0) return false;
  if (request.status === 'action_required' && request.assignment) return false;
  return !offers || offers.length === 0;
}

export function reserveLapsed(request: RequestCustomer): boolean {
  return (
    request.status === 'searching' &&
    Boolean(request.assignment) &&
    ['expired', 'declined'].includes(request.assignment!.state)
  );
}

export function relativeWindow(
  start: string | null | undefined,
  end: string | null | undefined,
  timezone?: string | null,
  withZone = false,
): string {
  const full = visitWindowShort(start, end, timezone);
  if (!start) return full;
  const day = dayMonth(start, timezone);
  const today = dayMonth(new Date().toISOString(), timezone);
  const tomorrow = dayMonth(new Date(Date.now() + 86_400_000).toISOString(), timezone);
  const label = day === today ? strings.requests.card.today : day === tomorrow ? strings.requests.card.tomorrow : null;
  if (!label || (end && dayMonth(end, timezone) !== day)) return full;
  const zone = withZone ? full.match(/ (МСК|UTC[^ ]*)$/)?.[0] ?? '' : '';
  const range = end ? `${formatTime(start, timezone)}–${formatTime(end, timezone)}` : formatTime(start, timezone);
  return `${label} ${range}${zone}`;
}

export function eventTime(iso: string | null | undefined, timezone?: string | null): string {
  if (!iso) return '';
  if (relativeDay(iso, timezone).startsWith('сегодня')) return formatTime(iso, timezone);
  return dayMonth(iso, timezone);
}

export function agoText(iso: string | null | undefined, timezone?: string | null, now = Date.now()): string {
  if (!iso) return '';
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  const c = strings.requests.card;
  if (Number.isNaN(minutes)) return '';
  if (minutes < 1) return c.justNow;
  if (minutes < 60) return c.minutesAgo(pluralRu(minutes, c.minuteForms));
  if (minutes < 6 * 60) return c.minutesAgo(pluralRu(Math.floor(minutes / 60), c.hourForms));
  return atTime(iso, timezone);
}

export function minutesSince(iso: string | null | undefined, now = Date.now()): number {
  if (!iso) return 0;
  const value = (now - new Date(iso).getTime()) / 60_000;
  return Number.isNaN(value) ? 0 : value;
}

export function forceDeadlinePassed(
  cancellation: RequestCustomer['cancellation'],
  now: number = Date.now(),
): boolean {
  if (!cancellation || !['pending', 'disputed'].includes(cancellation.status)) return false;
  const deadline = cancellation.dispute_deadline_at;
  return deadline != null && new Date(deadline).getTime() <= now;
}
