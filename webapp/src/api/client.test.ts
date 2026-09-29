import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { server } from '../mocks/server';
import { api, setReauthHandler } from './client';
import { ApiError } from './errors';
import { setToken } from './tokenStore';
import { setActiveContext } from './orgStore';

describe('api client', () => {
  it('шлёт Idempotency-Key только для мутаций, а не для GET', async () => {
    let postHeader: string | null = null;
    let getHeader: string | null = null;

    server.use(
      http.post('/app-api/v1/__test/echo', ({ request }) => {
        postHeader = request.headers.get('Idempotency-Key');
        return HttpResponse.json({ ok: true });
      }),
      http.get('/app-api/v1/__test/echo', ({ request }) => {
        getHeader = request.headers.get('Idempotency-Key');
        return HttpResponse.json({ ok: true });
      }),
    );

    await api.post('/__test/echo', { a: 1 });
    await api.get('/__test/echo');

    expect(postHeader).toMatch(/^[0-9a-f-]{10,}$/i);
    expect(getHeader).toBeNull();
  });

  it('повторяет вход по initData один раз при 401 и повторяет исходный запрос', async () => {
    server.use(
      http.get('/app-api/v1/__test/protected', ({ request }) => {
        const auth = request.headers.get('Authorization');
        if (auth === 'Bearer valid-token') return HttpResponse.json({ ok: true });
        return HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'нет токена', request_id: 'r1' } },
          { status: 401 },
        );
      }),
    );

    const reauth = vi.fn(async () => {
      setToken('valid-token');
      return true;
    });
    setReauthHandler(reauth);

    const result = await api.get<{ ok: boolean }>('/__test/protected');

    expect(result.ok).toBe(true);
    expect(reauth).toHaveBeenCalledTimes(1);
  });

  it('выдаёт SESSION_EXPIRED, если повторный вход не удался', async () => {
    server.use(
      http.get('/app-api/v1/__test/protected', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'нет токена', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
    );

    setReauthHandler(async () => false);

    expect.assertions(2);
    try {
      await api.get('/__test/protected');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).isSessionExpired).toBe(true);
    }
  });

  it('сбой связи при повторном входе отдаётся запросу как есть, а не как SESSION_EXPIRED', async () => {
    server.use(
      http.get('/app-api/v1/__test/protected', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHORIZED', message: 'нет токена', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
    );
    setReauthHandler(async () => {
      throw ApiError.network(new Error('offline'));
    });

    await expect(api.get('/__test/protected')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });

  it('401 от самого входа не запускает повторный вход', async () => {
    server.use(
      http.post('/app-api/v1/__test/login', () =>
        HttpResponse.json(
          { error: { code: 'INIT_DATA_INVALID', message: 'Вход недоступен', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
    );
    const reauth = vi.fn(async () => true);
    setReauthHandler(reauth);

    await expect(api.post('/__test/login', {}, { skipReauth: true })).rejects.toMatchObject({
      code: 'INIT_DATA_INVALID',
    });
    expect(reauth).not.toHaveBeenCalled();
  });

  it('прокидывает VERSION_CONFLICT с деталями актуальной версии', async () => {
    server.use(
      http.patch('/app-api/v1/__test/versioned', () =>
        HttpResponse.json(
          {
            error: {
              code: 'VERSION_CONFLICT',
              message: 'Заявка изменена',
              request_id: 'r2',
              details: { current_version: 8 },
            },
          },
          { status: 409 },
        ),
      ),
    );

    expect.assertions(3);
    try {
      await api.patch('/__test/versioned', {});
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.isVersionConflict).toBe(true);
      expect(apiError.details).toEqual({ current_version: 8 });
    }
  });

  it('оборачивает сетевую ошибку в ApiError с кодом NETWORK_ERROR', async () => {
    server.use(
      http.get('/app-api/v1/__test/network-fail', () => HttpResponse.error()),
    );

    expect.assertions(2);
    try {
      await api.get('/__test/network-fail');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).isNetworkError).toBe(true);
    }
  });

  it('шлёт X-Membership-Id активного членства и X-Organization-Id для совместимости', async () => {
    let headers: Headers | null = null;
    server.use(
      http.get('/app-api/v1/__test/context', ({ request }) => {
        headers = request.headers;
        return HttpResponse.json({ ok: true });
      }),
    );
    setActiveContext({ membershipId: 'mem_1', organizationId: 'org_1' });
    await api.get('/__test/context');
    expect(headers!.get('X-Membership-Id')).toBe('mem_1');
    expect(headers!.get('X-Organization-Id')).toBe('org_1');
  });

  it('известные коды ошибок получают человеческий текст, 503/413/429 — даже без конверта ошибки', async () => {
    server.use(
      http.post('/app-api/v1/__test/secret', () =>
        HttpResponse.json(
          { error: { code: 'IDEMPOTENT_SECRET_NOT_REPLAYABLE', message: 'raw', request_id: 'r' } },
          { status: 409 },
        ),
      ),
      http.get('/app-api/v1/__test/down', () => new HttpResponse('Service Unavailable', { status: 503 })),
      http.get('/app-api/v1/__test/busy', () => new HttpResponse(null, { status: 429 })),
      http.post('/app-api/v1/__test/big', () => new HttpResponse('too big', { status: 413 })),
    );

    const caught = async (promise: Promise<unknown>) => {
      try {
        await promise;
      } catch (error) {
        return error as ApiError;
      }
      throw new Error('ожидалась ошибка');
    };

    const secret = await caught(api.post('/__test/secret', {}));
    expect(secret.message).toBe(
      'Ключ уже выдан, повторно показать его нельзя. При необходимости перевыпустите ключ.',
    );

    const down = await caught(api.get('/__test/down'));
    expect(down.code).toBe('SERVICE_UNAVAILABLE');
    expect(down.isServiceUnavailable).toBe(true);
    expect(down.message).toBe('Сервис временно недоступен. Попробуйте повторить чуть позже.');

    const busy = await caught(api.get('/__test/busy'));
    expect(busy.isRateLimited).toBe(true);
    expect(busy.message).toBe('Слишком много попыток, попробуйте позже.');

    const big = await caught(api.post('/__test/big', {}));
    expect(big.code).toBe('PAYLOAD_TOO_LARGE');
  });
});
