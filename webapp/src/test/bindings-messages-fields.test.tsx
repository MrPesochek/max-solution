import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import type {
  BindingInvitationIssued,
  BindingInvitationPreview,
  RequestCustomer,
} from '../api/types';
import { findHomeScreen, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

type Auth = { token: string; organizationId: string };

async function pickProvider(user: ReturnType<typeof userEvent.setup>, query = 'Холод', name = 'Сервис-Холод Плюс') {
  await user.type(await screen.findByRole('textbox', { name: 'Сервис' }), query);
  await user.click(await screen.findByRole('radio', { name }));
}

async function boschId(auth: Auth): Promise<string> {
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>('/equipment', auth);
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function openContractRequestForm(user: ReturnType<typeof userEvent.setup>) {
  window.location.hash = '#/bindings/new?way=request';
  await screen.findByRole('heading', { name: 'По номеру договора' });
  await pickProvider(user);
  await user.type(screen.getByLabelText('Номер договора'), 'Д-77');
  await user.click(screen.getAllByRole('checkbox')[0]!);
}

describe('запрос по договору (D25.2): остаток попыток и ожидание после лимита', () => {
  it('после запроса форма показывает «Попыток осталось: 4 из 5 за 15 минут»', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await openContractRequestForm(user);
    expect(
      screen.getByText('Можно отправить не больше 5 запросов за 15 минут.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Запросить подтверждение' }));
    await screen.findByText('Ждём подтверждения');

    window.location.hash = '#/bindings';
    await screen.findByRole('heading', { name: 'Подключённые сервисы' });
    await openContractRequestForm(user);
    expect(screen.getByText('Попыток осталось: 4 из 5 за 15 минут.')).toBeInTheDocument();
  });

  it('429 с retry_after_seconds — «Попробуйте через 4 минуты»', async () => {
    server.use(
      http.post('*/service-bindings/requests', () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'Слишком много запросов',
              request_id: 'req_test',
              details: { retry_after_seconds: 230 },
            },
          },
          { status: 429 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await openContractRequestForm(user);
    await user.click(screen.getByRole('button', { name: 'Запросить подтверждение' }));
    await screen.findByText('Попробуйте через 4 минуты');
  });
});

describe('запрос по договору (15h): основание, ожидание и отмена', () => {
  it('основание уходит в запрос, «Отменить запрос» отзывает созданную ожидающую привязку', async () => {
    const user = userEvent.setup();
    const sent: { path: string; body: unknown }[] = [];
    server.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname;
      if (request.method === 'POST' && (path.endsWith('/service-bindings/requests') || path.endsWith('/revoke'))) {
        void request
          .clone()
          .json()
          .then((body: unknown) => sent.push({ path, body }));
      }
    });
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/new?way=request';
    await screen.findByRole('heading', { name: 'Привязать свой сервис' });
    await pickProvider(user);
    await user.type(screen.getByLabelText('Номер договора'), 'СО-2291');
    await user.click(within(screen.getByRole('radiogroup', { name: 'Основание' })).getByRole('radio', { name: 'Гарантия' }));
    await user.click(screen.getAllByRole('checkbox')[0]!);
    await user.click(screen.getByRole('button', { name: 'Запросить подтверждение' }));

    await screen.findByText('Ждём подтверждения');
    expect(screen.getByText('Сервис-Холод Плюс проверит договор СО-2291. Сообщим в MAX.')).toBeInTheDocument();
    expect(screen.getByText('На проверке у сервиса')).toBeInTheDocument();
    expect(screen.getByText('Гарантия')).toBeInTheDocument();
    await waitFor(() => expect(sent.some((c) => c.path.endsWith('/service-bindings/requests'))).toBe(true));
    expect(sent.find((c) => c.path.endsWith('/service-bindings/requests'))!.body).toMatchObject({
      contract_number: 'СО-2291',
      basis: 'warranty',
    });

    expect(screen.getByRole('button', { name: 'Готово' })).toBeInTheDocument();
    const cancel = screen.getByRole('button', { name: 'Отменить запрос' });
    await waitFor(() => expect(cancel).toBeEnabled());
    await user.click(cancel);
    const dialog = await screen.findByRole('alertdialog');
    expect(sent.filter((c) => c.path.endsWith('/revoke'))).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Отменить запрос' }));
    await screen.findByRole('heading', { name: 'Привязать свой сервис' });
    expect(sent.filter((c) => c.path.endsWith('/revoke')).length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Номер договора')).toHaveValue('СО-2291');
  });

  it('сервис ищется по названию или ИНН целиком (K-10): короткий запрос не уходит на сервер', async () => {
    const user = userEvent.setup();
    const queries: string[] = [];
    server.events.on('request:start', ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith('/providers')) queries.push(url.searchParams.get('q') ?? '');
    });
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/new?way=request';
    await screen.findByRole('heading', { name: 'Привязать свой сервис' });
    const field = await screen.findByRole('textbox', { name: 'Сервис' });
    expect(field).toHaveAttribute('placeholder', 'Название или ИНН');

    await user.type(field, 'Хо');
    expect(await screen.findByText('Введите не меньше 3 букв названия или ИНН целиком')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(queries).toEqual([]);

    await user.clear(field);
    await user.type(field, '7712345691');
    await user.click(await screen.findByRole('radio', { name: 'Сервис-Холод Плюс' }));
    expect(queries).toContain('7712345691');

    await user.clear(field);
    await user.type(field, 'Несуществующий');
    expect(await screen.findByText('Сервис не найден. Проверьте название или ИНН.')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Сервис-Холод Плюс' })).toBeChecked();
  });
});

