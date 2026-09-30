import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { RequestCustomer } from '../api/types';

type Auth = { token: string; organizationId: string };

async function boschId(auth: Auth): Promise<string> {
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', auth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function declinedOwnService(): Promise<RequestCustomer> {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    method: 'POST',
    body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal', symptom_description: 'Не морозит' },
  });
  const submitted = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
    method: 'POST',
    body: { photos_incomplete: true, photos_incomplete_reason: 'не требуется для теста' },
  });
  const provider = await demoLoginRaw('provider_active_admin');
  await apiCall(`/requests/${draft.id}/actions/decline`, provider, {
    method: 'POST',
    body: { assignment_id: submitted.assignment!.id, reason: 'Нет мастера на эту дату' },
  });
  return apiCall<RequestCustomer>(`/requests/${draft.id}`, manager);
}

async function stoppedSearch(): Promise<RequestCustomer> {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    method: 'POST',
    body: { equipment_id: await boschId(manager), route: 'marketplace', urgency: 'normal' },
  });
  await apiCall(`/requests/${draft.id}/actions/publish-search`, manager, {
    method: 'POST',
    body: { published_description: 'Витрина не охлаждает', attachment_ids: [], confirm_sensitive: false },
  });
  await apiCall(`/requests/${draft.id}/actions/request-cancellation`, manager, {
    method: 'POST',
    body: { target: 'change_provider', reason: 'Уточним условия' },
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

describe('изменение условий заявки, которой нужно решение', () => {
  it('руководитель меняет описание и срочность; уходят только изменения и версия заявки', async () => {
    const request = await declinedOwnService();
    expect(request.status).toBe('action_required');
    const bodies = captureActionBodies('update-details');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}`;

    await user.click(await screen.findByRole('button', { name: 'Изменить условия' }));
    await screen.findByRole('heading', { name: 'Изменить условия' });
    const save = await screen.findByRole('button', { name: 'Сохранить условия' });
    await user.click(save);
    expect(await screen.findByText(/Условия не изменились/)).toBeInTheDocument();
    expect(bodies).toEqual([]);
    expect(screen.queryByLabelText('Район')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Описание для карточки')).not.toBeInTheDocument();

    const description = await screen.findByLabelText('Описание неисправности');
    await user.clear(description);
    await user.type(description, 'Не морозит, на дисплее ошибка E5');
    await user.click(screen.getByRole('radio', { name: '1–3 дня' }));
    await user.click(save);

    await user.click(await screen.findByRole('button', { name: /^(Подробнее|Показать полностью)/ }));
    await screen.findByText('Не морозит, на дисплее ошибка E5');
    expect(bodies).toEqual([
      {
        symptom_description: 'Не морозит, на дисплее ошибка E5',
        urgency: 'urgent',
        expected_version: request.version,
      },
    ]);

    await user.click(await screen.findByRole('button', { name: /^История/ }));
    expect(await screen.findByText('Условия заявки изменены')).toBeInTheDocument();
    server.events.removeAllListeners();
  });

  it('у публиковавшейся заявки меняются район и описание для карточки; остановка подбора видна в истории', async () => {
    const request = await stoppedSearch();
    expect(request.status).toBe('action_required');
    const bodies = captureActionBodies('update-details');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${request.id}/details`;

    await screen.findByRole('heading', { name: 'Изменить условия' });
    const cardDescription = await screen.findByLabelText('Описание для карточки');
    expect(cardDescription).toHaveValue('Витрина не охлаждает');
    await user.clear(cardDescription);
    await user.type(cardDescription, 'Витрина не охлаждает, нужен выезд утром');
    await user.click(await screen.findByRole('button', { name: 'Сохранить условия' }));
    expect(await screen.findByText(/Опишите, что случилось/)).toBeInTheDocument();
    expect(bodies).toEqual([]);
    await user.type(screen.getByLabelText('Описание неисправности'), 'Не охлаждает');
    await user.click(screen.getByRole('button', { name: 'Сохранить условия' }));

    await screen.findByRole('button', { name: /^История/ });
    await waitFor(() =>
      expect(bodies).toEqual([
        {
          symptom_description: 'Не охлаждает',
          published_description: 'Витрина не охлаждает, нужен выезд утром',
          expected_version: request.version,
        },
      ]),
    );
    await user.click(await screen.findByRole('button', { name: /^История/ }));
    expect(await screen.findByText('Подбор исполнителя остановлен')).toBeInTheDocument();
    expect(screen.getByText('Условия заявки изменены')).toBeInTheDocument();
    server.events.removeAllListeners();
  });

  it('сервер (мок) требует expected_version: без неё — 422, с устаревшей — 409 VERSION_CONFLICT', async () => {
    const request = await declinedOwnService();
    const manager = await demoLoginRaw('customer_manager');
    const post = (body: unknown) =>
      fetch(`/app-api/v1/requests/${request.id}/actions/update-details`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${manager.token}`,
          'X-Organization-Id': manager.organizationId,
          'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify(body),
      });

    const missing = await post({ symptom_description: 'Новое описание' });
    expect(missing.status).toBe(422);

    const stale = await post({ symptom_description: 'Новое описание', expected_version: request.version - 1 });
    expect(stale.status).toBe(409);
    expect(((await stale.json()) as { error: { code: string } }).error.code).toBe('VERSION_CONFLICT');

    const district = await post({ district_id: 'dist_msk_c', expected_version: request.version });
    expect(district.status).toBe(422);
  });
});
