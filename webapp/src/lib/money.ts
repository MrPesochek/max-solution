import type { Price } from '../api/types';
import { strings } from '../strings/ru';

const CURRENCY_SYMBOLS: Record<string, string> = { RUB: '₽' };

export function formatAmountMinor(amountMinor: number, currency: string | null = 'RUB'): string {
  const negative = amountMinor < 0;
  const abs = Math.abs(Math.trunc(amountMinor));
  const units = Math.trunc(abs / 100);
  const cents = abs % 100;
  const unitsText = units.toLocaleString('ru-RU');
  const symbol = currency ? (CURRENCY_SYMBOLS[currency] ?? `${currency} `) : '';
  const amountText = cents === 0 ? unitsText : `${unitsText},${String(cents).padStart(2, '0')}`;
  return `${negative ? '−' : ''}${amountText}${symbol ? ' ' + symbol : ''}`;
}

export function isPriceKnown(price: Price | null | undefined): price is Price & { amount_minor: number } {
  return Boolean(price?.is_known) && price?.amount_minor !== null && price?.amount_minor !== undefined;
}

export function formatPrice(price: Price | null | undefined): string {
  if (!isPriceKnown(price)) return strings.money.priceUnknown;
  return formatAmountMinor(price.amount_minor, price.currency);
}

export function vatModeLabel(vatMode: string | null | undefined): string | null {
  switch (vatMode) {
    case 'included':
      return strings.money.vatIncluded;
    case 'excluded':
      return strings.money.vatExcluded;
    case 'not_applicable':
      return strings.money.vatNotApplicable;
    default:
      return null;
  }
}