describe('гарантирующая сторона в приглашении (12b, K-13)', () => {
  it('«Гарантию даёт» — со слов сервиса; производитель без проверки полномочий не «авторизован»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const preview = await apiCall<BindingInvitationPreview>('/service-binding-invitations/preview', manager, {
      body: { token: 'demo-sb-valid-token' },
    });
    server.use(
      http.post('*/service-binding-invitations/preview', () =>
        HttpResponse.json({ ...preview, guarantor_kind: 'manufacturer', guarantor_name: 'Carboma' }),
      ),
    );
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/accept?token=demo-sb-valid-token';
    await screen.findByText('Приглашение от Сервис-Холод Плюс');
    expect(screen.getByText('Гарантию даёт')).toBeInTheDocument();
    expect(screen.getByText('Производитель: Carboma')).toBeInTheDocument();
    expect(screen.getByText('со слов сервиса, полномочия производителя не проверены')).toBeInTheDocument();
    expect(screen.queryByText(/[Аа]вторизован/)).not.toBeInTheDocument();
  });

  it('без сведений о гаранте строки «Гарантию даёт» нет', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/accept?token=demo-sb-valid-token';
    await screen.findByText('Приглашение от Сервис-Холод Плюс');
    expect(screen.queryByText('Гарантию даёт')).not.toBeInTheDocument();
  });
});

