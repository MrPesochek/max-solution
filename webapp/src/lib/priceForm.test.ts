import { describe, expect, it } from 'vitest';
import { EMPTY_PRICE_VALUE, isPriceValueValid, parsePositiveRub, priceValueToBody } from './priceForm';

describe('денежные поля предложений, выезда и сметы', () => {
  it.each(['1500abc', '12,3,4', '1e3', '0.001', '-10', '', '0', '999999999999999999'])('не принимает некорректную сумму %s', (amountRub) => {
    const value = { ...EMPTY_PRICE_VALUE, mode: 'amount' as const, amountRub };
    expect(isPriceValueValid(value)).toBe(false);
    expect(priceValueToBody(value).amount_minor).toBeNull();
  });
  it.each([['1 500,25', 150025], ['12.3', 1230], ['0,01', 1], ['100', 10000]])('переводит %s в копейки без потери точности', (input, minor) => {
    expect(parsePositiveRub(input)).toBe(minor);
  });
  it('сохраняет различие между неизвестной ценой и бесплатной работой с основанием', () => {
    expect(priceValueToBody(EMPTY_PRICE_VALUE).amount_minor).toBeNull();
    expect(isPriceValueValid({ ...EMPTY_PRICE_VALUE, mode: 'free' })).toBe(false);
    const free = { ...EMPTY_PRICE_VALUE, mode: 'free' as const, zeroCostReason: 'Гарантия' };
    expect(isPriceValueValid(free)).toBe(true);
    expect(priceValueToBody(free).amount_minor).toBe(0);
  });
});
