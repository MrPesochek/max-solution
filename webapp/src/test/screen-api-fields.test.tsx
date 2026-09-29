import { cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '../mocks/server';
import * as db from '../mocks/db';
import * as rdb from '../mocks/requestsDb';
import { seedPendingPortfolioAttachment } from '../mocks/portfolio';
import type { Attachment, Offer, ProviderCatalogItem, RequestCustomer } from '../api/types';
import { findHomeScreen, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

type Auth = { token: string; organizationId: string };

async function boschId(auth: Auth): Promise<string> {
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>('/equipment', auth);
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function acceptedOwnServiceRequest() {
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
  const assignmentId = submitted.assignment!.id;
  const provider = await demoLoginRaw('provider_active_admin');
  await apiCall(`/requests/${draft.id}/actions/accept`, provider, {
    body: { assignment_id: assignmentId },
  });
  return {
    manager,
    provider,
    requestId: draft.id,
    requestNumber: draft.request_number,
    assignmentId,
  };
}

function tomorrowAt18(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(18, 0, 0, 0);
  return date.toISOString();
}

function trackOfferLookups(): string[] {
  const lookups: string[] = [];
  server.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET' && /\/requests\/[^/]+\/offers$/.test(path)) lookups.push(path);
  });
  return lookups;
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

describe('главная (D07): «Нужно ваше решение» из pending_decision', () => {
  it('строки выезда и предложений показывают сумму, срок и число предложений без запросов /offers', async () => {
    const { provider, requestId, assignmentId } = await acceptedOwnServiceRequest();
    await apiCall(`/requests/${requestId}/actions/propose-visit`, provider, {
      body: {
        assignment_id: assignmentId,
        amount_minor: 350000,
        currency: 'RUB',
        valid_until: tomorrowAt18(),
      },
    });

    const manager = await demoLoginRaw('customer_manager');
    const market = await apiCall<RequestCustomer>('/requests', manager, {
      body: { equipment_id: await boschId(manager), route: 'marketplace', urgency: 'normal' },
    });
    await apiCall(`/requests/${market.id}/actions/publish-search`, manager, {
      body: { attachment_ids: [], confirm_sensitive: false },
    });
    await apiCall<Offer>(`/marketplace/requests/${market.id}/offers`, provider, {
      body: { amount_minor: 200000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
    });

    const lookups = trackOfferLookups();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    const section = within(
      (await screen.findByRole('heading', { name: 'Нужно ваше решение' })).closest('section')!,
    );
    const visit = await section.findByRole('link', { name: /Согласуйте выезд/ });
    expect(visit).toHaveTextContent('Холодильник Bosch');
    expect(visit).toHaveTextContent('Выезд 3 500 ₽ · ответить до завтра 18:00');
    const offers = await section.findByRole('link', { name: /Выберите исполнителя/ });
    expect(offers).toHaveTextContent('1 предложение');
    expect(offers).toHaveAttribute(
      'href',
      expect.stringContaining(`/requests/${market.id}/offers`),
    );
    expect(lookups).toEqual([]);
  });
});

describe('списки заявок: название техники из категории и бренда', () => {
  it('«Мои заявки» показывают «Холодильник Bosch», а не модель', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
    });
    await apiCall(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
      body: { photos_incomplete: true, photos_incomplete_reason: 'Без фото' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Заявки' }));
    await screen.findByRole('heading', { name: 'Заявки' });
    const rows = await screen.findAllByRole('link', { name: /^Холодильник Bosch/ });
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.queryByRole('link', { name: /^Bosch KGN39VL316/ })).not.toBeInTheDocument();
  });

  it('«Входящие» исполнителя — тоже «Холодильник Bosch»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
    });
    await apiCall(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
      body: { photos_incomplete: true, photos_incomplete_reason: 'Без фото' },
    });
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('tab', { name: 'Входящие', selected: true });
    expect(
      (await screen.findAllByRole('link', { name: /^Холодильник Bosch/ })).length,
    ).toBeGreaterThan(0);
  });
});

