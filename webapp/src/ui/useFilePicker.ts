import { useRef, type ChangeEvent } from 'react';
import { IMAGE_ACCEPT, MAX_ATTACHMENT_BYTES } from '../lib/attachments';

export interface FilePickerOptions {
  accept?: string;
  maxBytes?: number;
  onFile: (file: File) => void;
  onTooLarge?: (file: File) => void;
}

export function useFilePicker({ accept = IMAGE_ACCEPT, maxBytes = MAX_ATTACHMENT_BYTES, onFile, onTooLarge }: FilePickerOptions) {
  const ref = useRef<HTMLInputElement | null>(null);
  const onChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > maxBytes) {
      onTooLarge?.(file);
      return;
    }
    onFile(file);
  };
  return {
    open: () => ref.current?.click(),
    inputProps: { ref, type: 'file' as const, accept, hidden: true, onChange },
  };
}
