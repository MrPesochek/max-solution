import { strings } from '../strings/ru';
import { Sheet } from '../ui/Sheet';
import { ActionButton } from '../ui/layout/ActionButton';

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  destructive,
  pending,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Sheet
      open={open}
      role="alertdialog"
      title={title}
      description={description}
      onClose={onCancel}
      locked={pending}
      actions={
        <>
          <ActionButton kind={destructive ? 'd' : 'p'} loading={pending} onClick={onConfirm}>
            {confirmLabel ?? strings.common.yes}
          </ActionButton>
          <ActionButton kind="s" disabled={pending} onClick={onCancel}>
            {cancelLabel ?? strings.common.cancel}
          </ActionButton>
        </>
      }
    />
  );
}
