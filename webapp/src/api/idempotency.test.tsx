import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import { api } from './client';
import { useIdempotentMutation } from './idempotency';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function scriptedEndpoint(outcomes: ('network' | 'ok' | 'bad_request' | 'server_error')[]) {
  const keys: (string | null)[] = [];
  server.use(
    http.post('*/app-api/v1/__test/idempotent', ({ request }) => {
      keys.push(request.headers.get('Idempotency-Key'));
      const outcome = outcomes.shift() ?? 'ok';
      if (outcome === 'network') return HttpResponse.error();
      if (outcome === 'bad_request') {
        return HttpResponse.json(
          { error: { code: 'VALIDATION_FAILED', message: 'Ошибка', request_id: 'r' } },
          { status: 422 },
        );
      }
      if (outcome === 'server_error') return new HttpResponse(null, { status: 503 });
      return HttpResponse.json({ ok: true }, { status: 201 });
    }),
  );
  return keys;
}

function useTestMutation() {
  return useIdempotentMutation({
    mutationFn: (input: { value: string }, idempotencyKey) =>
      api.post<{ ok: boolean }>('/__test/idempotent', input, { idempotencyKey }),
  });
}

async function attempt(result: { current: ReturnType<typeof useTestMutation> }, value: string) {
  await act(async () => {
    await result.current.mutateAsync({ value }).catch(() => undefined);
  });
}

describe('стабильный Idempotency-Key на логическое действие', () => {
  it('повтор после обрыва сети и 5xx уходит с тем же ключом, после успеха — новый', async () => {
    const keys = scriptedEndpoint(['network', 'server_error', 'ok', 'ok']);
    const { result } = renderHook(() => useTestMutation(), { wrapper });

    await attempt(result, 'a');
    await attempt(result, 'a');
    await attempt(result, 'a');
    await attempt(result, 'a');

    expect(keys).toHaveLength(4);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).toBe(keys[0]);
    expect(keys[3]).not.toBe(keys[0]);
  });

  it('изменение входных данных или окончательный отказ сервера дают новый ключ', async () => {
    const keys = scriptedEndpoint(['network', 'network', 'bad_request', 'ok']);
    const { result } = renderHook(() => useTestMutation(), { wrapper });

    await attempt(result, 'a');
    await attempt(result, 'b');
    await attempt(result, 'b');
    await attempt(result, 'b');

    expect(keys[1]).not.toBe(keys[0]);
    expect(keys[2]).toBe(keys[1]);
    expect(keys[3]).not.toBe(keys[2]);
  });

  it('ключ можно сбросить явно — например, при повторном открытии формы', async () => {
    const keys = scriptedEndpoint(['network', 'ok']);
    const { result } = renderHook(() => useTestMutation(), { wrapper });

    await attempt(result, 'a');
    act(() => result.current.resetIdempotencyKey());
    await attempt(result, 'a');

    expect(keys[1]).not.toBe(keys[0]);
  });
});
