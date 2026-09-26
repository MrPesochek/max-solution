import { strings } from '../../strings/ru';
import type { Gradient } from '../../ui/blocks/Blocks';

export function countLabel(n: number, forms: readonly [string, string, string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const form =
    mod10 === 1 && mod100 !== 11
      ? forms[0]
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? forms[1]
        : forms[2];
  return `${n} ${form}`;
}

export function ratingValue(rating: number): string {
  return rating.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function hasRating(rating: number | null | undefined): rating is number {
  return typeof rating === 'number' && rating > 0;
}

export function starsText(rating: number): string {
  return '★'.repeat(Math.max(0, Math.min(5, Math.round(rating))));
}

export function shortDate(iso: string | null | undefined, withYear = false): string {
  if (!iso) return strings.common.notSpecified;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return strings.common.notSpecified;
  const text = date.toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: withYear ? 'numeric' : undefined,
  });
  return text.replace('.', '').replace(/\s?г\.?$/, '');
}

const GRADIENTS: Gradient[] = ['p', 'b', 'r', 'o', 'g'];

export function gradientFor(id: string): Gradient {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return GRADIENTS[hash % GRADIENTS.length]!;
}
