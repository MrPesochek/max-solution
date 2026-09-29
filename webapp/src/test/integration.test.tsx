import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { IntegrationSummary } from '../api/types';

describe('интеграция: ключи, подписки, доставки (ТЗ 5.2, 10.1, 11)', () => {
  it('диспетчер не видит раздел «Интеграция» в навигации и не может открыть его напрямую', async () => {
    renderApp();
    await loginAsDemo('provider_active_dispatcher');

    await screen.findByRole('link', { name: 'Профиль' });
    expect(screen.queryByRole('link', { name: 'Интеграция' })).not.toBeInTheDocument();

    window.location.hash = '#/integration';
    await screen.findByText('Нет доступа');
  });

  it('администратор создаёт ключ, видит его один раз, затем — только префикс', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('link', { name: /Интеграция с CRM/ }));
    await screen.findByRole('heading', { name: 'Интеграция' });
    await screen.findByText('CRM подключена');
    expect(screen.getByText('key_live_demo1••••')).toBeInTheDocument();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();

    await user.click(await screen.findByRole('link', { name: /API-ключи/ }));
    await screen.findByText('CRM продакшн');
    expect(screen.getByText(/key_live_demo1/)).toBeInTheDocument();
    expect(screen.queryByText('key_live_demo1_seed_not_shown_again')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Создать ключ' }));
    await user.type(await screen.findByLabelText('Название ключа'), 'Тестовая интеграция');
    const create = screen.getByRole('button', { name: 'Создать ключ' });
    expect(create).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: 'requests:read' }));
    expect(screen.queryByRole('checkbox', { name: 'service_bindings:write' })).not.toBeInTheDocument();
    await user.click(create);

    await screen.findByText('Ключ показывается один раз');
    expect(
      screen.getByText(
        'Сохраните его в CRM. Потом увидеть ключ будет нельзя, только выпустить новый.',
      ),
    ).toBeInTheDocument();
    const keyInput = screen.getByDisplayValue(/key_live_/) as HTMLInputElement;
    const fullKey = keyInput.value;
    expect(fullKey.length).toBeGreaterThan(10);

    await user.click(screen.getByRole('button', { name: 'Скопировал, закрыть' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Закрыть' }));
    expect(screen.queryByDisplayValue(fullKey)).not.toBeInTheDocument();
    expect(screen.getByText('Тестовая интеграция')).toBeInTheDocument();
  });

  it('справка для интегратора содержит подпись, идемпотентность и восстановление через /events', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('link', { name: /Интеграция с CRM/ }));
    await screen.findByRole('heading', { name: 'Интеграция' });
    await user.click(screen.getByRole('link', { name: 'Справка для интегратора' }));

    expect(screen.getByText(/X-Signature/)).toBeInTheDocument();
    expect(screen.getByText(/Idempotency-Key/)).toBeInTheDocument();
    expect(screen.getByText(/\/events/)).toBeInTheDocument();
  });

  it('заблокированную доставку можно повторить', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('link', { name: /Интеграция с CRM/ }));
    await screen.findByRole('heading', { name: 'Интеграция' });
    await screen.findByText('Есть ошибки доставки');
    await user.click(screen.getByRole('link', { name: 'Журнал доставки' }));

    await user.click(await screen.findByRole('button', { name: 'request.changed: Заблокировано' }));
    const sheet = await screen.findByRole('dialog');
    await user.click(within(sheet).getByRole('button', { name: 'Повторить доставку' }));
    await waitFor(() => {
      expect(
        screen.queryByRole('button', { name: 'request.changed: Заблокировано' }),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'request.changed: Доставлено' })).toBeInTheDocument();
  });
});

async function openIntegration(user: ReturnType<typeof userEvent.setup>) {
  renderApp();
  await loginAsDemo('provider_active_admin');
  await user.click(await screen.findByRole('link', { name: 'Профиль' }));
  await user.click(await screen.findByRole('link', { name: /Интеграция с CRM/ }));
  await screen.findByRole('heading', { name: 'Интеграция' });
}

