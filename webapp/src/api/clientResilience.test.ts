import { http, HttpResponse, delay } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { server } from '../mocks/server';
import { api, apiGet, apiPath, fetchAuthorizedBlob, setReauthHandler } from './client';
import { ApiError } from './errors';
import { shouldRetryQuery } from './queryClient';
import { setToken } from './tokenStore';

describe('клиент API: пути, таймауты, повторы, blob', () => {
  it('id подставляется закодированным, массив — повторяющимся параметром', async () => {
    let seen = '';
    server.use(
      http.get('/app-api/v1/__test/items/:id', ({ request }) => {
        seen = new URL(request.url).pathname + new URL(request.url).search;
        return HttpResponse.json({ ok: true });
      }),
    );
    await api.get(apiPath`/__test/items/${'a b?c'}`, { query: { status: ['draft', 'closed'], skip: null } });
    expect(seen).toBe('/app-api/v1/__test/items/a%20b%3Fc?status=draft&status=closed');
  });

  it('id с `..` или `/` не отправляется вовсе — запрос не уйдёт на чужой путь', async () => {
    const spy = vi.fn();
    server.events.on('request:start', spy);
    expect(() => apiPath`/requests/${'../../operator-api/v1/x'}`).toThrow(ApiError);
    expect(() => apiPath`/requests/${'..'}`).toThrow(ApiError);
    await expect(apiGet('/requests/{request_id}', { path: { request_id: '..' } })).rejects.toMatchObject({
      code: 'INVALID_PATH',
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it('сервер не ответил за отведённое время — ApiError TIMEOUT, считается сбоем связи', async () => {
    server.use(
      http.get('/app-api/v1/__test/slow', async () => {
        await delay(500);
        return HttpResponse.json({ ok: true });
      }),
    );
    const error = await api.get('/__test/slow', { timeoutMs: 50 }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isTimeout).toBe(true);
    expect((error as ApiError).isNetworkError).toBe(true);
  });

  it('blob вложения при 401 проходит повторный вход, как обычный запрос (регресс)', async () => {
    server.use(
      http.get('/app-api/v1/__test/file', ({ request }) =>
        request.headers.get('Authorization') === 'Bearer fresh'
          ? new HttpResponse('png', { headers: { 'Content-Type': 'image/png' } })
          : HttpResponse.json({ error: { code: 'UNAUTHORIZED', message: '', request_id: 'r' } }, { status: 401 }),
      ),
    );
    setToken('stale');
    const reauth = vi.fn(async () => {
      setToken('fresh');
      return true;
    });
    setReauthHandler(reauth);
    const blob = await fetchAuthorizedBlob('/__test/file');
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
    expect(content).toBe('png');
    expect(reauth).toHaveBeenCalledTimes(1);
  });

  it('повторяются только сбой связи и ответы сервера 5xx/408/429, но не 4xx', () => {
    const network = ApiError.network(new Error('x'));
    expect(shouldRetryQuery(0, network)).toBe(true);
    expect(shouldRetryQuery(2, network)).toBe(false);
    expect(shouldRetryQuery(0, new ApiError(503, null, ''))).toBe(true);
    expect(shouldRetryQuery(1, new ApiError(503, null, ''))).toBe(false);
    for (const status of [400, 403, 404, 409, 422]) {
      expect(shouldRetryQuery(0, new ApiError(status, null, ''))).toBe(false);
    }
    expect(shouldRetryQuery(0, ApiError.sessionExpired())).toBe(false);
  });
});
