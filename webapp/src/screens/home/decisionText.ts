import { strings } from '../../strings/ru';
import type { PendingDecision } from '../../api/types';
import { formatTime } from '../../lib/datetime';
import { formatAmountMinor } from '../../lib/money';
import { shortDateTime } from '../../ui/format';
import { pluralRu } from '../requests/card/cardFormat';

const t = strings.home;

function dayKey(date: Date): string {
  return new Intl.DateTimeFormat('ru-RU', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

export function respondByText(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const key = dayKey(date);
  if (key === dayKey(now)) return `${t.decisionToday} ${formatTime(iso)}`;
  if (key === dayKey(new Date(now.getTime() + 86_400_000)))
    return `${t.decisionTomorrow} ${formatTime(iso)}`;
  return shortDateTime(iso);
}

export function decisionSubtitle(decision: PendingDecision | null | undefined): string | null {
  if (!decision) return null;
  const price =
    typeof decision.amount_minor === 'number'
      ? formatAmountMinor(decision.amount_minor, decision.currency ?? 'RUB')
      : null;
  const due = decision.respond_by ? respondByText(decision.respond_by) : '';
  const withDue = (head: string) => (due ? `${head} · ${t.decisionRespondBy(due)}` : head);
  switch (decision.kind) {
    case 'visit_proposal':
      return withDue(t.decisionVisit(price));
    case 'repair_quote':
      return withDue(t.decisionQuote(price));
    case 'offers':
      return typeof decision.offers_count === 'number' && decision.offers_count > 0
        ? pluralRu(decision.offers_count, t.decisionOfferForms)
        : null;
    default:
      return null;
  }
}
