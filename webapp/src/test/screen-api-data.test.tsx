import { cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '../mocks/server';
import * as rdb from '../mocks/requestsDb';
import type { Offer, RequestCustomer, RequestMessage } from '../api/types';
import { findHomeScreen, findRowLink, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

type Auth = { token: string; organizationId: string };

async function boschId(auth: Auth): Promise<string> {
  const locs = await apiCall<{ items: { id: string; name: string }[] }>('/locations', auth);
  const cafe = locs.items.find((l) => l.name.includes('Тверской'))!;
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${cafe.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function ownServiceRequest() {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
  });
  const submitted = await apiCall<RequestCustomer>(
    `/requests/${draft.id}/actions/submit-to-own-service`,
    manager,
    {
      body: { photos_incomplete: true, photos_incomplete_reason: 'Фото не требуются для теста' },
    },
  );
  return { manager, request: submitted };
}

async function publishedRequest() {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    body: { equipment_id: await boschId(manager), route: 'marketplace', urgency: 'urgent' },
  });
  await apiCall(`/requests/${draft.id}/actions/publish-search`, manager, {
    body: { attachment_ids: [], confirm_sensitive: false },
  });
  return { manager, requestId: draft.id, requestNumber: draft.request_number };
}

function captureBodies(method: string, pathPattern: RegExp): Record<string, unknown>[] {
  const bodies: Record<string, unknown>[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === method && pathPattern.test(new URL(request.url).pathname)) {
      void request
        .clone()
        .json()
        .then((body: Record<string, unknown>) => bodies.push(body));
    }
  });
  return bodies;
}

const originalCreate = URL.createObjectURL;
const originalRevoke = URL.revokeObjectURL;
beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:preview');
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

describe('карточка заказчика: доставка в CRM и «Позвонить в сервис»', () => {
  it('доставлено в CRM — время доставки, строка «Позвонить в …» ведёт на tel:', async () => {
    const { request } = await ownServiceRequest();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    expect(
      await screen.findByText(/^Заявка доставлена .+, но её пока никто не принял\./),
    ).toBeInTheDocument();
    const timeline = screen.getByLabelText('История');
    expect(within(timeline).getByText('Доставлено в CRM')).toBeInTheDocument();
    const provider = request.assignment!.provider_display_name!;
    const call = screen.getByRole('link', { name: `Позвонить в ${provider}` });
    expect(call.getAttribute('href')).toMatch(/^tel:\+?\d+$/);
  });

  it('CRM недоступна — баннер с временем последней попытки и кнопка «Позвонить в сервис»', async () => {
    const { request } = await ownServiceRequest();
    const lastAttempt = new Date();
    lastAttempt.setHours(9, 40, 0, 0);
    rdb.setDeliveryOverride(request.id, {
      state: 'retrying',
      channel: 'crm',
      delivered_at: null,
      last_attempt_at: lastAttempt.toISOString(),
      next_attempt_at: null,
    });
    try {
      renderApp();
      await loginAsDemo('customer_manager');
      window.location.hash = `#/requests/${request.id}`;

      expect(await screen.findByText('CRM сервиса недоступна')).toBeInTheDocument();
      expect(
        screen.getByText(
          'Заявка сохранена. Повторяем доставку автоматически, последняя попытка в 09:40.',
        ),
      ).toBeInTheDocument();
      expect(within(screen.getByLabelText('История')).getByText('повторяем')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Позвонить в сервис' }).getAttribute('href')).toMatch(
        /^tel:/,
      );
      expect(screen.queryByText('Принято сервисом')).not.toBeInTheDocument();
    } finally {
      rdb.setDeliveryOverride(request.id, null);
    }
  });

  it('без CRM — «Доставлено в приложение исполнителя», строки CRM нет', async () => {
    const { request } = await ownServiceRequest();
    rdb.setDeliveryOverride(request.id, { state: 'none', channel: 'app' });
    try {
      renderApp();
      await loginAsDemo('customer_manager');
      window.location.hash = `#/requests/${request.id}`;
      expect(await screen.findByText('Доставлено в приложение исполнителя')).toBeInTheDocument();
      expect(screen.queryByText('Доставлено в CRM')).not.toBeInTheDocument();
    } finally {
      rdb.setDeliveryOverride(request.id, null);
    }
  });
});

