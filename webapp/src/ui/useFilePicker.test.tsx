import { act, renderHook } from '@testing-library/react';
import type { ChangeEvent } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MAX_ATTACHMENT_BYTES } from '../lib/attachments';
import { useFilePicker } from './useFilePicker';

function pick(onChange: (e: ChangeEvent<HTMLInputElement>) => void, file: File) {
  const target = { files: [file], value: 'C:\\fakepath\\x' } as unknown as HTMLInputElement;
  onChange({ target } as unknown as ChangeEvent<HTMLInputElement>);
  return target;
}

describe('useFilePicker', () => {
  it('файл в пределах лимита отдаётся экрану, поле сбрасывается для повторного выбора', () => {
    const onFile = vi.fn();
    const { result } = renderHook(() => useFilePicker({ onFile }));
    const file = new File(['x'], 'a.jpg', { type: 'image/jpeg' });
    let target: HTMLInputElement | undefined;
    act(() => {
      target = pick(result.current.inputProps.onChange, file);
    });
    expect(onFile).toHaveBeenCalledWith(file);
    expect(target?.value).toBe('');
    expect(result.current.inputProps.accept).toContain('image/');
  });

  it('файл больше 10 МБ не загружается — вместо этого причина', () => {
    const onFile = vi.fn();
    const onTooLarge = vi.fn();
    const { result } = renderHook(() => useFilePicker({ onFile, onTooLarge }));
    const big = new File(['x'], 'big.jpg', { type: 'image/jpeg' });
    Object.defineProperty(big, 'size', { value: MAX_ATTACHMENT_BYTES + 1 });
    act(() => void pick(result.current.inputProps.onChange, big));
    expect(onFile).not.toHaveBeenCalled();
    expect(onTooLarge).toHaveBeenCalledWith(big);
  });
});