describe('приглашение от сервиса (D25.4)', () => {
  it('подпись «Проверенный сервис» — по requisites_verified и representative_verified', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const preview = await apiCall<BindingInvitationPreview>(
      '/service-binding-invitations/preview',
      manager,
      {
        body: { token: 'demo-sb-valid-token' },
      },
    );
    server.use(
      http.post('*/service-binding-invitations/preview', () =>
        HttpResponse.json({ ...preview, requisites_verified: true, representative_verified: true }),
      ),
    );
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/accept?token=demo-sb-valid-token';
    await screen.findByText('Приглашение от Сервис-Холод Плюс');
    expect(
      screen.getByText('Проверенный сервис · реквизиты и представитель подтверждены'),
    ).toBeInTheDocument();
  });

  it('без проверок платформы сервис не называется проверенным', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const preview = await apiCall<BindingInvitationPreview>(
      '/service-binding-invitations/preview',
      manager,
      {
        body: { token: 'demo-sb-valid-token' },
      },
    );
    server.use(
      http.post('*/service-binding-invitations/preview', () =>
        HttpResponse.json({
          ...preview,
          requisites_verified: false,
          representative_verified: false,
        }),
      ),
    );
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings/accept?token=demo-sb-valid-token';
    await screen.findByText('Реквизиты и представитель сервиса платформой не проверены');
    expect(screen.queryByText(/^Проверенный сервис/)).not.toBeInTheDocument();
  });

  it('«Отклонить» — подтверждение с причиной, POST /decline и состояние «Приглашение отклонено»', async () => {
    const provider = await demoLoginRaw('provider_active_admin');
    const issued = await apiCall<BindingInvitationIssued>(
      '/service-binding-invitations',
      provider,
      {
        body: {
          customer_inn: '7712345600',
          customer_name: 'ООО «Ромашка»',
          contract_number: 'Д-810',
          equipment_items: [{ description: 'Витрина' }],
        },
      },
    );
    const bodies: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (
        request.method === 'POST' &&
        new URL(request.url).pathname.endsWith('/service-binding-invitations/decline')
      ) {
        void request
          .clone()
          .json()
          .then((body: unknown) => bodies.push(body));
      }
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/bindings/accept?token=${encodeURIComponent(issued.token)}`;
    await screen.findByText('Приглашение от Сервис-Холод Плюс');

    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const sheet = within(await screen.findByRole('alertdialog'));
    expect(sheet.getByText('Отклонить приглашение?')).toBeInTheDocument();
    await user.click(sheet.getByRole('button', { name: 'Отмена' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(bodies).toEqual([]);

    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const again = within(await screen.findByRole('alertdialog'));
    await user.type(again.getByLabelText('Причина'), 'Договор расторгнут');
    await user.click(again.getByRole('button', { name: 'Отклонить приглашение' }));

    await screen.findByText('Приглашение отклонено');
    expect(bodies).toEqual([{ token: issued.token, reason: 'Договор расторгнут' }]);
  });

  it('исполнитель видит отказ: название заказчика, «Отклонено» и причину (D35)', async () => {
    const provider = await demoLoginRaw('provider_active_admin');
    const issued = await apiCall<BindingInvitationIssued>(
      '/service-binding-invitations',
      provider,
      {
        body: {
          customer_inn: '7712345600',
          customer_name: 'Пекарня Мука',
          contract_number: 'Д-811',
          equipment_items: [{ description: 'Витрина' }, { description: 'Шкаф' }],
        },
      },
    );
    const manager = await demoLoginRaw('customer_manager');
    await apiCall('/service-binding-invitations/decline', manager, {
      body: { token: issued.token, reason: 'Не наш договор' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('link', { name: 'Профиль' });
    window.location.hash = '#/bindings/invitations';
    await screen.findByRole('heading', { name: 'Приглашения клиентов' });

    const row = await screen.findByRole('button', { name: /^Пекарня Мука/ });
    expect(within(row).getByText('Отклонено')).toBeInTheDocument();
    expect(within(row).getByText('Причина: «Не наш договор»')).toBeInTheDocument();
    await user.click(row);
    const sheet = within(await screen.findByRole('dialog'));
    expect(sheet.getByText('Отклонено заказчиком')).toBeInTheDocument();
    expect(sheet.getByText('№ Д-811')).toBeInTheDocument();
    expect(sheet.queryByRole('button', { name: 'Отозвать приглашение' })).toBeNull();
  });
});

describe('переписка: счётчик непрочитанного и отметка прочтения', () => {
  it('«Переписка» показывает число новых сообщений, открытие отмечает прочтение', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
    });
    const submitted = await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/submit-to-own-service`,
      manager,
      {
        body: { photos_incomplete: true, photos_incomplete_reason: 'Без фото' },
      },
    );
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall(`/requests/${draft.id}/actions/accept`, provider, {
      body: { assignment_id: submitted.assignment!.id },
    });
    await apiCall(`/requests/${draft.id}/messages`, provider, {
      body: { body: 'Пришлите фото шильдика' },
    });
    await apiCall(`/requests/${draft.id}/messages`, provider, {
      body: { body: 'И код ошибки, если есть' },
    });

    const reads: string[] = [];
    server.events.on('request:start', ({ request }) => {
      if (
        request.method === 'POST' &&
        new URL(request.url).pathname.endsWith(`/requests/${draft.id}/messages/read`)
      ) {
        reads.push(request.method);
      }
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${draft.id}`;
    const row = await screen.findByRole('link', { name: /^Переписка/ });
    expect(within(row).getByText('2')).toBeInTheDocument();

    await user.click(row);
    await screen.findByText('И код ошибки, если есть');
    await waitFor(() => expect(reads.length).toBeGreaterThan(0));

    window.location.hash = `#/requests/${draft.id}`;
    await screen.findByRole('button', { name: /^Написать/ }, { timeout: 5000 });
    await waitFor(() => expect(screen.queryByRole('link', { name: /^Переписка/ })).not.toBeInTheDocument());
  });
});

