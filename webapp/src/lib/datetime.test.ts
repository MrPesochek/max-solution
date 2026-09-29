import { describe, expect, it } from 'vitest';
import { dayLabel, messageTime, pluralRu } from './datetime';

describe('даты в поясе точки', () => {
  const now = new Date('2026-09-29T19:00:00Z');

  it('сегодня и вчера считаются в поясе точки, а не браузера', () => {
    const iso = '2026-09-29T18:30:00Z';
    expect(dayLabel(iso, 'Europe/Moscow', now)).toEqual({ kind: 'today', time: '21:30', date: '29 сент' });
    expect(dayLabel(iso, 'Asia/Yekaterinburg', now)?.kind).toBe('yesterday');
  });

  it('старая дата — коротким днём; пустое и битое значение — null', () => {
    expect(dayLabel('2026-09-20T10:00:00Z', 'Europe/Moscow', now)?.kind).toBe('date');
    expect(dayLabel(null)).toBeNull();
    expect(dayLabel('не дата')).toBeNull();
  });

  it('время сообщения собирается из структуры, а не разбором текста', () => {
    const old = '2026-09-20T10:00:00Z';
    expect(messageTime(old, 'Europe/Moscow', 'list')).toBe('20 сент');
    expect(messageTime(old, 'Europe/Moscow', 'feed')).toBe('20 сент, 13:00');
  });

  it('склонение по числу', () => {
    const forms = ['день', 'дня', 'дней'] as const;
    expect([1, 2, 5, 11, 12, 14, 21, 22, 25, 111, 112].map((n) => pluralRu(n, forms))).toEqual([
      'день', 'дня', 'дней', 'дней', 'дней', 'дней', 'день', 'дня', 'дней', 'дней', 'дней',
    ]);
  });
});
