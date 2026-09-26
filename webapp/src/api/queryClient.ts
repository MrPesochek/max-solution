import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './errors';

export const POLL_INTERVAL_MS = 20_000;

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (!(error instanceof ApiError)) return failureCount < 1;
  if (error.isSessionExpired) return false;
  if (error.isNetworkError) return failureCount < 2;
  if (error.status >= 500 || error.status === 408 || error.status === 429) return failureCount < 1;
  return false;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetryQuery,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});
