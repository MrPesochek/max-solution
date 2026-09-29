import { describe, expect, it } from 'vitest';
import { innSubjectKind, isInnFormat, isValidInn } from './inn';

describe('isValidInn', () => {
  it('принимает корректный ИНН организации (10 цифр)', () => {
    expect(isValidInn('7707083893')).toBe(true);
  });

  it('принимает корректный ИНН физического лица (12 цифр)', () => {
    expect(isValidInn('500100732259')).toBe(true);
  });

  it('отклоняет ИНН с неверной контрольной цифрой', () => {
    expect(isValidInn('7707083894')).toBe(false);
    expect(isValidInn('500100732250')).toBe(false);
  });

  it('отклоняет неверный формат', () => {
    expect(isValidInn('123')).toBe(false);
    expect(isValidInn('770708389a')).toBe(false);
    expect(isValidInn('')).toBe(false);
  });
});

describe('isInnFormat', () => {
  it('проверяет только длину и цифры, без контрольной суммы', () => {
    expect(isInnFormat('1234567890')).toBe(true);
    expect(isInnFormat('123456789012')).toBe(true);
    expect(isInnFormat('12345')).toBe(false);
  });
});

describe('innSubjectKind', () => {
  it('различает организацию и физлицо по длине', () => {
    expect(innSubjectKind('7707083893')).toBe('organization');
    expect(innSubjectKind('500100732259')).toBe('individual');
    expect(innSubjectKind('123')).toBeNull();
  });
});
