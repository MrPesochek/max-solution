export function initials(name: string | null | undefined): string {
  if (!name) return '?';
  const words = name
    .replace(/[«»"'()]/g, ' ')
    .split(/[\s\-·,.]+/)
    .filter((w) => w && !/^(ООО|ИП|АО|ПАО|ЗАО)$/i.test(w));
  const first = words[0] ?? name;
  if (words.length >= 2) return (first[0]! + words[1]![0]!).toUpperCase();
  const caps = first.match(/[A-ZА-ЯЁ]/g);
  if (caps && caps.length >= 2) return (caps[0]! + caps[1]!).toUpperCase();
  return first.slice(0, 1).toUpperCase();
}

export function requestNo(number: number | string): string {
  return `Р-${number}`;
}

function parts(iso: string, timeZone: string | null | undefined, options: Intl.DateTimeFormatOptions) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const map: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat('ru-RU', { ...options, timeZone: timeZone ?? undefined }).formatToParts(date)) {
    map[part.type] = part.value;
  }
  return map;
}

function shortMonth(value: string | undefined): string {
  return (value ?? '').replace('.', '');
}

export function shortDateTime(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '—';
  const p = parts(iso, timeZone, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  if (!p) return '—';
  return `${p.day} ${shortMonth(p.month)}, ${p.hour}:${p.minute}`;
}

function zoneLabel(iso: string, timeZone: string | null | undefined): string {
  if (!timeZone) return '';
  if (timeZone === 'Europe/Moscow') return ' МСК';
  const p = parts(iso, timeZone, { timeZoneName: 'shortOffset' });
  const name = p?.timeZoneName?.replace('GMT', 'UTC');
  return name ? ` ${name}` : '';
}

export function visitWindowShort(
  start: string | null | undefined,
  end: string | null | undefined,
  timeZone?: string | null,
): string {
  if (!start) return '—';
  const s = parts(start, timeZone, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
  if (!s) return '—';
  const weekday = s.weekday ? s.weekday.charAt(0).toUpperCase() + s.weekday.slice(1) : '';
  const head = `${weekday} ${s.day} ${shortMonth(s.month)}, ${s.hour}:${s.minute}`.trim();
  if (!end) return `${head}${zoneLabel(start, timeZone)}`;
  const e = parts(end, timeZone, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  if (!e) return head;
  const sameDay = e.day === s.day && e.month === s.month;
  const tail = sameDay ? `${e.hour}:${e.minute}` : `${e.day} ${shortMonth(e.month)}, ${e.hour}:${e.minute}`;
  return `${head}–${tail}${zoneLabel(start, timeZone)}`;
}

export function relativeDay(iso: string | null | undefined, timeZone?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const day = (d: Date) => {
    const p = parts(d.toISOString(), timeZone, { year: 'numeric', month: '2-digit', day: '2-digit' });
    return p ? `${p.year}-${p.month}-${p.day}` : '';
  };
  const time = parts(iso, timeZone, { hour: '2-digit', minute: '2-digit' });
  const hm = time ? `${time.hour}:${time.minute}` : '';
  const now = new Date();
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (day(date) === day(now)) return `сегодня в ${hm}`;
  if (day(date) === day(yesterday)) return `вчера в ${hm}`;
  const p = parts(iso, timeZone, { day: 'numeric', month: 'short' });
  return p ? `${p.day} ${shortMonth(p.month)}` : '';
}
