import { ApiError } from '../../api/errors';
import { strings } from '../../strings/ru';

export type ActionFeedbackState =
  | { kind: 'stale' }
  | { kind: 'offline'; message: string }
  | { kind: 'error'; message: string };

const STALE_CODES: ReadonlySet<string> = new Set(['VERSION_CONFLICT', 'INVALID_TRANSITION']);

export function isStaleError(error: unknown, extraCodes?: ReadonlySet<string>): boolean {
  if (!(error instanceof ApiError)) return false;
  return STALE_CODES.has(error.code) || Boolean(extraCodes?.has(error.code));
}

export function isOfflineError(error: unknown): boolean {
  return error instanceof ApiError && error.isNetworkError;
}

export function describeActionError(
  error: unknown,
  options: { staleCodes?: ReadonlySet<string>; fallback?: string } = {},
): ActionFeedbackState {
  if (isStaleError(error, options.staleCodes)) return { kind: 'stale' };
  if (isOfflineError(error)) return { kind: 'offline', message: strings.actions.offlineError };
  if (error instanceof ApiError && !error.isSessionExpired) return { kind: 'error', message: error.message };
  return { kind: 'error', message: options.fallback ?? strings.actions.genericError };
}

export function actionErrorMessage(error: unknown, fallback: string): string {
  const described = describeActionError(error, { fallback });
  return described.kind === 'stale' ? strings.actions.staleDescription : described.message;
}
