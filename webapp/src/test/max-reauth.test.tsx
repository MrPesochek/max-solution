import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { renderApp, findHomeScreen } from './testUtils';
import { server } from '../mocks/server';
import { queryClient } from '../api/queryClient';

const INIT_DATA = 'demo:customer_manager';

function openFromChat(initData = INIT_DATA) {
  window.WebApp = { initData };
}

function countAuthCalls(): { count: number } {
  const counter = { count: 0 };
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/auth/max'))
      counter.count += 1;
  });
  return counter;
}

const initDataInvalid = () =>
  HttpResponse.json(
    { error: { code: 'INIT_DATA_INVALID', message: 'Вход недоступен', request_id: 'r' } },
    { status: 401 },
  );

const sessionRevoked = () =>
  HttpResponse.json(
    { error: { code: 'UNAUTHENTICATED', message: 'Требуется вход', request_id: 'r' } },
    { status: 401 },
  );

describe('вход по initData мини-приложения', () => {
  it('отказ по initData при запуске — сразу «откройте заново», без кнопки повтора и без повторных входов', async () => {
    server.use(http.post('*/auth/max', initDataInvalid));
    const calls = countAuthCalls();
    openFromChat();
    renderApp();

    expect(await screen.findByText('Сессия истекла')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
    expect(calls.count).toBe(1);
  });

  it('сбой сервера при запуске — экран с кнопкой повтора, повтор входит', async () => {
    server.use(
      http.post('*/auth/max', () => new HttpResponse('Service Unavailable', { status: 503 }), {
        once: true,
      }),
    );
    const user = userEvent.setup();
    openFromChat();
    renderApp();

    expect(await screen.findByText('Сервис временно недоступен')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    await findHomeScreen();
  });

  it('401 во время работы — один повторный вход по тому же initData, исходный запрос повторяется', async () => {
    const calls = countAuthCalls();
    openFromChat();
    renderApp();
    await findHomeScreen();

    server.use(http.get('*/organizations/current', sessionRevoked, { once: true }));
    window.location.hash = '#/organization';
    await screen.findByRole('button', { name: 'Изменить профиль' });
    expect(calls.count).toBe(2);
  });

  it('повторный вход отклонён (initData истёк) — reopen_required, дальше вход не повторяется', async () => {
    const calls = countAuthCalls();
    openFromChat();
    renderApp();
    await findHomeScreen();

    server.use(
      http.post('*/auth/max', initDataInvalid),
      http.get('*/organizations/current', sessionRevoked),
    );
    window.location.hash = '#/organization';

    expect(await screen.findByText('Сессия истекла')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
    expect(calls.count).toBe(2);
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });
});