describe('интеграция: сводка и подключение CRM (12d, K-11, K-12)', () => {
  it('сводка — из /integration/summary: события за сутки, ошибки, вебхук', async () => {
    const auth = await demoLoginRaw('provider_active_admin');
    const summary = await apiCall<IntegrationSummary>('/integration/summary', auth);
    const user = userEvent.setup();
    await openIntegration(user);

    await screen.findByText('CRM подключена');
    expect(
      screen.getByText(
        `${summary.deliveries_24h.total} · ошибок ${summary.deliveries_24h.failed}`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('crm.example-service.local/webhooks/repairbot')).toBeInTheDocument();
  });

  it('«Отключить интеграцию» отключает подписку, «Включить» — возвращает', async () => {
    const user = userEvent.setup();
    await openIntegration(user);

    await user.click(await screen.findByRole('button', { name: 'Отключить интеграцию' }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Отключить' }));

    await screen.findByText('crm.example-service.local/webhooks/repairbot · отключён');
    await user.click(screen.getByRole('button', { name: 'Включить интеграцию' }));
    await screen.findByRole('button', { name: 'Отключить интеграцию' });
    expect(screen.getByText('crm.example-service.local/webhooks/repairbot')).toBeInTheDocument();
  });

  it('«Подключить CRM»: при нескольких ключах выбирается client_id, секрет — один раз', async () => {
    const auth = await demoLoginRaw('provider_active_admin');
    const second = await apiCall<{ id: string }>('/integration/api-keys', auth, {
      body: { name: 'CRM тест', scopes: ['requests:read'] },
    });
    let sentBody: Record<string, unknown> | null = null;
    const onRequest = async ({ request }: { request: Request }) => {
      if (request.method === 'POST' && request.url.endsWith('/integration/webhook-subscriptions')) {
        sentBody = (await request.clone().json()) as Record<string, unknown>;
      }
    };
    server.events.on('request:start', onRequest);
    try {
      const user = userEvent.setup();
      await openIntegration(user);
      await user.click(screen.getByRole('link', { name: /Вебхуки/ }));
      await user.click(await screen.findByRole('button', { name: 'Подключить CRM' }));

      await user.type(await screen.findByLabelText('Адрес вебхука'), 'https://crm.example.ru/max');
      const connect = screen.getByRole('button', { name: 'Подключить CRM' });
      expect(connect).toBeDisabled();
      await user.click(screen.getByRole('radio', { name: /CRM тест/ }));
      await user.click(connect);

      await screen.findByText('Секрет показывается один раз');
      const secret = (screen.getByDisplayValue(/^whsec_/) as HTMLInputElement).value;
      expect(sentBody).toMatchObject({ url: 'https://crm.example.ru/max', client_id: second.id });
      expect(screen.getByRole('button', { name: 'Скопировать секрет' })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Скопировал, закрыть' }));
      await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Закрыть' }));
      expect(screen.queryByDisplayValue(secret)).not.toBeInTheDocument();

      await user.click(await screen.findByRole('button', { name: /crm\.example\.ru\/max/ }));
      const sheet = await screen.findByRole('dialog');
      await user.click(within(sheet).getByRole('button', { name: 'Новый секрет подписи' }));
      const confirm = await screen.findByRole('alertdialog');
      await user.click(within(confirm).getByRole('button', { name: 'Выпустить' }));
      await screen.findByText('Секрет показывается один раз');
      expect((screen.getByDisplayValue(/^whsec_/) as HTMLInputElement).value).not.toBe(secret);
    } finally {
      server.events.removeListener('request:start', onRequest);
    }
  });

  it('мок, как сервер: при нескольких ключах подписка без client_id — 422 по полю client_id', async () => {
    const auth = await demoLoginRaw('provider_active_admin');
    await apiCall('/integration/api-keys', auth, { body: { name: 'Второй ключ', scopes: ['requests:read'] } });
    await expect(
      apiCall('/integration/webhook-subscriptions', auth, { body: { url: 'https://crm.example.ru/no-key' } }),
    ).rejects.toThrow(/422: .*"field":"client_id"/);
  });

  it('выпуск ключа — подэкран ?view=create: прямая ссылка открывает форму, «назад» с вводом переспрашивает', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/integration/keys?view=create';

    await user.type(await screen.findByLabelText('Название ключа'), 'Черновик');
    await user.click(screen.getByRole('button', { name: 'Назад' }));
    const ask = await screen.findByRole('alertdialog');
    expect(within(ask).getByText('Выйти без сохранения?')).toBeInTheDocument();
    await user.click(within(ask).getByRole('button', { name: 'Остаться' }));
    expect(screen.getByDisplayValue('Черновик')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Назад' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Выйти' }));
    await screen.findByText('CRM продакшн');
    expect(window.location.hash).not.toContain('view=create');
  });

  it('409 NO_ACTIVE_API_KEY — понятный текст, введённый адрес остаётся', async () => {
    server.use(
      http.post('*/integration/webhook-subscriptions', () =>
        HttpResponse.json(
          {
            error: {
              code: 'NO_ACTIVE_API_KEY',
              message: 'Сначала выпустите ключ интеграции',
              request_id: 'req_test',
            },
          },
          { status: 409 },
        ),
      ),
      http.get('*/integration/api-keys', () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/integration/webhooks?view=create';

    await user.type(await screen.findByLabelText('Адрес вебхука'), 'https://crm.example.ru/hook');
    await user.click(screen.getByRole('button', { name: 'Подключить CRM' }));

    await screen.findByText('Сначала выпустите ключ API — подписка привязывается к нему.');
    expect(screen.getByDisplayValue('https://crm.example.ru/hook')).toBeInTheDocument();
  });

  it('предупреждение по ключу — из ApiKey.warnings, 422 SCOPE_CONFLICT при выпуске', async () => {
    server.use(
      http.get('*/integration/api-keys', () =>
        HttpResponse.json([
          {
            id: 'ik_mixed',
            name: 'Смешанный',
            scopes: ['requests:read'],
            status: 'active',
            key_prefix: 'key_live_mixd',
            created_at: new Date().toISOString(),
            rotated_at: null,
            revoked_at: null,
            last_used_at: null,
            warnings: ['service_bindings_write_shared'],
          },
        ]),
      ),
      http.post('*/integration/api-keys', () =>
        HttpResponse.json(
          {
            error: {
              code: 'SCOPE_CONFLICT',
              message: 'conflict',
              request_id: 'req_test',
              details: { field: 'scopes' },
            },
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    await openIntegration(user);

    await screen.findByText('Привязки — отдельным ключом');

    await user.click(screen.getByRole('link', { name: /API-ключи/ }));
    await user.click(await screen.findByRole('button', { name: 'Создать ключ' }));
    await user.type(await screen.findByLabelText('Название ключа'), 'Ещё один');
    await user.click(screen.getByRole('checkbox', { name: 'requests:read' }));
    await user.click(screen.getByRole('button', { name: 'Создать ключ' }));
    await screen.findByText(
      'Право создавать привязки техники выдаётся отдельным ключом — без прав на заявки и отклики.',
    );
  });
});
