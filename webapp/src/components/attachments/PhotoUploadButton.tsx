import { useRef, type ChangeEvent } from 'react';
import { Button, type ButtonProps } from '@maxhub/max-ui';

interface PhotoUploadButtonProps {
  label: string;
  onFile: (file: File) => void;
  disabled?: boolean;
  accept?: string;
  variant?: ButtonProps['variant'];
  size?: ButtonProps['size'];
}

export function PhotoUploadButton({
  label,
  onFile,
  disabled,
  accept = 'image/*',
  variant = 'secondary',
  size = 'small',
}: PhotoUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) onFile(file);
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        aria-label={label}
        onChange={handleChange}
      />
      <Button
        type="button"
        size={size}
        variant={variant}
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        {label}
      </Button>
    </>
  );
}
