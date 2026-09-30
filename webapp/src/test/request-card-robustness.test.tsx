import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import * as rdb from '../mocks/requestsDb';
import { parseStartParam, startParamToPath } from '../max/startParam';
import type { RequestCustomer } from '../api/types';

async function firstBoschId(auth: { token: string; organizationId: string }): Promise<string> {
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', auth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function createApprovalRequired(): Promise<RequestCustomer> {
  const employee = await demoLoginRaw('customer_employee');
  const draft = await apiCall<RequestCustomer>('/requests', employee, {
    method: 'POST',
    body: { equipment_id: await firstBoschId(employee), route: 'marketplace', urgency: 'normal' },
  });
  return apiCall<RequestCustomer>(`/requests/${draft.id}/actions/request-approval`, employee, {
    method: 'POST',
    body: {},
  });
}

async function createSubmittedOwnService(): Promise<RequestCustomer> {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    method: 'POST',
    body: { equipment_id: await firstBoschId(manager), route: 'own_service', urgency: 'normal' },
  });
  return apiCall<RequestCustomer>(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
    method: 'POST',
    body: { photos_incomplete: true, photos_incomplete_reason: 'не требуется для теста' },
  });
}

describe('карточка заявки: конфликт версий, офлайн, диплинк', () => {
  it('409 при действии: баннер, карточка перечитана, введённый текст сохранён', async () => {
    const request = await createApprovalRequired();
    let cardReads = 0;
    const onStart = ({ request: req }: { request: Request }) => {
      if (req.method === 'GET' && new URL(req.url).pathname.endsWith(`/requests/${request.id}`)) {
        cardReads += 1;
      }
    };
    server.events.on('request:start', onStart);
    server.use(
      http.post('*/requests/:id/actions/return-to-draft', () =>
        HttpResponse.json(
          {
            error: {
              code: 'VERSION_CONFLICT',
              message: 'Данные изменились — обновите экран',
              request_id: 'req_test',
              details: { current_version: 99 },
            },
          },
          { status: 409 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    await user.click(await screen.findByRole('button', { name: 'Вернуть сотруднику' }));
    const comment = screen.getByLabelText('Что нужно исправить');
    await user.type(comment, 'Добавьте фото шильдика');
    const readsBefore = cardReads;
    await user.click(screen.getByRole('button', { name: 'Вернуть на доработку' }));

    const banner = await screen.findByRole('alert');
    expect(within(banner).getByText('Данные изменились')).toBeInTheDocument();
    await waitFor(() => expect(cardReads).toBeGreaterThan(readsBefore));
    expect(screen.getByLabelText('Что нужно исправить')).toHaveValue('Добавьте фото шильдика');
    server.events.removeListener('request:start', onStart);
  });

  it('без сети экран показывает офлайн-сообщение, а не общую ошибку', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    server.use(http.get('*/app-api/v1/requests', () => HttpResponse.error()));
    await user.click(screen.getByRole('link', { name: 'Заявки' }));

    expect(
      await screen.findByText(
        'Нет соединения с сервером. Проверьте сеть и повторите.',
        {},
        { timeout: 8000 },
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('Не удалось загрузить данные')).not.toBeInTheDocument();
  }, 15000);

  it('ссылка req_<id> у исполнителя открывает его карточку заявки', async () => {
    const request = await createSubmittedOwnService();
    const path = startParamToPath(parseStartParam(`req_${request.id}`));
    window.location.hash = `#${path}`;

    renderApp();
    await loginAsDemo('provider_active_admin');

    expect(await screen.findByRole('button', { name: 'Принять' })).toBeInTheDocument();
    expect(window.location.hash).toBe(`#/provider/requests/${request.id}`);
  });

  it('у исполнителя главная ведёт во «Входящие»', async () => {
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('tab', { name: 'Входящие', selected: true });
    window.location.hash = '#/';
    await waitFor(() => expect(window.location.hash).toBe('#/provider/incoming'));
    expect(
      await screen.findByRole('tab', { name: 'Входящие', selected: true }),
    ).toBeInTheDocument();
  });

  it('переписка: неотправленное сообщение остаётся с «Не доставлено · повторить», повтор — тем же ключом', async () => {
    const request = await createSubmittedOwnService();
    const keys: string[] = [];
    const onStart = ({ request: req }: { request: Request }) => {
      if (
        req.method === 'POST' &&
        new URL(req.url).pathname.endsWith(`/requests/${request.id}/messages`)
      ) {
        keys.push(req.headers.get('Idempotency-Key') ?? '');
      }
    };
    server.events.on('request:start', onStart);
    server.use(http.post('*/requests/:id/messages', () => HttpResponse.error(), { once: true }));

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    await screen.findByText('Ждём ответа сервиса', {}, { timeout: 3000 });
    await user.click(await screen.findByRole('link', { name: /^Переписка/ }));
    await screen.findByRole('heading', { name: 'Переписка' });
    await user.type(await screen.findByLabelText('Написать мастеру'), 'Витрина стоит у окна');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));

    await screen.findByText(/Не доставлено/);
    expect(screen.getByText('Витрина стоит у окна')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'повторить' }));

    await waitFor(() => expect(screen.queryByText(/Не доставлено/)).not.toBeInTheDocument());
    expect(await screen.findByText('Витрина стоит у окна')).toBeInTheDocument();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    server.events.removeListener('request:start', onStart);
  });

  it('вопрос из CRM сервиса: блок в карточке, ответ новым сообщением, «Дополнить» вместо правки', async () => {
    const request = await createSubmittedOwnService();
    rdb.postMessage(
      request.id,
      'integration_client',
      null,
      null,
      'Витрина подключена через стабилизатор?',
    );
    const posted: unknown[] = [];
    const onStart = ({ request: req }: { request: Request }) => {
      if (
        req.method === 'POST' &&
        new URL(req.url).pathname.endsWith(`/requests/${request.id}/messages`)
      ) {
        void req
          .clone()
          .json()
          .then((body: unknown) => posted.push(body));
      }
    };
    server.events.on('request:start', onStart);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    const question = await screen.findByText(
      'Витрина подключена через стабилизатор?',
      {},
      { timeout: 4000 },
    );
    const block = question.closest('a')!;
    expect(block).toHaveAttribute('href', `#/requests/${request.id}/messages`);
    await user.click(block);
    await screen.findByRole('heading', { name: 'Сервис уточняет' });
    const answer = screen.getByRole('button', { name: 'Ответить' });
    expect(answer).toBeDisabled();
    await user.type(screen.getByLabelText('Ваш ответ'), 'Да, через стабилизатор');
    await user.click(answer);

    await screen.findByRole('heading', { name: 'Ответ отправлен' });
    await waitFor(() => expect(posted).toEqual([{ body: 'Да, через стабилизатор' }]));
    expect(screen.queryByRole('button', { name: /Изменить/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Дополнить' }));
    expect(screen.getByText('Да, через стабилизатор')).toBeInTheDocument();
    expect(screen.getByLabelText('Добавить к ответу')).toHaveValue('');
    server.events.removeListener('request:start', onStart);
  }, 15000);

  it('ссылка сохраняется, пока пользователь выбирает организацию', async () => {
    const request = await createSubmittedOwnService();
    const manager = await demoLoginRaw('customer_manager');
    await apiCall('/organizations', manager, {
      method: 'POST',
      body: { name: 'ООО «Вторая точка»', kind: 'customer', contact_phone: '+79990000000' },
    });

    window.location.hash = `#${startParamToPath(parseStartParam(`req_${request.id}`))}`;
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');

    await screen.findByRole('radio', { name: /ООО «Вторая точка»/ });
    await user.click(screen.getByRole('radio', { name: /ООО «Ромашка»/ }));
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    await waitFor(() => expect(window.location.hash).toBe(`#/requests/${request.id}`));
    expect(
      await screen.findByRole('heading', { name: `Заявка Р-${request.request_number}` }),
    ).toBeInTheDocument();
  });
});
