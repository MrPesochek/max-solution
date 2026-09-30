import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { findRowLink, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { Offer, RequestCustomer, RequestProvider } from '../api/types';

async function boschEquipmentId(auth: { token: string; organizationId: string }): Promise<string> {
  const locs = await apiCall<{ items: { id: string; name: string }[] }>('/locations', auth);
  const cafe = locs.items.find((l) => l.name.includes('Тверской'))!;
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${cafe.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

describe('рабочее место исполнителя: входящие/в работе (свой сервис)', () => {
  it('исполнитель принимает входящую заявку и предлагает выезд с ценой', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);

    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
    });
    const submitted = await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/submit-to-own-service`,
      managerAuth,
      {
        body: { photos_incomplete: false, photos_incomplete_reason: null },
      },
    );
    expect(submitted.status).toBe('awaiting_provider');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/provider/incoming';

    await screen.findByRole('heading', { name: 'Заявки' });
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Входящие' })).toHaveAttribute('aria-selected', 'true'),
    );
    const row = await findRowLink(`/provider/requests/${submitted.id}`);
    expect(row).toHaveTextContent('ООО «Ромашка»');
    expect(
      screen.queryByText(/Адрес и контакты появятся после подтверждения назначения/),
    ).not.toBeInTheDocument();

    await user.click(row);
    await screen.findByRole('button', { name: 'Принять' });
    await user.click(screen.getByRole('button', { name: 'Принять' }));

    const providerAuth = await demoLoginRaw('provider_active_admin');
    const accepted = await apiCall<RequestProvider>(`/requests/${draft.id}`, providerAuth);
    let sent: Record<string, unknown> | undefined;
    server.use(http.post('*/requests/:id/messages', async ({ request }) => {
      sent = await request.json() as Record<string, unknown>;
      return HttpResponse.json({
        id: 'message-regression', request_id: draft.id,
        author_kind: 'provider_membership', body: sent.body,
        created_at: new Date().toISOString(), visibility_scope: 'all_participants',
      }, { status: 201 });
    }));
    await user.click(await screen.findByRole('button', { name: 'Переписка' }));
    await user.type(await screen.findByPlaceholderText('Написать сообщение…'), 'Мастер готов выехать');
    await user.click(screen.getByRole('button', { name: 'Отправить' }));
    await waitFor(() => expect(sent).toMatchObject({
      body: 'Мастер готов выехать', assignment_id: accepted.assignment.id,
    }));
    await user.click(screen.getByRole('button', { name: /^Гарантия/ }));
    expect(await screen.findByRole('button', { name: 'Сохранить решение' })).toBeDisabled();
    await user.type(screen.getByLabelText('Пояснение решения (обязательно)'), 'Нужна диагностика');
    await user.click(screen.getByRole('button', { name: 'Сохранить решение' }));

    await screen.findByRole('button', { name: 'Предложить выезд' });
    await user.click(screen.getByRole('button', { name: 'Предложить выезд' }));

    await user.type(await screen.findByLabelText('Стоимость выезда и диагностики'), '1500');
    await user.click(screen.getByRole('button', { name: 'Отправить на согласование' }));

    await waitFor(() => expect(screen.getByText('Не согласовано')).toBeInTheDocument());
  });
});

describe('биржа: отклик исполнителя', () => {
  it('подаёт предложение (бесплатно, с основанием) и отзывает его', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'marketplace', urgency: 'normal' },
    });
    const published = await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/publish-search`,
      managerAuth,
      {
        body: { attachment_ids: [], confirm_sensitive: false },
      },
    );
    expect(published.status).toBe('searching');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/provider/available';

    await screen.findByRole('heading', { name: 'Заявки' });
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Доступные' })).toHaveAttribute('aria-selected', 'true'),
    );
    const card = await findRowLink(`/provider/available/${published.id}`);
    expect(card).toHaveTextContent('Нет предложений');
    expect(card).not.toHaveTextContent('Ромашка');
    const providerAuth = await demoLoginRaw('provider_active_admin');
    const market = await apiCall<{
      card: { district_name?: string | null; city_name?: string | null };
    }>(`/marketplace/requests/${published.id}`, providerAuth);
    const area = market.card.district_name ?? market.card.city_name;
    expect(area).toBeTruthy();
    expect(card).toHaveTextContent(area!);
    await user.click(card);

    await screen.findByRole('heading', { name: `Заявка Р-${published.request_number}` });
    expect(screen.getAllByRole('radio', { checked: true }).length).toBeGreaterThan(0);
    await user.click(await screen.findByRole('switch', { name: 'Бесплатно, 0 ₽' }));
    await user.type(
      screen.getByLabelText('Основание (почему бесплатно)'),
      'Гарантийный ремонт по договору',
    );

    await user.click(screen.getByRole('button', { name: 'Откликнуться' }));

    await waitFor(() =>
      expect(screen.getByText(/Гарантийный ремонт по договору/)).toBeInTheDocument(),
    );
    expect(screen.getByText('Действует')).toBeInTheDocument();
    expect(screen.getByText(/Отклик отправлен/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Отозвать' }));
    const confirmDialog = await screen.findByRole('alertdialog');
    await user.click(within(confirmDialog).getByRole('button', { name: 'Да' }));

    await waitFor(() => expect(screen.getByText('Отозвано исполнителем')).toBeInTheDocument());
  });
});

