import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import type { RequestCustomer } from '../api/types';

async function createAcceptedOwnServiceRequest() {
  const managerAuth = await demoLoginRaw('customer_manager');
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', managerAuth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    managerAuth,
  );
  const bosch = eq.items.find((e) => e.brand === 'Bosch')!;

  const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
    method: 'POST',
    body: { equipment_id: bosch.id, route: 'own_service', urgency: 'normal' },
  });
  const submitted = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/submit-to-own-service`, managerAuth, {
    method: 'POST',
    body: { photos_incomplete: true, photos_incomplete_reason: 'Фото не требуются для теста' },
  });
  const assignmentId = (submitted as unknown as { assignment: { id: string } }).assignment.id;

  const providerAuth = await demoLoginRaw('provider_active_admin');
  await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
    method: 'POST',
    body: { assignment_id: assignmentId },
  });

  return { managerAuth, providerAuth, requestId: draft.id, assignmentId };
}

describe('согласование выезда', () => {
  it('руководитель согласует условия выезда; при устаревшей версии — актуальные условия и повторное подтверждение', async () => {
    const { providerAuth, requestId, assignmentId } = await createAcceptedOwnServiceRequest();

    await apiCall(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
      method: 'POST',
      body: {
        assignment_id: assignmentId,
        visit_window_start: '2026-10-05T10:00:00Z',
        visit_window_end: '2026-10-05T13:00:00Z',
        amount_minor: 150000,
        currency: 'RUB',
        vat_mode: 'not_applicable',
        scope_description: 'Выезд и диагностика',
        valid_until: '2026-12-31T00:00:00Z',
      },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await screen.findByText('Предложение выезда · версия 1');
    expect(screen.getByRole('button', { name: /Согласовать 1.500 ₽/ })).toBeInTheDocument();

    await apiCall(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
      method: 'POST',
      body: {
        assignment_id: assignmentId,
        visit_window_start: '2026-10-06T10:00:00Z',
        visit_window_end: '2026-10-06T13:00:00Z',
        amount_minor: 180000,
        currency: 'RUB',
        valid_until: '2026-12-31T00:00:00Z',
      },
    });

    await user.click(screen.getByRole('button', { name: /Согласовать 1.500 ₽/ }));

    await screen.findByText('Версия 2 заменила версию 1');
    expect(screen.getByText('Предложение выезда · версия 2')).toBeInTheDocument();
    expect(screen.getByText(/1.500 ₽/).tagName).toBe('S');

    await user.click(screen.getByRole('button', { name: /Согласовать 1.800 ₽/ }));

    await waitFor(() => expect(screen.getByText('Выезд согласован')).toBeInTheDocument());
  });

  it('ссылка на заменённую версию: экран «Эти условия уже заменены», затем актуальные условия', async () => {
    const { providerAuth, requestId, assignmentId } = await createAcceptedOwnServiceRequest();
    const propose = (amount: number) =>
      apiCall<RequestCustomer>(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
        method: 'POST',
        body: {
          assignment_id: assignmentId,
          visit_window_start: '2026-10-05T10:00:00Z',
          visit_window_end: '2026-10-05T13:00:00Z',
          amount_minor: amount,
          currency: 'RUB',
          valid_until: '2026-12-31T00:00:00Z',
        },
      });
    const first = await propose(150000);
    const firstProposalId = first.visit_proposals.find((p) => p.version === 1)!.id;
    await propose(210000);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/visit-proposals/${firstProposalId}`;

    await screen.findByRole('heading', { name: 'Эти условия уже заменены' });
    expect(screen.queryByRole('button', { name: /Согласовать/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Посмотреть новые условия' }));

    await screen.findByText('Предложение выезда · версия 2');
    expect(screen.getByRole('button', { name: /Согласовать 2.100 ₽/ })).toBeInTheDocument();
  });
});

