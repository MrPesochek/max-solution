export type PriceMode = 'amount' | 'unknown' | 'free';

export interface PriceFormValue {
  mode: PriceMode;
  amountRub: string;
  zeroCostReason: string;
  vatMode: string;
}

export const EMPTY_PRICE_VALUE: PriceFormValue = { mode: 'unknown', amountRub: '', zeroCostReason: '', vatMode: '' };

export function parsePositiveRub(value: string): number | null {
  const normalized = value.replace(/\s/g, '').replace(',', '.');
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null;
  const [rubles, cents = ''] = normalized.split('.');
  const minor = Number(rubles) * 100 + Number(cents.padEnd(2, '0'));
  return Number.isSafeInteger(minor) && minor > 0 ? minor : null;
}

export function priceValueToBody(value: PriceFormValue): {
  amount_minor: number | null;
  currency: string | null;
  vat_mode: string | null;
  zero_cost_reason: string | null;
} {
  if (value.mode === 'unknown') {
    return { amount_minor: null, currency: null, vat_mode: null, zero_cost_reason: null };
  }
  if (value.mode === 'free') {
    return { amount_minor: 0, currency: 'RUB', vat_mode: null, zero_cost_reason: value.zeroCostReason.trim() || null };
  }
  const amountMinor = parsePositiveRub(value.amountRub);
  return { amount_minor: amountMinor, currency: 'RUB', vat_mode: value.vatMode || null, zero_cost_reason: null };
}

export function isPriceValueValid(value: PriceFormValue): boolean {
  if (value.mode === 'unknown') return true;
  if (value.mode === 'free') return value.zeroCostReason.trim().length > 0;
  return parsePositiveRub(value.amountRub) !== null;
}
