import { strings } from '../../../strings/ru';
import type { Price } from '../../../api/types';
import { isPriceKnown, vatModeLabel } from '../../../lib/money';

export function priceNote(price: Price): string | null {
  if (price.amount_minor === 0 && price.zero_cost_reason) return price.zero_cost_reason;
  const vat = isPriceKnown(price) ? vatModeLabel(price.vat_mode) : null;
  return vat;
}

export function localToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export const VAT_OPTIONS = [
  { value: 'included', label: strings.workspace.vatModeOption.included },
  { value: 'excluded', label: strings.workspace.vatModeOption.excluded },
  { value: 'not_applicable', label: strings.workspace.vatModeOption.not_applicable },
];