describe('биржевое назначение: адрес скрыт до подтверждения', () => {
  it('до принятия адреса нет, после принятия — есть', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'marketplace', urgency: 'normal' },
    });
    const published = await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/publish-search`,
      managerAuth,
      {
        body: { attachment_ids: [], confirm_sensitive: false },
      },
    );

    const providerAuth = await demoLoginRaw('provider_active_admin');
    const offer = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, providerAuth, {
      body: { amount_minor: 200000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
    });
    await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/select-offer`, managerAuth, {
      body: {
        offer_id: offer.id,
        offer_version: offer.version,
        expected_version: published.version,
      },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${draft.id}`;

    await screen.findByText(/Адрес и контакты появятся после подтверждения назначения/);
    const hidden = await apiCall<RequestProvider>(`/requests/${draft.id}`, providerAuth);
    expect(hidden.customer_org_name ?? null).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Принять' }));

    await waitFor(() =>
      expect(
        screen.queryByText(/Адрес и контакты появятся после подтверждения назначения/),
      ).not.toBeInTheDocument(),
    );
    await screen.findByText(/ · ул\. Тверская/);
    const shown = await apiCall<RequestProvider>(`/requests/${draft.id}`, providerAuth);
    expect(shown.customer_org_name).toBeTruthy();
    expect(
      await screen.findAllByText(`${shown.customer_org_name} · Заявка Р-${shown.request_number}`),
    ).not.toHaveLength(0);
  });
});

describe('смета ремонта не согласовывается вместе с выездом', () => {
  it('после согласования выезда смета остаётся «не согласовано» до отдельного решения заказчика', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
    });
    await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/submit-to-own-service`,
      managerAuth,
      {
        body: { photos_incomplete: false, photos_incomplete_reason: null },
      },
    );

    const providerAuth = await demoLoginRaw('provider_active_admin');
    const pendingView = await apiCall<{ assignment: { id: string } }>(
      `/requests/${draft.id}`,
      providerAuth,
    );
    const assignmentId = pendingView.assignment.id;
    await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
      body: { assignment_id: assignmentId },
    });

    await apiCall(`/requests/${draft.id}/actions/propose-visit`, providerAuth, {
      body: { assignment_id: assignmentId, amount_minor: 100000, currency: 'RUB' },
    });
    const withProposal = await apiCall<RequestCustomer>(`/requests/${draft.id}`, managerAuth);
    const proposal = withProposal.visit_proposals[0]!;
    await apiCall(`/requests/${draft.id}/actions/approve-visit-proposal`, managerAuth, {
      body: {
        proposal_id: proposal.id,
        proposal_version: proposal.version,
        expected_version: withProposal.version,
      },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${draft.id}`;

    await screen.findByRole('button', { name: 'Я выехал' });
    expect(screen.queryByRole('button', { name: 'Заказчик согласовал' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Предложить цену ремонта' }));
    await user.click(await screen.findByRole('button', { name: 'Добавить позицию' }));
    const line = await screen.findByRole('dialog');
    await user.type(within(line).getByLabelText('Работа или деталь'), 'Замена компрессора');
    await user.type(within(line).getByLabelText('Сумма, ₽'), '8000');
    await user.click(within(line).getByRole('button', { name: 'Добавить' }));
    expect(screen.getByText('8 000 ₽', { selector: '.ui-price__value' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить на согласование' }));

    await waitFor(() => expect(screen.getAllByText('Не согласовано').length).toBeGreaterThan(0));
    expect(screen.getByText('Согласовано')).toBeInTheDocument();
  });
});

describe('ответ исполнителя на запрос отмены', () => {
  it('исполнитель может не согласиться — заявка переходит в спор', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
    });
    await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/submit-to-own-service`,
      managerAuth,
      {
        body: { photos_incomplete: false, photos_incomplete_reason: null },
      },
    );
    const providerAuth = await demoLoginRaw('provider_active_admin');
    const beforeAccept = await apiCall<{ assignment: { id: string } }>(
      `/requests/${draft.id}`,
      providerAuth,
    );
    await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
      body: { assignment_id: beforeAccept.assignment.id },
    });
    const accepted = await apiCall<RequestCustomer>(`/requests/${draft.id}`, managerAuth);
    await apiCall(`/requests/${draft.id}/actions/request-cancellation`, managerAuth, {
      body: { target: 'cancel_request', reason: 'Передумали', expected_version: accepted.version },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${draft.id}`;

    await screen.findByText('Заказчик просит отменить заявку');
    await user.click(screen.getByRole('button', { name: 'Не согласен' }));
    const sheet = await screen.findByRole('dialog');
    expect(within(sheet).getByRole('button', { name: 'Отправить ответ' })).toBeDisabled();
    await user.type(within(sheet).getByPlaceholderText('Комментарий'), 'Уже выехал мастер');
    await user.click(within(sheet).getByRole('button', { name: 'Отправить ответ' }));

    await waitFor(() => expect(screen.getByText('Исполнитель не согласен')).toBeInTheDocument());
  });
});

describe('отказ исполнителя от принятой заявки', () => {
  it('после отказа заявка больше не открывается со стороны этого исполнителя', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
    });
    await apiCall<RequestCustomer>(
      `/requests/${draft.id}/actions/submit-to-own-service`,
      managerAuth,
      {
        body: { photos_incomplete: false, photos_incomplete_reason: null },
      },
    );
    const providerAuth = await demoLoginRaw('provider_active_admin');
    const before = await apiCall<{ assignment: { id: string } }>(
      `/requests/${draft.id}`,
      providerAuth,
    );
    await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
      body: { assignment_id: before.assignment.id },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${draft.id}`;

    await screen.findByRole('button', { name: 'Отказаться от заявки' });
    await user.click(screen.getByRole('button', { name: 'Отказаться от заявки' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByRole('button', { name: 'Отказаться от заявки' })).toBeDisabled();
    await user.type(
      within(dialog).getByPlaceholderText('Причина отказа'),
      'Не хватает специалиста нужного профиля',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Отказаться от заявки' }));

    await waitFor(() =>
      expect(screen.getByText(/назначение по этой заявке прекращено/i)).toBeInTheDocument(),
    );
  });
});

async function scheduledRequest(): Promise<{ id: string; assignmentId: string }> {
  const managerAuth = await demoLoginRaw('customer_manager');
  const equipmentId = await boschEquipmentId(managerAuth);
  const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
    body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
  });
  await apiCall(`/requests/${draft.id}/actions/submit-to-own-service`, managerAuth, {
    body: { photos_incomplete: false, photos_incomplete_reason: null },
  });
  const providerAuth = await demoLoginRaw('provider_active_admin');
  const view = await apiCall<{ assignment: { id: string } }>(`/requests/${draft.id}`, providerAuth);
  const assignmentId = view.assignment.id;
  await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
    body: { assignment_id: assignmentId },
  });
  await apiCall(`/requests/${draft.id}/actions/propose-visit`, providerAuth, {
    body: { assignment_id: assignmentId, amount_minor: 100000, currency: 'RUB' },
  });
  const withProposal = await apiCall<RequestCustomer>(`/requests/${draft.id}`, managerAuth);
  const proposal = withProposal.visit_proposals[0]!;
  await apiCall(`/requests/${draft.id}/actions/approve-visit-proposal`, managerAuth, {
    body: {
      proposal_id: proposal.id,
      proposal_version: proposal.version,
      expected_version: withProposal.version,
    },
  });
  return { id: draft.id, assignmentId };
}

