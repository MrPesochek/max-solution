import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from 'react';
import { useConfirm } from '../../components/useConfirm';
import { strings } from '../../strings/ru';

interface UnsavedGuardValue {
  confirmLeave: () => Promise<boolean>;
  reset: () => void;
}

const UnsavedGuardContext = createContext<UnsavedGuardValue | null>(null);

export function UnsavedInputGuard({ children }: { children: ReactNode }) {
  const dirty = useRef(false);
  const { confirm, dialog } = useConfirm();

  const confirmLeave = useCallback(async () => {
    if (!dirty.current) return true;
    const ok = await confirm({
      title: strings.ui.unsavedTitle,
      description: strings.ui.unsavedText,
      confirmLabel: strings.ui.unsavedLeave,
      cancelLabel: strings.ui.unsavedStay,
      destructive: true,
    });
    if (ok) dirty.current = false;
    return ok;
  }, [confirm]);

  const value = useMemo<UnsavedGuardValue>(
    () => ({ confirmLeave, reset: () => (dirty.current = false) }),
    [confirmLeave],
  );

  const mark = () => {
    dirty.current = true;
  };

  return (
    <UnsavedGuardContext.Provider value={value}>
      <div className="ui-contents" onInputCapture={mark} onChangeCapture={mark}>
        {children}
      </div>
      {dialog}
    </UnsavedGuardContext.Provider>
  );
}

const PASS: UnsavedGuardValue = { confirmLeave: async () => true, reset: () => {} };

export function useUnsavedGuard(): UnsavedGuardValue {
  return useContext(UnsavedGuardContext) ?? PASS;
}
