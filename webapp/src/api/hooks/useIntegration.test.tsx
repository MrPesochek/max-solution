import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { server } from '../../mocks/server';
import { setActiveContext } from '../orgStore';
import { useCreateApiKey } from './useIntegration';

describe('одноразовый секрет', () => {
  it('ключ отдаётся экрану результатом вызова, в кэше мутаций не остаётся, в буфер не копируется', async () => {
    setActiveContext({ membershipId: 'mem_1', organizationId: 'org_1' });
    server.use(
      http.post('/app-api/v1/integration/api-keys', () =>
        HttpResponse.json({ id: 'k1', key: 'key_live_secret', prefix: 'key_live' }, { status: 201 }),
      ),
    );
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const writes: string[] = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async (text: string) => void writes.push(text) },
    });
    const { result } = renderHook(() => useCreateApiKey(), { wrapper });

    let issued: { key: string } | undefined;
    await act(async () => {
      issued = await result.current.mutateAsync({ name: 'CRM', scopes: ['requests:read'] });
    });

    expect(issued?.key).toBe('key_live_secret');
    expect(result.current.data).toBeUndefined();
    await waitFor(() =>
      expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.data))).not.toContain(
        'key_live_secret',
      ),
    );
    expect(writes).toEqual([]);
  });
});
