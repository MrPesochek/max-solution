import { useState } from 'react';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';

interface TextActionSheetProps {
  open: boolean;
  title: string;
  description?: string;
  label: string;
  placeholder?: string;
  submitLabel: string;
  errorFallback: string;
  maxLength?: number;
  pending: boolean;
  onSubmit: (text: string) => Promise<unknown>;
  onClose: () => void;
  id: string;
}

export function TextActionSheet({
  open,
  title,
  description,
  label,
  placeholder,
  submitLabel,
  errorFallback,
  maxLength,
  pending,
  onSubmit,
  onClose,
  id,
}: TextActionSheetProps) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!text.trim()) return;
    setError(null);
    try {
      await onSubmit(text.trim());
      setText('');
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : errorFallback);
    }
  };

  return (
    <Sheet
      open={open}
      title={title}
      description={description}
      onClose={onClose}
      locked={pending}
      actions={
        <>
          <ActionButton loading={pending} disabled={!text.trim()} onClick={() => void submit()}>
            {submitLabel}
          </ActionButton>
          <ActionButton kind="s" disabled={pending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id={id}
        label={label}
        value={text}
        placeholder={placeholder}
        maxLength={maxLength}
        rows={3}
        onChange={setText}
        error={error ?? undefined}
      />
    </Sheet>
  );
}