describe('баннер сотрудника: кто опубликует черновик (approver_name)', () => {
  it('approval_required у сотрудника — «Иван Петров проверит…»', async () => {
    const employee = await demoLoginRaw('customer_employee');
    const draft = await apiCall<RequestCustomer>('/requests', employee, {
      body: {
        equipment_id: await boschId(employee),
        route: 'marketplace',
        urgency: 'normal',
        symptom_description: 'Не морозит',
      },
    });
    await apiCall(`/requests/${draft.id}/actions/request-approval`, employee, { body: {} });

    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    window.location.hash = `#/requests/${draft.id}`;
    expect(
      await screen.findByText('Иван Петров проверит, что увидят исполнители, и откроет поиск.'),
    ).toBeInTheDocument();
  });

  it('без approver_name — «Руководитель проверит…»', async () => {
    const employee = await demoLoginRaw('customer_employee');
    const draft = await apiCall<RequestCustomer>('/requests', employee, {
      body: { equipment_id: await boschId(employee), route: 'marketplace', urgency: 'normal' },
    });
    const pending = await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/request-approval`,
      employee,
      {
        body: {},
      },
    );
    server.use(
      http.get(`*/requests/${draft.id}`, () =>
        HttpResponse.json({ ...pending, approver_name: null }),
      ),
    );

    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    window.location.hash = `#/requests/${draft.id}`;
    expect(
      await screen.findByText('Руководитель проверит, что увидят исполнители, и откроет поиск.'),
    ).toBeInTheDocument();
  });
});

describe('черновик (D16 draft): карточка перед мастером', () => {
  it('показывает, что заполнено, «Продолжить» открывает мастер на нужном шаге', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${draft.id}`;

    await screen.findByRole('heading', { name: 'Холодильник Bosch' });
    expect(screen.getByText(/^Кафе на Тверской · сохранён на сервере /)).toBeInTheDocument();
    expect(
      screen.getByText('Никто её не видит. Продолжить можно здесь или в чате с ботом.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Описание').closest('.ui-row')).toHaveTextContent('не заполнено');
    expect(screen.getByText('Фото').closest('.ui-row')).toHaveTextContent('не добавлены');
    await waitFor(() =>
      expect(screen.getByText('Получатель').closest('.ui-row')).toHaveTextContent(
        'Сервис-Холод Плюс',
      ),
    );

    await user.click(screen.getByRole('button', { name: 'Продолжить заполнение' }));
    await screen.findByText('Шаг 2 из 3');
    expect(screen.getByLabelText('Подробнее')).toBeInTheDocument();
  });

  it('«Удалить черновик» — подтверждение и cancel-draft с версией', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      body: {
        equipment_id: await boschId(manager),
        route: 'own_service',
        urgency: 'normal',
        symptom_description: 'Гудит',
      },
    });
    const bodies: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (
        request.method === 'POST' &&
        new URL(request.url).pathname.endsWith(`/requests/${draft.id}/actions/cancel-draft`)
      ) {
        void request
          .clone()
          .json()
          .then((body: unknown) => bodies.push(body));
      }
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${draft.id}`;
    await screen.findByText('Заявка ещё не отправлена');

    await user.click(screen.getByRole('button', { name: 'Удалить черновик' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    expect(dialog.getByText('Удалить черновик?')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Удалить' }));

    await screen.findByRole('heading', { name: 'Заявки' });
    expect(bodies).toEqual([{ expected_version: draft.version }]);
    const after = await apiCall<RequestCustomer>(`/requests/${draft.id}`, manager);
    expect(after.status).toBe('cancelled');
  });
});
