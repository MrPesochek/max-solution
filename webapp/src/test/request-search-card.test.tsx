import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { Offer, RequestCustomer } from '../api/types';

type Auth = { token: string; organizationId: string };

async function equipmentId(auth: Auth, brand: string): Promise<string> {
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', auth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === brand)!.id;
}

async function publishedRequest(manager: Auth, brand: string, description: string): Promise<RequestCustomer> {
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    method: 'POST',
    body: { equipment_id: await equipmentId(manager, brand), route: 'marketplace', urgency: 'normal' },
  });
  await apiCall(`/requests/${draft.id}/actions/publish-search`, manager, {
    method: 'POST',
    body: { published_description: description, attachment_ids: [], confirm_sensitive: false },
  });
  return apiCall<RequestCustomer>(`/requests/${draft.id}`, manager);
}

function captureActionBodies(action: string): unknown[] {
  const bodies: unknown[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith(`/actions/${action}`)) {
      void request
        .clone()
        .json()
        .then((body: unknown) => bodies.push(body));
    }
  });
  return bodies;
}

describe('S2 из карточки заявки: публикация → отклики → сравнение → выбор', () => {
  it('карточка показывает число исполнителей, предложения и ведёт к выбору', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const request = await publishedRequest(manager, 'Bosch', 'Витрина не охлаждает');
    expect(request.status).toBe('searching');
    expect(request.search).toMatchObject({ published: true, matched_providers: 2 });
    expect(request.search?.public_card?.published_description).toBe('Витрина не охлаждает');

    const providerA = await demoLoginRaw('provider_active_admin');
    const providerB = await demoLoginRaw('provider_admin');
    for (const [auth, amount] of [
      [providerA, 250000],
      [providerB, 180000],
    ] as const) {
      await apiCall<Offer>(`/marketplace/requests/${request.id}/offers`, auth, {
        body: { amount_minor: amount, currency: 'RUB', vat_mode: 'included', valid_until: '2026-12-31T00:00:00Z' },
      });
    }

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    await screen.findByText('Ищем исполнителя');
    await screen.findByText(/Заявку видят 2 исполнителя .*Уже есть 2 предложения/);
    expect(screen.getByText(/опубликовано в/)).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: 'Сравнить предложения' }));
    await screen.findByRole('heading', { name: 'Предложения' });
    expect(screen.getAllByRole('radio')).toHaveLength(2);

    await user.click(await screen.findByRole('link', { name: /Подробнее: Сервис-Холод Плюс/ }));
    await user.click(await screen.findByRole('button', { name: /^Выбрать за/ }));
    await screen.findByText('Выбрать это предложение?');
    await user.click(screen.getByRole('button', { name: 'Подтвердить выбор' }));
    await waitFor(() => expect(screen.getByText('Ждём подтверждения исполнителя')).toBeInTheDocument());

    const waiting = await apiCall<RequestCustomer>(`/requests/${request.id}`, manager);
    expect(waiting.status).toBe('awaiting_assignment_confirmation');
    expect(waiting.search?.published).toBe(true);
  });

  it('до публикации поиска в карточке нет', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      method: 'POST',
      body: { equipment_id: await equipmentId(manager, 'Bosch'), route: 'marketplace', urgency: 'normal' },
    });
    const card = await apiCall<RequestCustomer>(`/requests/${draft.id}`, manager);
    expect(card.search).toBeNull();
  });

  it('нет подходящих исполнителей: карточка не публикуется, герой «Рядом нет исполнителей»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const request = await publishedRequest(manager, 'Saeco', 'Не варит кофе');
    expect(request.status).toBe('action_required');
    expect(request.search).toMatchObject({ published: false, matched_providers: 0 });

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    await screen.findByText('Рядом нет исполнителей');
    expect(screen.queryByText('Сравнить предложения')).not.toBeInTheDocument();
  });

  it('повторная публикация сохраняет район и описание, уточнённые в «Изменить условия»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const request = await publishedRequest(manager, 'Saeco', 'Не варит кофе');
    await apiCall(`/requests/${request.id}/actions/update-details`, manager, {
      method: 'POST',
      body: {
        district_id: 'dist_msk_s',
        published_description: 'Не варит кофе, течёт вода',
        expected_version: request.version,
      },
    });
    const bodies = captureActionBodies('publish-search');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}/publish`;

    await screen.findByRole('heading', { name: 'Что увидят исполнители' });
    expect(await screen.findByLabelText(/Описание/, { selector: 'textarea' })).toHaveValue('Не варит кофе, течёт вода');
    const preview = screen.getByLabelText('Так увидят исполнители');
    await waitFor(() => expect(within(preview).getByText('Южный')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Опубликовать' }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ district_id: null, published_description: 'Не варит кофе, течёт вода' });

    const after = await apiCall<RequestCustomer>(`/requests/${request.id}`, manager);
    expect(after.search?.public_card?.district_id).toBe('dist_msk_s');
    expect(after.search?.public_card?.published_description).toBe('Не варит кофе, течёт вода');
    server.events.removeAllListeners();
  });
});