describe('ход работ исполнителя: отметка выезда', () => {
  it('«Я выехал» ставит отметку, шаг «Выехал» пройден, дальше — «Я на месте»', async () => {
    const { id } = await scheduledRequest();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${id}`;

    await user.click(await screen.findByRole('button', { name: 'Я выехал' }));

    await screen.findByRole('heading', { name: 'В пути' });
    expect(screen.queryByRole('button', { name: 'Я выехал' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Я на месте' })).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Ход работ' });
    expect(within(steps).getByText('Выехал')).toBeInTheDocument();
    expect(within(steps).queryByText('Выезд согласован')).not.toBeInTheDocument();
  });

  it('повторная отметка (409 ALREADY_EN_ROUTE) — не ошибка: карточка перечитывается', async () => {
    const { id, assignmentId } = await scheduledRequest();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${id}`;
    await screen.findByRole('button', { name: 'Я выехал' });

    const providerAuth = await demoLoginRaw('provider_active_admin');
    const fresh = await apiCall<{ version: number }>(`/requests/${id}`, providerAuth);
    await apiCall(`/requests/${id}/actions/mark-en-route`, providerAuth, {
      body: { assignment_id: assignmentId, expected_version: fresh.version },
    });
    server.use(
      http.post('*/requests/:id/actions/mark-en-route', () =>
        HttpResponse.json(
          {
            error: { code: 'ALREADY_EN_ROUTE', message: 'Выезд уже отмечен', request_id: 'req_test' },
          },
          { status: 409 },
        ),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Я выехал' }));

    await screen.findByRole('heading', { name: 'В пути' });
    expect(screen.queryByText('Выезд уже отмечен')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
