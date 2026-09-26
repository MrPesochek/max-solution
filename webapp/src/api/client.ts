import { ApiError } from './errors';
import { createIdempotencyKey } from './idempotency';
import { getActiveMembershipId, getActiveOrganizationId } from './orgStore';
import { queryClient } from './queryClient';
import type { paths } from './schema';
import { getToken, setToken } from './tokenStore';
import type { ApiErrorBody } from './types';

const API_BASE = '/app-api/v1';
const OPERATOR_API_BASE = '/operator-api/v1';

const MUTATING_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

const DEFAULT_TIMEOUT_MS = 30_000;
const UPLOAD_TIMEOUT_MS = 120_000;

type ReauthHandler = () => Promise<boolean>;

let reauthHandler: ReauthHandler | null = null;
let reauthInFlight: Promise<boolean> | null = null;

let contextLostHandler: (() => void) | null = null;

export function setContextLostHandler(handler: (() => void) | null): void {
  contextLostHandler = handler;
}

export function setReauthHandler(handler: ReauthHandler | null): void {
  reauthHandler = handler;
}

type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, QueryValue | readonly QueryValue[]>;
  idempotencyKey?: string;
  withoutOrganization?: boolean;
  skipReauth?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
  responseType?: 'json' | 'blob';
}

export function encodePathSegment(value: string | number): string {
  const raw = String(value);
  if (raw === '' || raw === '.' || raw === '..' || /[/\\]/.test(raw)) throw ApiError.invalidPath();
  return encodeURIComponent(raw);
}

export function apiPath(strings: TemplateStringsArray, ...values: (string | number)[]): string {
  return strings.reduce(
    (path, chunk, index) => path + chunk + (index < values.length ? encodePathSegment(values[index]!) : ''),
    '',
  );
}

function setContextHeaders(headers: Headers): void {
  const membershipId = getActiveMembershipId();
  if (membershipId) headers.set('X-Membership-Id', membershipId);
  const orgId = getActiveOrganizationId();
  if (orgId) headers.set('X-Organization-Id', orgId);
}

function buildUrl(base: string, path: string, query: RequestOptions['query']): string {
  const url = new URL(base + path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      const values = Array.isArray(value) ? value : [value];
      for (const item of values as QueryValue[]) {
        if (item !== undefined && item !== null) url.searchParams.append(key, String(item));
      }
    }
  }
  return url.pathname + url.search;
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody | null> {
  try {
    const data: unknown = await response.json();
    if (
      data &&
      typeof data === 'object' &&
      'error' in data &&
      typeof (data as { error?: unknown }).error === 'object'
    ) {
      return data as ApiErrorBody;
    }
    return null;
  } catch {
    return null;
  }
}

let signalCompatible: boolean | null = null;
function fetchAcceptsSignal(signal: AbortSignal): boolean {
  if (signalCompatible === null) {
    try {
      new Request(window.location.origin, { signal });
      signalCompatible = true;
    } catch {
      signalCompatible = false;
    }
  }
  return signalCompatible;
}

class TimeoutSignal extends Error {}

async function withTimeout<T>(
  outer: AbortSignal | undefined,
  timeoutMs: number,
  run: (signal: AbortSignal | undefined) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const onAbort = () => controller.abort(outer?.reason);
  if (outer) {
    if (outer.aborted) controller.abort(outer.reason);
    else outer.addEventListener('abort', onAbort, { once: true });
  }
  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout =
    timeoutMs > 0
      ? new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            controller.abort();
            reject(new TimeoutSignal());
          }, timeoutMs);
        })
      : null;
  try {
    const signal = fetchAcceptsSignal(controller.signal) ? controller.signal : undefined;
    const work = run(signal);
    return await (timeout ? Promise.race([work, timeout]) : work);
  } catch (error) {
    if (error instanceof TimeoutSignal) throw ApiError.timeout();
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
    outer?.removeEventListener('abort', onAbort);
  }
}

async function performFetch<T>(base: string, path: string, options: RequestOptions): Promise<T> {
  const method = options.method ?? 'GET';
  const blob = options.responseType === 'blob';
  const headers = new Headers({ Accept: blob ? '*/*' : 'application/json' });

  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  if (!options.withoutOrganization) setContextHeaders(headers);

  let body: BodyInit | undefined;
  const multipart = options.body instanceof FormData;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.body);
  }

  if (MUTATING_METHODS.has(method)) {
    headers.set('Idempotency-Key', options.idempotencyKey ?? createIdempotencyKey());
  }

  return withTimeout(
    options.signal,
    options.timeoutMs ?? (multipart ? UPLOAD_TIMEOUT_MS : DEFAULT_TIMEOUT_MS),
    async (signal) => {
      let response: Response;
      try {
        response = await fetch(buildUrl(base, path, options.query), { method, headers, body, signal });
      } catch (cause) {
        if (options.signal?.aborted) throw cause;
        throw ApiError.network(cause);
      }

      if (response.status === 204) {
        return undefined as T;
      }

      if (!response.ok) {
        const errorBody = await parseErrorBody(response);
        throw new ApiError(response.status, errorBody, `Ошибка запроса (${response.status})`);
      }

      try {
        return (blob ? await response.blob() : await response.json()) as T;
      } catch (cause) {
        if (options.signal?.aborted) throw cause;
        throw ApiError.network(cause);
      }
    },
  );
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestAgainstBase<T>(API_BASE, path, options);
}

