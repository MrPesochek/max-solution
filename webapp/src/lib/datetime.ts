import { useEffect, useState } from 'react';
import { strings } from '../strings/ru';

export function formatDateTime(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timeZone ?? undefined,
  }).format(date);
}

export function formatDate(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    timeZone: timeZone ?? undefined,
  }).format(date);
}

export function formatTime(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timeZone ?? undefined,
  }).format(date);
}

export function formatVisitWindow(
  start: string | null | undefined,
  end: string | null | undefined,
  timeZone?: string | null,
): string {
  if (!start && !end) return 'Время выезда пока не согласовано';
  if (start && !end) return `с ${formatDateTime(start, timeZone)}`;
  if (!start && end) return `до ${formatDateTime(end, timeZone)}`;
  const startDate = formatDate(start, timeZone);
  const endDate = formatDate(end, timeZone);
  if (startDate === endDate) {
    return `${startDate}, ${formatTime(start, timeZone)}–${formatTime(end, timeZone)}`;
  }
  return `${formatDateTime(start, timeZone)} — ${formatDateTime(end, timeZone)}`;
}

export function pluralRu(n: number, forms: readonly [string, string, string]): string {
  const mod10 = Math.abs(n) % 10;
  const mod100 = Math.abs(n) % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
  return forms[2];
}

function pluralize(n: number, one: string, few: string, many: string): string {
  return pluralRu(n, [one, few, many]);
}

function dayParts(date: Date, timeZone: string | null | undefined): Record<string, string> {
  const map: Record<string, string> = {};
  const format = new Intl.DateTimeFormat('ru-RU', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: timeZone ?? undefined,
  });
  for (const part of format.formatToParts(date)) map[part.type] = part.value;
  return map;
}

function dayKey(date: Date, timeZone: string | null | undefined): string {
  const p = dayParts(date, timeZone);
  return `${p.year}-${p.month}-${p.day}`;
}

export interface DayLabel {
  kind: 'today' | 'yesterday' | 'date';
  time: string;
  date: string;
}

export function dayLabel(
  iso: string | null | undefined,
  timeZone?: string | null,
  now: Date = new Date(),
): DayLabel | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const day = dayKey(date, timeZone);
  const kind =
    day === dayKey(now, timeZone)
      ? 'today'
      : day === dayKey(new Date(now.getTime() - 86_400_000), timeZone)
        ? 'yesterday'
        : 'date';
  const short = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'short',
    timeZone: timeZone ?? undefined,
  })
    .format(date)
    .replace('.', '');
  return { kind, time: formatTime(iso, timeZone), date: short };
}

export function formatCountdown(deadlineIso: string | null | undefined): { expired: boolean; label: string } {
  if (!deadlineIso) return { expired: false, label: '—' };
  const diffMs = new Date(deadlineIso).getTime() - Date.now();
  if (diffMs <= 0) return { expired: true, label: 'срок истёк' };

  const minutes = Math.floor(diffMs / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days >= 1) {
    return { expired: false, label: `${days} ${pluralize(days, 'день', 'дня', 'дней')}` };
  }
  if (hours >= 1) {
    const restMinutes = minutes % 60;
    return {
      expired: false,
      label: `${hours} ${pluralize(hours, 'час', 'часа', 'часов')} ${restMinutes} мин`,
    };
  }
  return { expired: false, label: `${Math.max(minutes, 1)} мин` };
}

export function useCountdown(deadlineIso: string | null | undefined): { expired: boolean; label: string } {
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (!deadlineIso) return;
    const interval = window.setInterval(() => forceTick((n) => n + 1), 30_000);
    return () => window.clearInterval(interval);
  }, [deadlineIso]);
  return formatCountdown(deadlineIso);
}

export function messageTime(iso: string, timeZone?: string | null, style: 'feed' | 'list' = 'feed'): string {
  const label = dayLabel(iso, timeZone);
  if (!label) return '';
  if (label.kind === 'today') return label.time;
  const day = label.kind === 'yesterday' ? strings.requests.dayYesterday : label.date;
  if (style === 'list') return day;
  return label.kind === 'yesterday' ? `${day} в ${label.time}` : `${day}, ${label.time}`;
}