describe('карточка техники (D10): заявки по equipment_id и подписи слотов фото', () => {
  it('заявки другой техники той же точки не попадают в блок «Заявки»; фото подписаны слотом', async () => {
    const { requestNumber } = await acceptedOwnServiceRequest();
    const manager = await demoLoginRaw('customer_manager');
    const eq = await apiCall<{ items: { id: string; brand: string; location_id: string }[] }>(
      '/equipment',
      manager,
    );
    const saeco = eq.items.find((e) => e.brand === 'Saeco')!;
    const saecoDraft = await apiCall<RequestCustomer>('/requests', manager, {
      body: {
        equipment_id: saeco.id,
        route: 'marketplace',
        urgency: 'normal',
        symptom_description: 'Не греет',
      },
    });
    const bosch = eq.items.find((e) => e.brand === 'Bosch')!;

    const photo: Attachment = {
      id: 'att_slot_overview',
      owner_kind: 'equipment',
      request_id: null,
      message_id: null,
      equipment_id: bosch.id,
      slot: 'nameplate',
      visibility_class: 'request_sensitive',
      processing_state: 'ready',
      publication_state: null,
      rejected_reason: null,
      mime_type: 'image/png',
      byte_size: 4,
      pixel_width: null,
      pixel_height: null,
      created_at: new Date().toISOString(),
    };
    server.use(
      http.get('*/equipment/:id/photos', ({ params }) =>
        HttpResponse.json(params.id === bosch.id ? [photo] : []),
      ),
      http.get(
        '*/attachments/:id/content',
        () => new HttpResponse(new Uint8Array([1]), { headers: { 'Content-Type': 'image/png' } }),
      ),
    );

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${bosch.location_id}/${bosch.id}?tab=specs`;
    await screen.findByRole('heading', { name: /Bosch KGN39VL316/ });

    expect(await screen.findByText('Шильдик')).toBeInTheDocument();
    expect(
      await screen.findByRole('img', { name: 'Холодильник Bosch KGN39VL316: Шильдик' }),
    ).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('tab', { name: 'История' }));
    const requests = within(await screen.findByRole('list', { name: 'История' }));
    expect(
      await requests.findByRole('link', { name: new RegExp(`^Р-${requestNumber}:`) }),
    ).toBeInTheDocument();
    expect(
      requests.queryByRole('link', { name: new RegExp(`^Р-${saecoDraft.request_number}:`) }),
    ).toBeNull();
  });
});

describe('каталог и профиль исполнителя (D24)', () => {
  const base: Omit<
    ProviderCatalogItem,
    'id' | 'name' | 'rating' | 'rating_label' | 'reviews_count' | 'unique_customers'
  > = {
    provider_kind: 'company',
    categories: [{ id: 'cat_fridge', code: 'fridge', name: 'Витрины' }],
    service_areas: [],
    accepting_new_requests: true,
    details_verified: true,
    representative_verified: true,
  };

  it('тег рейтинга: «★ 4,7 · 9 организаций», при подписи сервера или < 3 организаций — «Мало отзывов»', async () => {
    server.use(
      http.get('*/providers', () =>
        HttpResponse.json({
          items: [
            {
              ...base,
              id: 'org_a',
              name: 'Северный холод',
              rating: 4.7,
              rating_label: null,
              reviews_count: 14,
              unique_customers: 9,
            },
            {
              ...base,
              id: 'org_b',
              name: 'Полюс',
              rating: null,
              rating_label: 'Мало отзывов',
              reviews_count: 2,
              unique_customers: 2,
            },
            {
              ...base,
              id: 'org_c',
              name: 'Игорь Малов',
              rating: 4.9,
              rating_label: null,
              reviews_count: 2,
              unique_customers: 2,
            },
          ],
          next_cursor: null,
        }),
      ),
    );
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/providers';

    expect(await screen.findByRole('link', { name: /^Северный холод/ })).toHaveTextContent(
      '★ 4,7 · 9 организаций',
    );
    expect(screen.getByRole('link', { name: /^Полюс/ })).toHaveTextContent('Мало отзывов');
    expect(screen.getByRole('link', { name: /^Игорь Малов/ })).toHaveTextContent('Мало отзывов');
  });

  it('галерея — id вложений: «Работы · 2 фото», превью через приватную выдачу', async () => {
    const provider = db.listProviderCatalog({}).items[0]!;
    const photos = [seedPendingPortfolioAttachment(provider.id), seedPendingPortfolioAttachment(provider.id)];
    for (const photo of photos) rdb.approveModeratedAttachment(photo.id);
    const contentRequests: string[] = [];
    server.events.on('request:start', ({ request }) => {
      const match = /\/attachments\/([^/]+)\/content/.exec(new URL(request.url).pathname);
      if (match) contentRequests.push(match[1]!);
    });
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/providers/${provider.id}`;
    await screen.findByRole('heading', { name: 'Работы' });
    const grid = within(screen.getByRole('group', { name: 'Галерея работ' }));
    await waitFor(() => expect(grid.getAllByRole('img')).toHaveLength(2));
    await waitFor(() => expect(grid.getAllByRole('img')[0]).toHaveAttribute('src', 'blob:preview'));
    await waitFor(() => expect(contentRequests.sort()).toEqual(photos.map((p) => p.id).sort()));
  });
});
