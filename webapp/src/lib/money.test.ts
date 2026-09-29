import { describe, expect, it } from 'vitest';
import { formatAmountMinor, formatPrice, isPriceKnown } from './money';
import type { Price } from '../api/types';

describe('формат денег (минимальные единицы, без ошибок float)', () => {
  it('переводит копейки в рубли без остатка ошибок плавающей точки', () => {
    expect(formatAmountMinor(10, 'RUB')).toBe('0,10 ₽');
    expect(formatAmountMinor(30, 'RUB')).toBe('0,30 ₽');
    expect(formatAmountMinor(123456, 'RUB')).toBe('1 234,56 ₽');
    expect(formatAmountMinor(100, 'RUB')).toBe('1 ₽');
  });

  it('показывает отрицательные значения с минусом впереди суммы', () => {
    expect(formatAmountMinor(-500, 'RUB')).toBe('−5 ₽');
  });

  it('null-цена (amount_minor=null) — «требует уточнения», а не 0', () => {
    const unknown: Price = { amount_minor: null, currency: null, vat_mode: null, zero_cost_reason: null, is_known: false };
    expect(isPriceKnown(unknown)).toBe(false);
    expect(formatPrice(unknown)).toBe('Цена требует уточнения');
  });

  it('явный 0 — известная бесплатная цена, отличная от null', () => {
    const free: Price = {
      amount_minor: 0,
      currency: 'RUB',
      vat_mode: null,
      zero_cost_reason: 'Гарантийный случай',
      is_known: true,
    };
    expect(isPriceKnown(free)).toBe(true);
    expect(formatPrice(free)).toBe('0 ₽');
  });
});
