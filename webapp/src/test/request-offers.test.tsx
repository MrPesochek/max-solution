import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { Offer, RequestCustomer } from '../api/types';

describe('предложения исполнителей: сравнение и выбор', () => {
  it('просроченное предложение нельзя выбрать, цена null показана как «Цена неизвестна»', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const locs = await apiCall<{ items: { id: string }[] }>('/locations', managerAuth);
    const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
      `/equipment?location_id=${locs.items[0]!.id}`,
      managerAuth,
    );
    const bosch = eq.items.find((e) => e.brand === 'Bosch')!;

    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      method: 'POST',
      body: { equipment_id: bosch.id, route: 'marketplace', urgency: 'normal' },
    });
    const published = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/publish-search`, managerAuth, {
      method: 'POST',
      body: { attachment_ids: [], confirm_sensitive: false },
    });
    expect(published.status).toBe('searching');

    const providerA = await demoLoginRaw('provider_active_admin');
    const providerB = await demoLoginRaw('provider_admin');

    const priced = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, providerA, {
      body: {
        visit_window_start: '2026-10-01T09:00:00Z',
        visit_window_end: '2026-10-01T12:00:00Z',
        amount_minor: 250000,
        currency: 'RUB',
        vat_mode: 'included',
        scope_description: 'Диагностика и выезд мастера',
        valid_until: '2026-12-31T00:00:00Z',
      },
    });
    expect(priced.price.is_known).toBe(true);

    const unknownPrice = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, providerB, {
      body: {
        visit_window_start: '2026-10-02T09:00:00Z',
        visit_window_end: '2026-10-02T12:00:00Z',
        amount_minor: null,
        scope_description: 'Нужен осмотр на месте для оценки',
        valid_until: '2026-12-31T00:00:00Z',
      },
    });
    expect(unknownPrice.price.is_known).toBe(false);

    const providerC = await demoLoginRaw('provider_needs_info_admin');
    await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, providerC, {
      body: {
        amount_minor: 100000,
        currency: 'RUB',
        valid_until: '2020-01-01T00:00:00Z', // заведомо истёкшее
      },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${draft.id}/offers`;

    await screen.findByRole('heading', { name: 'Предложения' });

    await waitFor(() => expect(screen.getByText('Цена неизвестна')).toBeInTheDocument());
    expect(screen.getAllByText('Срок истёк').length).toBeGreaterThan(0);

    expect(screen.getByText('Сервис-Холод Плюс')).toBeInTheDocument();
    expect(screen.getByText('★ 4,6 · 12 отзывов')).toBeInTheDocument();

    expect(screen.getByText(/Диагностика и выезд мастера · до /)).toBeInTheDocument();
    const cards = screen.getAllByRole('radio');
    const expired = cards.filter((card) => /Срок истёк/.test(card.textContent ?? ''));
    expect(expired).toHaveLength(1);
    expect(expired[0]).toBeDisabled();

    const expiredName = within(expired[0]!).getByText(/./, { selector: '.ui-choice__title' }).textContent!;
    await user.click(screen.getByRole('link', { name: `Подробнее: ${expiredName}` }));
    await screen.findByText('Предложение недоступно');
    expect(screen.queryByRole('button', { name: /^Выбрать/ })).not.toBeInTheDocument();
    window.history.back();

    await user.click(await screen.findByRole('link', { name: /Подробнее: Сервис-Холод Плюс/ }));
    await user.click(await screen.findByRole('button', { name: /Выбрать за 2.500 ₽/ }));
    await screen.findByText('Выбрать это предложение?');
    await user.click(screen.getByRole('button', { name: 'Подтвердить выбор' }));

    await waitFor(() => expect(screen.getByText('Ждём подтверждения исполнителя')).toBeInTheDocument());
  });

  it('исполнитель обновил предложение, пока руководитель подтверждал выбор, — OFFER_NOT_CURRENT и актуальная версия', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const locs = await apiCall<{ items: { id: string }[] }>('/locations', managerAuth);
    const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
      `/equipment?location_id=${locs.items[0]!.id}`,
      managerAuth,
    );
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      method: 'POST',
      body: { equipment_id: eq.items.find((e) => e.brand === 'Bosch')!.id, route: 'marketplace', urgency: 'normal' },
    });
    await apiCall(`/requests/${draft.id}/actions/publish-search`, managerAuth, {
      method: 'POST',
      body: { attachment_ids: [], confirm_sensitive: false },
    });
    const provider = await demoLoginRaw('provider_active_admin');
    const first = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, provider, {
      body: { amount_minor: 150000, currency: 'RUB', valid_until: '2026-12-31T00:00:00Z' },
    });
    expect(first.version).toBe(1);

    const selectBodies: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/actions/select-offer')) {
        void request
          .clone()
          .json()
          .then((body: unknown) => selectBodies.push(body));
      }
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${draft.id}/offers/${first.id}`;
    await user.click(await screen.findByRole('button', { name: /Выбрать за 1.500 ₽/ }));
    await screen.findByText('Выбрать это предложение?');

    const second = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, provider, {
      body: { amount_minor: 180000, currency: 'RUB', valid_until: '2026-12-31T00:00:00Z' },
    });
    expect(second.version).toBe(2);

    await user.click(screen.getByRole('button', { name: 'Подтвердить выбор' }));
    await screen.findByText(
      'Исполнитель обновил предложение — проверьте актуальные условия и подтвердите выбор ещё раз.',
    );
    expect(screen.getByText('Выбрать это предложение?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Подтвердить выбор' }));
    await waitFor(() => expect(screen.getByText('Ждём подтверждения исполнителя')).toBeInTheDocument());
    expect(selectBodies).toEqual([
      expect.objectContaining({ offer_id: first.id, offer_version: 1 }),
      expect.objectContaining({ offer_id: second.id, offer_version: 2 }),
    ]);
    server.events.removeAllListeners();
  });
});
