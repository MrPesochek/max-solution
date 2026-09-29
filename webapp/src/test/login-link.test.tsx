import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { findHomeScreen, renderApp } from './testUtils';
import { server } from '../mocks/server';
import { rememberOpenedViaLink } from '../session/loginLink';

const TOKEN = 'demo:customer_manager:scr_organization';

function openLink(token: string) {
  window.history.replaceState(null, '', `/#/auth/link?t=${encodeURIComponent(token)}`);
}

function captureLinkBodies(): string[] {
  const bodies: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname.endsWith('/auth/link')) {
      void request
        .clone()
        .text()
        .then((text) => bodies.push(text));
    }
  });
  return bodies;
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('вход по ссылке из бота', () => {
  it('входит по токену из фрагмента и открывает экран из ссылки', async () => {
    const bodies = captureLinkBodies();
    openLink(TOKEN);
    renderApp();

    expect(window.location.href).not.toContain('customer_manager');

    expect(await screen.findByRole('button', { name: 'Изменить профиль' })).toBeInTheDocument();
    expect(window.location.hash).toBe('#/organization');
    expect(window.location.href).not.toContain('t=');
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(JSON.parse(bodies[0] ?? '{}')).toEqual({ token: TOKEN });
  });

  it('устаревшая ссылка — экран «Ссылка устарела» с переходом в чат, без демо-входа', async () => {
    vi.stubEnv('VITE_MAX_BOT_USERNAME', 'repair_bot');
    openLink('expired-token');
    renderApp();

    expect(await screen.findByText('Ссылка устарела')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Открыть чат с ботом' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Идентификатор демо-пользователя')).not.toBeInTheDocument();
    expect(window.location.href).not.toContain('expired-token');
  });

  it('повторное использование ссылки отклоняется', async () => {
    const token = 'demo:customer_manager:scr_locations';
    openLink(token);
    const first = renderApp();
    await waitFor(() => expect(window.location.hash).toBe('#/locations'));
    first.unmount();

    openLink(token);
    renderApp();
    expect(await screen.findByText('Ссылка устарела')).toBeInTheDocument();
  });

  it('перезагрузка вкладки после входа по ссылке — «откройте из чата», не демо-вход', async () => {
    rememberOpenedViaLink();
    renderApp();

    expect(await screen.findByText('Сессия истекла')).toBeInTheDocument();
    expect(screen.getByText(/Нажмите «Открыть приложение» в чате с ботом/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Идентификатор демо-пользователя')).not.toBeInTheDocument();
  });

  it('сессия по ссылке отозвана во время работы — «откройте из чата», без повторного входа', async () => {
    openLink('demo:customer_manager:scr_home');
    renderApp();
    await findHomeScreen();

    server.use(
      http.get('*/organizations/current', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'Требуется вход', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    window.location.hash = '#/organization';

    expect(await screen.findByText('Сессия истекла')).toBeInTheDocument();
  });
});
