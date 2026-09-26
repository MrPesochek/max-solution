const WEIGHTS_10 = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const WEIGHTS_12_N11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const WEIGHTS_12_N12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

function weightedChecksum(digits: number[], weights: number[]): number {
  const sum = weights.reduce((acc, weight, index) => acc + weight * (digits[index] ?? 0), 0);
  return (sum % 11) % 10;
}

export function isInnFormat(raw: string): boolean {
  const value = raw.trim();
  return /^\d{10}$/.test(value) || /^\d{12}$/.test(value);
}

export function isValidInn(raw: string): boolean {
  const value = raw.trim();
  if (!isInnFormat(value)) return false;
  const digits = value.split('').map(Number);

  if (digits.length === 10) {
    return weightedChecksum(digits.slice(0, 9), WEIGHTS_10) === digits[9];
  }
  return (
    weightedChecksum(digits.slice(0, 10), WEIGHTS_12_N11) === digits[10] &&
    weightedChecksum(digits.slice(0, 11), WEIGHTS_12_N12) === digits[11]
  );
}

export type InnSubjectKind = 'organization' | 'individual';

export function innSubjectKind(raw: string): InnSubjectKind | null {
  const value = raw.trim();
  if (/^\d{10}$/.test(value)) return 'organization';
  if (/^\d{12}$/.test(value)) return 'individual';
  return null;
}
