import { strings } from '../strings/ru';
import type { ApiErrorBody } from './types';

const CODE_MESSAGES: Readonly<Record<string, string>> = strings.errorCodes;

const STATUS_CODES: Readonly<Record<number, string>> = {
  413: 'PAYLOAD_TOO_LARGE',
  429: 'RATE_LIMITED',
  503: 'SERVICE_UNAVAILABLE',
};

function messageFor(code: string, body: ApiErrorBody | null, fallback: string): string {
  return CODE_MESSAGES[code] ?? body?.error.message ?? fallback;
}

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown> | undefined;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody | null, fallbackMessage: string, codeOverride?: string) {
    const code = codeOverride ?? body?.error.code ?? STATUS_CODES[status] ?? 'UNKNOWN_ERROR';
    super(messageFor(code, body, fallbackMessage));
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = body?.error.request_id ?? null;
    this.details = body?.error.details;
  }

  get isVersionConflict(): boolean {
    return this.status === 409 && this.code === 'VERSION_CONFLICT';
  }

  get isNetworkError(): boolean {
    return this.code === 'NETWORK_ERROR' || this.code === 'TIMEOUT';
  }

  get isTimeout(): boolean {
    return this.code === 'TIMEOUT';
  }

  get isSessionExpired(): boolean {
    return this.code === 'SESSION_EXPIRED';
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }

  get isServiceUnavailable(): boolean {
    return this.status === 503;
  }

  get isMembershipAmbiguous(): boolean {
    return this.status === 409 && this.code === 'MEMBERSHIP_AMBIGUOUS';
  }

  static network(cause: unknown): ApiError {
    const err = new ApiError(0, null, 'Нет соединения с сервером', 'NETWORK_ERROR');
    if (cause instanceof Error) err.cause = cause;
    return err;
  }

  static timeout(): ApiError {
    return new ApiError(0, null, 'Сервер не ответил вовремя. Проверьте соединение и повторите', 'TIMEOUT');
  }

  static invalidPath(): ApiError {
    return new ApiError(400, null, 'Некорректная ссылка', 'INVALID_PATH');
  }

  static sessionExpired(): ApiError {
    return new ApiError(401, null, 'Сессия недействительна', 'SESSION_EXPIRED');
  }
}
