import { describe, expect, it } from 'vitest';
import { formatRating } from './trust';

describe('formatRating — рейтинг исполнителя (ТЗ 8.3.3)', () => {
  it('показывает число с одним знаком после запятой, когда отзывов достаточно', () => {
    expect(formatRating(4.6, null)).toBe('4.6');
    expect(formatRating(5, null)).toBe('5.0');
  });

  it('показывает метку «Мало отзывов» вместо числа, когда рейтинга ещё нет — не 0 и не 5 звёзд', () => {
    expect(formatRating(null, 'Мало отзывов')).toBe('Мало отзывов');
    expect(formatRating(undefined, 'Мало отзывов')).toBe('Мало отзывов');
  });

  it('без явной метки от сервера использует запасной текст, но не число', () => {
    expect(formatRating(null, null)).toBe('Мало отзывов');
  });
});
