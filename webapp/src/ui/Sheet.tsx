import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { registerBack } from './layout/backStack';

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface SheetProps {
  open: boolean;
  title?: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  role?: 'dialog' | 'alertdialog';
  actions?: ReactNode;
  children?: ReactNode;
  locked?: boolean;
}

export function Sheet({
  open,
  title,
  description,
  onClose,
  role = 'dialog',
  actions,
  children,
  locked,
}: SheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const lockedRef = useRef(locked);
  lockedRef.current = locked;
  useEffect(() => {
    if (!open) return;
    return registerBack('overlay', () => {
      if (!lockedRef.current) closeRef.current();
    });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    sheetRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => previous?.focus?.();
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      if (!locked) onClose();
      return;
    }
    if (event.key !== 'Tab' || !sheetRef.current) return;
    const focusable = Array.from(sheetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (focusable.length === 0) return;
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className="ui-sheet-overlay"
      onClick={() => {
        if (!locked) onClose();
      }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={sheetRef}
        className="ui-sheet"
        role={role}
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descriptionId : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        {(title || description) && (
          <div className="ui-sheet__head">
            {title && (
              <h2 id={titleId} className="ui-sheet__title">
                {title}
              </h2>
            )}
            {description && (
              <p id={descriptionId} className="ui-sheet__text">
                {description}
              </p>
            )}
          </div>
        )}
        {children && <div className="ui-sheet__body">{children}</div>}
        {actions && <div className="ui-sheet__actions">{actions}</div>}
      </div>
    </div>,
    document.querySelector('.ui-root') ?? document.body,
  );
}
