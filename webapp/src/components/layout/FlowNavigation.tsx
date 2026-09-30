import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react';

type ExitGuard = () => Promise<boolean>;
const FlowNavigationContext = createContext<{ guard: { current: ExitGuard | null } } | null>(null);

export function FlowNavigationProvider({ children }: { children: ReactNode }) {
  const guard = useRef<ExitGuard | null>(null);
  return (
    <FlowNavigationContext.Provider value={{ guard }}>{children}</FlowNavigationContext.Provider>
  );
}

export function FlowExitGuard({ save }: { save: ExitGuard }) {
  const context = useContext(FlowNavigationContext);
  useEffect(() => {
    if (!context) return;
    context.guard.current = save;
    return () => {
      if (context.guard.current === save) context.guard.current = null;
    };
  }, [context, save]);
  return null;
}

export function useFlowNavigation() {
  const context = useContext(FlowNavigationContext);
  return async () => (context?.guard.current ? context.guard.current() : true);
}