async function scheduledWithQuote(amounts: (number | null)[]) {
  const acc = await createAcceptedOwnServiceRequest();
  const { managerAuth, providerAuth, requestId, assignmentId } = acc;
  await apiCall(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
    method: 'POST',
    body: { assignment_id: assignmentId, amount_minor: 350000, currency: 'RUB', valid_until: '2026-12-31T00:00:00Z' },
  });
  const withVisit = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
  await apiCall(`/requests/${requestId}/actions/approve-visit-proposal`, managerAuth, {
    method: 'POST',
    body: { proposal_id: withVisit.visit_proposals[0]!.id, proposal_version: 1 },
  });
  let last: RequestCustomer | null = null;
  for (const amount of amounts) {
    last = await apiCall<RequestCustomer>(`/requests/${requestId}/actions/create-repair-quote`, providerAuth, {
      method: 'POST',
      body: {
        assignment_id: assignmentId,
        description_of_work: 'Замена пускового реле и заправка фреоном',
        amount_minor: amount,
        currency: 'RUB',
        zero_cost_reason: amount === 0 ? 'Гарантия сервиса' : null,
        valid_until: '2026-12-31T00:00:00Z',
      },
    });
  }
  return { ...acc, quotes: last!.repair_quotes };
}

describe('согласование ремонта', () => {
  it('карточка ведёт к смете; отклонение уходит с причиной и комментарием', async () => {
    const { requestId, quotes } = await scheduledWithQuote([670000]);
    const bodies: unknown[] = [];
    const onStart = ({ request }: { request: Request }) => {
      if (new URL(request.url).pathname.endsWith('/actions/reject-repair-quote')) {
        void request
          .clone()
          .json()
          .then((body: unknown) => bodies.push(body));
      }
    };
    server.events.on('request:start', onStart);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await screen.findByText('Выезд согласован');
    await user.click(await screen.findByRole('button', { name: 'Согласовать ремонт' }));

    await screen.findByRole('heading', { name: 'Цена ремонта' });
    expect(screen.getByText('Замена пускового реле и заправка фреоном')).toBeInTheDocument();
    expect(screen.getByText(/Выезд и диагностика \(3.500 ₽\) согласованы отдельно/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Согласовать 6.700 ₽/ })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Отказаться' }));
    await screen.findByRole('heading', { name: 'Почему отказываетесь?' });
    expect(screen.getByRole('button', { name: 'Слишком дорого' })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: 'Нужен другой состав работ' }));
    await user.type(screen.getByLabelText('Комментарий'), 'Без замены реле');
    await user.click(screen.getByRole('button', { name: 'Отказаться' }));

    await screen.findByText('Выезд согласован');
    await waitFor(() =>
      expect(bodies).toEqual([
        expect.objectContaining({
          quote_id: quotes[0]!.id,
          quote_version: 1,
          comment: 'Нужен другой состав работ. Без замены реле',
        }),
      ]),
    );

    window.location.hash = `#/requests/${requestId}/repair-quotes/${quotes[0]!.id}`;
    await screen.findByRole('heading', { name: 'Отказ' });
    expect(screen.queryByRole('button', { name: /Отменить|Согласовать/ })).not.toBeInTheDocument();
    expect(screen.getByText(/исполнитель пришлёт новую версию/)).toBeInTheDocument();
    server.events.removeListener('request:start', onStart);
  });

  it('гарантийный ремонт — 0 ₽ «Доплата за ремонт» с основанием', async () => {
    const { requestId, quotes } = await scheduledWithQuote([0]);
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/repair-quotes/${quotes[0]!.id}`;

    await screen.findByText('Доплата за ремонт');
    expect(screen.getByText('Гарантия сервиса')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Согласовать ремонт' })).toBeInTheDocument();
  });

  it('ссылка на заменённую смету: «Эти условия уже заменены», затем актуальная версия', async () => {
    const { requestId, quotes } = await scheduledWithQuote([500000, 620000]);
    const first = quotes.find((q) => q.version === 1)!;

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/repair-quotes/${first.id}`;

    await screen.findByRole('heading', { name: 'Эти условия уже заменены' });
    expect(screen.queryByRole('button', { name: /Согласовать/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Посмотреть новые условия' }));

    await screen.findByText(/после диагностики · версия 2/);
    expect(screen.getByRole('button', { name: /Согласовать 6.200 ₽/ })).toBeInTheDocument();
  });
});