describe('мок как сервер: счётчики и события', () => {
  it('unread_messages_count в списке заявок учитывает отметку прочтения', async () => {
    const { manager, request } = await ownServiceRequest();
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall(`/requests/${request.id}/messages`, provider, { body: { body: 'Пришлите фото шильдика' } });
    const unread = async () =>
      (await apiCall<{ items: { id: string; unread_messages_count: number }[] }>('/requests', manager)).items.find(
        (r) => r.id === request.id,
      )!.unread_messages_count;
    expect(await unread()).toBe(1);
    await apiCall(`/requests/${request.id}/messages/read`, manager, { body: {} });
    expect(await unread()).toBe(0);
  });
});

describe('история: кто сделал шаг', () => {
  it('строка события — «Иван Петров · дата»', async () => {
    const { request } = await ownServiceRequest();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}/history`;
    const list = await screen.findByLabelText('История');
    await waitFor(() => expect(within(list).getAllByText('Иван Петров').length).toBeGreaterThan(0));
  });
});

describe('вопрос кандидата до выбора', () => {
  it('«Задать вопрос» из предложения — приватный тред, ответ уходит в /offers/{id}/messages', async () => {
    const { requestId } = await publishedRequest();
    const provider = await demoLoginRaw('provider_active_admin');
    const offer = await apiCall<Offer>(`/marketplace/requests/${requestId}/offers`, provider, {
      body: { amount_minor: 200000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
    });
    await apiCall(`/marketplace/requests/${requestId}/messages`, provider, {
      body: { body: 'Какая модель? Если CU1526, возьму с собой насос.' },
    });
    const other = await demoLoginRaw('provider_admin');
    await apiCall(`/marketplace/requests/${requestId}/messages`, other, {
      body: { body: 'Вопрос другого' },
    });

    const posted = captureBodies('POST', /\/offers\/[^/]+\/messages$/);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/offers/${offer.id}`;
    await user.click(await screen.findByRole('link', { name: 'Задать вопрос' }));

    await screen.findByRole('heading', { name: 'Вопрос исполнителя' });
    expect(screen.getByText('Видите только вы и этот исполнитель')).toBeInTheDocument();
    expect(
      await screen.findByText('Какая модель? Если CU1526, возьму с собой насос.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Вопрос другого')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Ответить исполнителю'), 'Scotsman AC 126');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await waitFor(() => expect(posted).toEqual([{ body: 'Scotsman AC 126' }]));
    expect(await screen.findByText('Scotsman AC 126')).toBeInTheDocument();
  });

  it('409 OFFER_DIALOG_CLOSED — понятный текст', async () => {
    const { requestId } = await publishedRequest();
    const provider = await demoLoginRaw('provider_active_admin');
    const offer = await apiCall<Offer>(`/marketplace/requests/${requestId}/offers`, provider, {
      body: { amount_minor: 200000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
    });
    server.use(
      http.post('*/requests/:id/offers/:offerId/messages', () =>
        HttpResponse.json(
          { error: { code: 'OFFER_DIALOG_CLOSED', message: 'closed', request_id: 'r1' } },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/offers/${offer.id}/messages`;
    await user.type(await screen.findByLabelText('Ответить исполнителю'), 'Ответ');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    expect(
      await screen.findByText(
        'Вопросы до выбора закрыты: исполнитель уже выбран или поиск завершён. Дальше — в переписке по заявке.',
      ),
    ).toBeInTheDocument();
  });

  it('общая переписка не показывает треды кандидатов', async () => {
    const { request } = await ownServiceRequest();
    const threadMessage = rdb.postMessage(
      request.id,
      'provider_membership',
      'm_other',
      'org_other_candidate',
      'Сообщение из треда другого исполнителя',
    );
    expect(threadMessage.thread_provider_id).toBe('org_other_candidate');
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall(`/requests/${request.id}/messages`, provider, {
      body: { body: 'Общее сообщение сервиса' },
    });

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}/messages`;
    expect(await screen.findByText('Общее сообщение сервиса')).toBeInTheDocument();
    expect(screen.queryByText('Сообщение из треда другого исполнителя')).not.toBeInTheDocument();
  });
});

describe('биржа исполнителя: вопрос заказчику и счётчик предложений', () => {
  it('«Задать вопрос» до отклика — /marketplace/requests/{id}/messages, в списке тег «Уточнение»', async () => {
    const { requestId } = await publishedRequest();
    const posted = captureBodies('POST', /\/marketplace\/requests\/[^/]+\/messages$/);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `#/provider/available/${requestId}`;

    await user.click(await screen.findByRole('button', { name: 'Задать вопрос' }));
    await screen.findByRole('heading', { name: 'Вопрос заказчику' });
    expect(screen.getByText('Видите только вы и заказчик')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Ваш вопрос'), 'Какая модель компрессора?');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await waitFor(() => expect(posted).toEqual([{ body: 'Какая модель компрессора?' }]));
    expect(await screen.findByText('Какая модель компрессора?')).toBeInTheDocument();

    window.location.hash = '#/provider/available';
    const row = await findRowLink(`/provider/available/${requestId}`);
    await waitFor(() => expect(row).toHaveTextContent('Уточнение'));
    expect(row).toHaveTextContent('ждёт ответа на вопрос');
  });

  it('число предложений — «1 предложение»', async () => {
    const { requestId } = await publishedRequest();
    const other = await demoLoginRaw('provider_admin');
    await apiCall<Offer>(`/marketplace/requests/${requestId}/offers`, other, {
      body: { amount_minor: 150000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
    });
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '#/provider/available';
    const row = await findRowLink(`/provider/available/${requestId}`);
    expect(row).toHaveTextContent('1 предложение');
    expect(row).toHaveTextContent('1–3 дня');
  });
});

describe('входящие исполнителя: заказчик и договор', () => {
  it('в карточке новой заявки — «Договор № Д-100»', async () => {
    const { request } = await ownServiceRequest();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `#/provider/requests/${request.id}`;
    expect(await screen.findByText('№ Д-100')).toBeInTheDocument();
    expect(screen.getByText('Договор')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2 }).parentElement).toHaveTextContent(
      'ООО «Ромашка»',
    );
  });
});

async function inProgressRequest() {
  const { manager, request } = await ownServiceRequest();
  const provider = await demoLoginRaw('provider_active_admin');
  const assignmentId = request.assignment!.id;
  await apiCall(`/requests/${request.id}/actions/accept`, provider, {
    body: { assignment_id: assignmentId },
  });
  await apiCall(`/requests/${request.id}/actions/propose-visit`, provider, {
    body: {
      assignment_id: assignmentId,
      amount_minor: 350000,
      currency: 'RUB',
      valid_until: '2027-01-01T00:00:00Z',
    },
  });
  const withVisit = await apiCall<RequestCustomer>(`/requests/${request.id}`, manager);
  await apiCall(`/requests/${request.id}/actions/approve-visit-proposal`, manager, {
    body: { proposal_id: withVisit.visit_proposals[0]!.id, proposal_version: 1 },
  });
  await apiCall(`/requests/${request.id}/actions/start-work`, provider, {
    body: { assignment_id: assignmentId },
  });
  return {
    manager,
    provider,
    requestId: request.id,
    requestNumber: request.request_number,
    assignmentId,
  };
}

describe('смета по позициям', () => {
  it('исполнитель отправляет items и итог; заказчик видит позиции с суммами', async () => {
    const { requestId } = await inProgressRequest();
    const posted = captureBodies('POST', /\/actions\/create-repair-quote$/);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `#/provider/requests/${requestId}`;

    await user.click(await screen.findByRole('button', { name: 'Предложить цену ремонта' }));
    for (const [title, amount] of [
      ['Пусковое реле', '1900'],
      ['Заправка фреоном', '3800'],
    ] as const) {
      await user.click(await screen.findByRole('button', { name: 'Добавить позицию' }));
      const sheet = await screen.findByRole('dialog');
      await user.type(within(sheet).getByLabelText('Работа или деталь'), title);
      await user.type(within(sheet).getByLabelText('Сумма, ₽'), amount);
      await user.click(within(sheet).getByRole('button', { name: 'Добавить' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    }
    await user.click(screen.getByRole('button', { name: 'Отправить на согласование' }));
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0]).toMatchObject({
      amount_minor: 570000,
      items: [
        { title: 'Пусковое реле', amount_minor: 190000 },
        { title: 'Заправка фреоном', amount_minor: 380000 },
      ],
      description_of_work: 'Пусковое реле, Заправка фреоном',
    });

    cleanup();
    renderApp();
    await loginAsDemo('customer_manager');
    const current = await apiCall<RequestCustomer>(
      `/requests/${requestId}`,
      await demoLoginRaw('customer_manager'),
    );
    window.location.hash = `#/requests/${requestId}/repair-quotes/${current.repair_quotes[0]!.id}`;
    const items = await screen.findByLabelText('Позиции сметы');
    expect(within(items).getByText('Пусковое реле')).toBeInTheDocument();
    expect(within(items).getByText('1 900 ₽')).toBeInTheDocument();
    expect(within(items).getByText('3 800 ₽')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Согласовать 5\s700\s₽$/ })).toBeInTheDocument();
  });

  it('422 QUOTE_ITEMS_SUM_MISMATCH — понятный текст, позиции остаются', async () => {
    const { requestId } = await inProgressRequest();
    server.use(
      http.post('*/requests/:id/actions/:action', ({ params }) =>
        String(params.action).includes('quote')
          ? HttpResponse.json(
              {
                error: { code: 'QUOTE_ITEMS_SUM_MISMATCH', message: 'mismatch', request_id: 'r1' },
              },
              { status: 422 },
            )
          : undefined,
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `#/provider/requests/${requestId}`;
    await user.click(await screen.findByRole('button', { name: 'Предложить цену ремонта' }));
    await user.click(await screen.findByRole('button', { name: 'Добавить позицию' }));
    const sheet = await screen.findByRole('dialog');
    await user.type(within(sheet).getByLabelText('Работа или деталь'), 'Работа');
    await user.type(within(sheet).getByLabelText('Сумма, ₽'), '1000');
    await user.click(within(sheet).getByRole('button', { name: 'Добавить' }));
    await user.click(await screen.findByRole('button', { name: 'Отправить на согласование' }));
    expect(
      await screen.findByText(
        'Итог не совпадает с суммой позиций — проверьте суммы и отправьте снова.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Работа')).toBeInTheDocument();
  });
});

describe('отчёт мастера: фото до и после', () => {
  it('исполнитель видит слоты «До»/«После»; заказчик — фото отчёта и текст', async () => {
    const { requestId, requestNumber, provider, assignmentId } = await inProgressRequest();

    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `#/provider/requests/${requestId}`;
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole('button', { name: 'Отчёт о работе' }))[0]!);
    expect(await screen.findByRole('button', { name: 'Добавить фото «До»' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Добавить фото «После»' })).toBeInTheDocument();
    cleanup();

    for (const slot of ['before', 'after']) {
      rdb.addAttachment({
        ownerKind: 'request',
        requestId,
        messageId: null,
        slot,
        visibilityClass: 'request_private',
        mimeType: 'image/jpeg',
        blob: new Blob(['x'], { type: 'image/jpeg' }),
      });
    }
    await apiCall(`/requests/${requestId}/actions/report-completion`, provider, {
      body: { assignment_id: assignmentId, outcome: 'resolved', summary: 'Заменил пусковое реле.' },
    });

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;
    expect(await screen.findByText('Мастер закончил ремонт')).toBeInTheDocument();
    expect(screen.getByText('Заменил пусковое реле.')).toBeInTheDocument();
    const photos = screen.getByRole('group', { name: 'Фото отчёта' });
    expect(within(photos).getByText('До')).toBeInTheDocument();
    expect(within(photos).getByText('После')).toBeInTheDocument();
    expect(within(photos).getAllByRole('img').length).toBe(2);
    expect(requestNumber).toBeGreaterThan(0);
  });
});

describe('главная: «Нужен ваш ответ»', () => {
  it('сотрудник видит вопрос мастера текстом сообщения и переходит в переписку', async () => {
    const { request } = await ownServiceRequest();
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall<RequestMessage>(`/requests/${request.id}/messages`, provider, {
      body: { body: 'Пришлите фото шильдика' },
    });
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    const section = await screen.findByRole('region', { name: 'Нужен ваш ответ' });
    const row = await within(section).findByRole('link', { name: /Пришлите фото шильдика/ });
    expect(row).toHaveTextContent('Вопрос мастера');
    await user.click(row);
    await screen.findByRole('heading', { name: 'Переписка' });
  });

  it('руководитель тоже видит вопрос кандидата; ссылка ведёт в тред исполнителя', async () => {
    const { requestId } = await publishedRequest();
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall(`/marketplace/requests/${requestId}/messages`, provider, {
      body: { body: 'Есть ли доступ к розетке?' },
    });
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    const section = await screen.findByRole('region', { name: 'Нужен ваш ответ' });
    const row = await within(section).findByRole('link', { name: /Есть ли доступ к розетке\?/ });
    expect(row.getAttribute('href')).toBe(
      `#/requests/${requestId}/questions/${provider.organizationId}`,
    );
    await user.click(row);
    await screen.findByRole('heading', { name: 'Вопрос исполнителя' });
    expect(await screen.findByText('Есть ли доступ к розетке?')).toBeInTheDocument();
  });
});

describe('точки и приглашение', () => {
  it('точка — «Москва, Центральный · N единиц техники»', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/locations';
    await screen.findByRole('heading', { name: 'Точки' });
    await waitFor(() =>
      expect(screen.getAllByText(/\d+\s(единица|единицы|единиц) техники$/).length).toBeGreaterThan(
        0,
      ),
    );
  });

  it('приглашение — «Приглашение от …, руководитель» и строка «Точки»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const locs = await apiCall<{ items: { id: string; name: string }[] }>('/locations', manager);
    const issued = await apiCall<{ token: string }>('/invitations', manager, {
      body: { role: 'customer_employee', location_ids: [locs.items[0]!.id] },
    });
    renderApp();
    await loginAsDemo('new_user');
    window.location.hash = `#/invitations/accept?token=${encodeURIComponent(issued.token)}`;
    expect(await screen.findByText('Приглашение от')).toBeInTheDocument();
    expect(screen.getByText('Иван Петров')).toBeInTheDocument();
    expect(screen.getByText('Точка')).toBeInTheDocument();
    expect(screen.getByText(locs.items[0]!.name)).toBeInTheDocument();
  });
});

describe('свой профиль исполнителя: условия выезда и отзывы', () => {
  it('«Выезд от» сохраняется в visit_price_from_minor и показывается «от 2 500 ₽»; отзывы — рейтинг сервера', async () => {
    const provider = await demoLoginRaw('provider_active_admin');
    const own = await apiCall<{
      rating?: number | null;
      rating_label?: string | null;
      unique_customers: number;
    }>('/provider-profile', provider);
    const patches = captureBodies('PATCH', /\/provider-profile$/);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '#/provider/profile/terms';
    const field = await screen.findByLabelText('Выезд от, ₽');
    await user.clear(field);
    await user.type(field, '2500');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByRole('link', { name: /Условия выезда/ });
    await waitFor(() => expect(patches.at(-1)).toMatchObject({ visit_price_from_minor: 250000 }));
    expect(screen.getByRole('link', { name: /Условия выезда/ })).toHaveTextContent(/от 2\s500\s₽/);

    const reviews = screen.getByRole('link', { name: /Отзывы/ });
    if (own.rating && !own.rating_label) expect(reviews).toHaveTextContent('★');
    else if (own.rating_label) expect(reviews).toHaveTextContent(own.rating_label);
  });
});

describe('оператор: очередь обжалований профилей', () => {
  it('обжалование видно во вкладке «Обжалования», решение — через /decision с основанием', async () => {
    const suspended = await demoLoginRaw('provider_suspended_admin');
    const profile = await apiCall<{ appeal?: { decision: string | null } | null }>(
      '/provider-profile',
      suspended,
    );
    if (!profile.appeal || profile.appeal.decision) {
      await apiCall('/provider-profile/appeal', suspended, {
        body: { text: 'Жалобы урегулированы, есть акты' },
      });
    }
    const decisions = captureBodies('POST', /\/moderation-cases\/[^/]+\/decision$/);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('operator');
    window.location.hash = '#/operator/providers';
    await user.click(await screen.findByRole('tab', { name: /Обжалования/ }));
    await user.click(await screen.findByRole('button', { name: /Обжалование/ }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByText('Жалобы урегулированы, есть акты')).toBeInTheDocument();
    await user.click(within(sheet).getByRole('radio', { name: 'Отклонить' }));
    await user.type(
      within(sheet).getByLabelText('Основание решения (обязательно)'),
      'Нарушения повторяются',
    );
    await user.click(within(sheet).getByRole('button', { name: 'Отправить решение' }));
    const confirm = await screen.findByRole('alertdialog');
    await user.click(within(confirm).getByRole('button', { name: /Да|Подтвердить/ }));
    await waitFor(() =>
      expect(decisions).toEqual([{ decision: 'rejected', reason: 'Нарушения повторяются' }]),
    );
    expect(await screen.findByText('Обжалований на рассмотрении нет')).toBeInTheDocument();
  });
});
