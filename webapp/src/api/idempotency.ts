import { useCallback, useRef } from 'react';
import {
  useMutation,
  type UseMutationOptions,
  type UseMutationResult,
} from '@tanstack/react-query';
import { ApiError } from './errors';

export function createIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `idk-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function fingerprintInput(value: unknown): string {
  return JSON.stringify(normalize(value));
}

function normalize(value: unknown): unknown {
  if (value === undefined) return null;
  if (typeof Blob !== 'undefined' && value instanceof Blob) {
    const file = value as Blob & { name?: string; lastModified?: number };
    return { $blob: [file.name ?? '', file.size, file.type, file.lastModified ?? 0] };
  }
  if (typeof FormData !== 'undefined' && value instanceof FormData) {
    const entries: [string, unknown][] = [];
    value.forEach((entry, key) => entries.push([key, normalize(entry)]));
    return { $form: entries };
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort())
      out[key] = normalize((value as Record<string, unknown>)[key]);
    return out;
  }
  return value;
}

export function isRetryableFailure(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  if (error.isNetworkError) return true;
  return error.status >= 500 || error.status === 408 || error.status === 429;
}

export type IdempotentMutationFn<TData, TVariables> = (
  variables: TVariables,
  idempotencyKey: string,
) => Promise<TData>;

export type IdempotentMutationOptions<TData, TError, TVariables, TContext> = Omit<
  UseMutationOptions<TData, TError, TVariables, TContext>,
  'mutationFn'
> & { mutationFn: IdempotentMutationFn<TData, TVariables> };

export type IdempotentMutationResult<TData, TError, TVariables, TContext> = UseMutationResult<
  TData,
  TError,
  TVariables,
  TContext
> & { resetIdempotencyKey: () => void };

export function useIdempotentMutation<
  TData = unknown,
  TError = Error,
  TVariables = void,
  TContext = unknown,
>(
  options: IdempotentMutationOptions<TData, TError, TVariables, TContext>,
): IdempotentMutationResult<TData, TError, TVariables, TContext> {
  const pending = useRef<{ key: string; print: string } | null>(null);
  const { mutationFn, ...rest } = options;

  const mutation = useMutation<TData, TError, TVariables, TContext>({
    ...rest,
    mutationFn: async (variables) => {
      const print = fingerprintInput(variables);
      if (!pending.current || pending.current.print !== print) {
        pending.current = { key: createIdempotencyKey(), print };
      }
      const { key } = pending.current;
      try {
        const result = await mutationFn(variables, key);
        if (pending.current?.key === key) pending.current = null;
        return result;
      } catch (error) {
        if (!isRetryableFailure(error) && pending.current?.key === key) pending.current = null;
        throw error;
      }
    },
  });

  const resetIdempotencyKey = useCallback(() => {
    pending.current = null;
  }, []);

  return { ...mutation, resetIdempotencyKey };
}
