import { strings } from '../../../strings/ru';

export interface VisitSlot {
  id: string;
  label: string;
  start: string;
  end: string;
}

export const SLOT_WINDOW_HOURS = 2;

interface WallTime {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function wallTime(date: Date, timeZone: string | undefined): WallTime {
  const map: Record<string, number> = {};
  const format = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  for (const part of format.formatToParts(date)) {
    if (part.type !== 'literal') map[part.type] = Number(part.value);
  }
  return {
    year: map.year ?? 1970,
    month: map.month ?? 1,
    day: map.day ?? 1,
    hour: map.hour ?? 0,
    minute: map.minute ?? 0,
  };
}

function zonedDate(time: WallTime, timeZone: string | undefined): Date {
  const guess = Date.UTC(time.year, time.month - 1, time.day, time.hour, time.minute);
  const seen = wallTime(new Date(guess), timeZone);
  const offset = Date.UTC(seen.year, seen.month - 1, seen.day, seen.hour, seen.minute) - guess;
  return new Date(guess - offset);
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

export function visitSlots(timeZone: string | null | undefined, now = new Date()): VisitSlot[] {
  const tz = timeZone ?? undefined;
  const today = wallTime(now, tz);
  const tomorrowNoon = wallTime(
    new Date(zonedDate({ ...today, hour: 12, minute: 0 }, tz).getTime() + 86_400_000),
    tz,
  );
  const slots: { day: 'today' | 'tomorrow'; date: WallTime }[] = [];

  const soonMinutes = today.hour * 60 + today.minute + 120;
  const rounded = Math.ceil(soonMinutes / 30) * 30;
  if (rounded <= 19 * 60) {
    slots.push({
      day: 'today',
      date: { ...today, hour: Math.floor(rounded / 60), minute: rounded % 60 },
    });
  }
  if (rounded < 17 * 60) slots.push({ day: 'today', date: { ...today, hour: 17, minute: 0 } });
  slots.push({ day: 'tomorrow', date: { ...tomorrowNoon, hour: 10, minute: 0 } });
  slots.push({ day: 'tomorrow', date: { ...tomorrowNoon, hour: 15, minute: 0 } });

  return slots.map(({ day, date }) => {
    const start = zonedDate(date, tz);
    const end = new Date(start.getTime() + SLOT_WINDOW_HOURS * 3_600_000);
    const time = `${pad(date.hour)}:${pad(date.minute)}`;
    return {
      id: `${day}-${time}`,
      label:
        day === 'today' ? strings.workspace.slotToday(time) : strings.workspace.slotTomorrow(time),
      start: start.toISOString(),
      end: end.toISOString(),
    };
  });
}
