import { strings } from '../../../strings/ru';
import type { RequestListItem } from '../../../api/types';
import type { ApprovalItem } from '../../../api/hooks/useApprovals';
import { formatDate, formatTime } from '../../../lib/datetime';
import { shortDateTime } from '../../../ui/format';
import { requestRowTag } from './requestTag';

export interface ListStatus {
  text: string;
  accent: boolean;
}

const ACTIVE_WORK = new Set(['scheduled', 'in_progress']);

function visitStart(iso: string, timezone: string | null | undefined): string {
  const today = formatDate(new Date().toISOString(), timezone);
  return formatDate(iso, timezone) === today ? formatTime(iso, timezone) : shortDateTime(iso, timezone);
}

export function listStatus(
  item: RequestListItem,
  options: { isManager: boolean; approval?: ApprovalItem },
): ListStatus {
  const tag = requestRowTag(item.status, options);
  if (tag.tone === 'a') return { text: tag.label, accent: true };
  if (item.status === 'scheduled' && (item.en_route_at || item.visit_window_start)) {
    const time = item.visit_window_start ? visitStart(item.visit_window_start, item.timezone) : null;
    const label = item.en_route_at ? strings.requests.enRoute : tag.label;
    return { text: time ? `${label} · ${time}` : label, accent: true };
  }
  if (item.status === 'closed' && typeof item.my_review_rating === 'number') {
    return { text: strings.requests.doneRated(item.my_review_rating), accent: false };
  }
  return { text: tag.label, accent: ACTIVE_WORK.has(item.status) };
}

export function listItemDate(item: RequestListItem): string | null | undefined {
  if (item.status === 'closed') return item.closed_at ?? item.updated_at;
  if (item.status === 'cancelled') return item.cancelled_at ?? item.updated_at;
  return item.updated_at;
}

function dayKey(date: Date, timeZone: string | null | undefined): string {
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: timeZone ?? undefined,
  }).format(date);
}

export function listDate(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const key = dayKey(date, timeZone);
  if (key === dayKey(now, timeZone)) return strings.requests.dayToday;
  if (key === dayKey(new Date(now.getTime() - 86_400_000), timeZone)) return strings.requests.dayYesterday;
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: timeZone ?? undefined })
    .format(date)
    .replace('.', '');
}
