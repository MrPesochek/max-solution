import { useCallback, useRef, useState } from 'react';
import { haptics } from '../../max/bridge';
import { describeActionError, type ActionFeedbackState } from './actionErrors';

interface ActionRunnerOptions {
  onStale?: () => unknown;
  staleCodes?: ReadonlySet<string>;
  fallbackMessage?: string;
}

export interface RunOptions {
  mapError?: (error: unknown) => string | null;
}

export function useActionRunner(options: ActionRunnerOptions = {}) {
  const { onStale, staleCodes, fallbackMessage } = options;
  const [running, setRunning] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ActionFeedbackState | null>(null);
  const runningRef = useRef<string | null>(null);

  const run = useCallback(
    async <T>(name: string, action: () => Promise<T>, runOptions: RunOptions = {}): Promise<T | undefined> => {
      if (runningRef.current) return undefined;
      runningRef.current = name;
      setRunning(name);
      setFeedback(null);
      try {
        const result = await action();
        haptics.notification('success');
        return result;
      } catch (error) {
        const described = describeActionError(error, { staleCodes, fallback: fallbackMessage });
        const custom = runOptions.mapError?.(error);
        setFeedback(custom ? { kind: 'error', message: custom } : described);
        haptics.notification(described.kind === 'stale' ? 'warning' : 'error');
        if (described.kind === 'stale') await onStale?.();
        return undefined;
      } finally {
        runningRef.current = null;
        setRunning(null);
      }
    },
    [onStale, staleCodes, fallbackMessage],
  );

  const clearFeedback = useCallback(() => setFeedback(null), []);

  return {
    run,
    running,
    busy: running !== null,
    isRunning: (name: string) => running === name,
    feedback,
    clearFeedback,
  };
}

export type ActionRunner = ReturnType<typeof useActionRunner>;