async function requestAgainstBase<T>(base: string, path: string, options: RequestOptions): Promise<T> {
  try {
    return await performFetch<T>(base, path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401 && !options.skipReauth) {
      const reauthed = await tryReauth();
      if (reauthed) {
        return performFetch<T>(base, path, options);
      }
      throw ApiError.sessionExpired();
    }
    if (error instanceof ApiError && error.isMembershipAmbiguous) contextLostHandler?.();
    throw error;
  }
}

function tryReauth(): Promise<boolean> {
  if (!reauthHandler) return Promise.resolve(false);
  if (!reauthInFlight) {
    reauthInFlight = reauthHandler().finally(() => {
      reauthInFlight = null;
    });
  }
  return reauthInFlight;
}

export function clearSession(): void {
  setToken(null);
  queryClient.clear();
}

export function fetchAuthorizedBlob(
  path: string,
  query?: RequestOptions['query'],
  signal?: AbortSignal,
): Promise<Blob> {
  return requestAgainstBase<Blob>(API_BASE, path, { query, signal, responseType: 'blob' });
}

type Options = Omit<RequestOptions, 'method' | 'body'>;

export const api = {
  get: <T>(path: string, options?: Options) => apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Options) =>
    apiRequest<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: Options) =>
    apiRequest<T>(path, { ...options, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, options?: Options) =>
    apiRequest<T>(path, { ...options, method: 'PUT', body }),
  delete: <T>(path: string, options?: Options) =>
    apiRequest<T>(path, { ...options, method: 'DELETE' }),
};

type AppPaths = {
  [K in keyof paths as K extends `${typeof API_BASE}${infer Rest}` ? Rest : never]: paths[K];
};

export type GetPath = {
  [P in keyof AppPaths]: AppPaths[P] extends { get: object } ? P : never;
}[keyof AppPaths];

type GetOp<P extends GetPath> = AppPaths[P] extends { get: infer Op } ? Op : never;

export type GetResponse<P extends GetPath> =
  GetOp<P> extends { responses: { 200: { content: { 'application/json': infer R } } } } ? R : never;

type GetQuery<P extends GetPath> = GetOp<P> extends { parameters: { query?: infer Q } } ? Q : never;
type GetPathParams<P extends GetPath> =
  GetOp<P> extends { parameters: { path: infer X } } ? X : never;

export type TypedGetOptions<P extends GetPath> = ([GetPathParams<P>] extends [never]
  ? { path?: undefined }
  : { path: GetPathParams<P> }) & {
  query?: GetQuery<P>;
  signal?: AbortSignal;
  withoutOrganization?: boolean;
};

function fillTemplate(template: string, params: Record<string, unknown> | undefined): string {
  return template.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = params?.[name];
    if (value === undefined || value === null) throw ApiError.invalidPath();
    return encodePathSegment(value as string);
  });
}

export async function apiGet<P extends GetPath>(
  template: P,
  ...[options]: [GetPathParams<P>] extends [never] ? [TypedGetOptions<P>?] : [TypedGetOptions<P>]
): Promise<GetResponse<P>> {
  const { path, query, signal, withoutOrganization } = (options ?? {}) as {
    path?: Record<string, unknown>;
    query?: RequestOptions['query'];
    signal?: AbortSignal;
    withoutOrganization?: boolean;
  };
  return apiRequest<GetResponse<P>>(fillTemplate(template, path), {
    method: 'GET',
    query,
    signal,
    withoutOrganization,
  });
}

function operatorRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestAgainstBase<T>(OPERATOR_API_BASE, path, { ...options, withoutOrganization: true });
}

export const operatorApi = {
  get: <T>(path: string, options?: Options) => operatorRequest<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Options) =>
    operatorRequest<T>(path, { ...options, method: 'POST', body }),
};

export function fetchOperatorAuthorizedBlob(
  path: string,
  query?: RequestOptions['query'],
  signal?: AbortSignal,
): Promise<Blob> {
  return operatorRequest<Blob>(path, { query, signal, responseType: 'blob' });
}
