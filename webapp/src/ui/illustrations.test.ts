import { readdirSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { ILLUSTRATIONS, ILLUSTRATION_NAMES, isIllustrationName, equipmentIllustration } from './illustrations';

const dir = path.resolve(__dirname, '../assets/illustrations');

describe('иллюстрации', () => {
  it('у холодильной камеры свой рисунок, отличный от агрегата', () => {
    expect(equipmentIllustration('split_system_cold_room')).toBe('cold-room');
    expect(equipmentIllustration(null, 'Холодильная камера')).toBe('cold-room');
    expect(equipmentIllustration('refrigeration_unit')).toBe('unit');
  });
  it('у каждого имени есть файл, у каждого файла — имя', () => {
    const files = readdirSync(dir)
      .filter((file) => file.endsWith('.svg'))
      .map((file) => file.slice(0, -4))
      .sort();
    expect([...ILLUSTRATION_NAMES].sort()).toEqual(files);
    for (const name of ILLUSTRATION_NAMES) expect(ILLUSTRATIONS[name]).toMatch(/^(?!data:).*\.svg/);
  });

  it('проверка имени', () => {
    expect(isIllustrationName('status-done')).toBe(true);
    expect(isIllustrationName('nope')).toBe(false);
  });
});
