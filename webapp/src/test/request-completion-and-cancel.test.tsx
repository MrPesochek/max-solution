import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { queryClient } from '../api/queryClient';
import { expireCancellationDeadline } from '../mocks/requestsDb';
import type { Offer, RequestCustomer } from '../api/types';

async function createOwnServiceDraft(urgency = 'normal') {
  const managerAuth = await demoLoginRaw('customer_manager');
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', managerAuth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    managerAuth,
  );
  const bosch = eq.items.find((e) => e.brand === 'Bosch')!;
  const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
    method: 'POST',
    body: { equipment_id: bosch.id, route: 'own_service', urgency },
  });
  return { managerAuth, requestId: draft.id };
}

async function submitAndAccept(requestId: string, managerAuth: { token: string; organizationId: string }) {
  const submitted = await apiCall<RequestCustomer>(`/requests/${requestId}/actions/submit-to-own-service`, managerAuth, {
    method: 'POST',
    body: { photos_incomplete: true, photos_incomplete_reason: 'не требуется для теста' },
  });
  const assignmentId = (submitted as unknown as { assignment: { id: string } }).assignment.id;
  const providerAuth = await demoLoginRaw('provider_active_admin');
  await apiCall(`/requests/${requestId}/actions/accept`, providerAuth, {
    method: 'POST',
    body: { assignment_id: assignmentId },
  });
  return { providerAuth, assignmentId };
}

describe('подтверждение результата', () => {
  it('руководитель подтверждает результат — заявка закрывается', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);

    await apiCall(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId, amount_minor: 100000, currency: 'RUB', valid_until: '2026-12-31T00:00:00Z' },
    });
    const withVisit = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
    const proposalId = withVisit.visit_proposals[0]!.id;
    await apiCall(`/requests/${requestId}/actions/approve-visit-proposal`, managerAuth, {
      method: 'POST',
      body: { proposal_id: proposalId, proposal_version: 1 },
    });
    await apiCall(`/requests/${requestId}/actions/start-work`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId },
    });
    await apiCall(`/requests/${requestId}/actions/report-completion`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId, outcome: 'resolved', summary: 'Заменили компрессор' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await waitFor(() => expect(screen.getByText('Мастер закончил ремонт')).toBeInTheDocument());
    expect(await screen.findByText('Заменили компрессор')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Принять работу' }));

    await waitFor(() => expect(screen.getByText('Работа принята')).toBeInTheDocument());
  });

  it('«проблема осталась» — заявка возвращается в работу тому же исполнителю', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await apiCall(`/requests/${requestId}/actions/propose-visit`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId, amount_minor: 100000, currency: 'RUB', valid_until: '2026-12-31T00:00:00Z' },
    });
    const withVisit = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
    await apiCall(`/requests/${requestId}/actions/approve-visit-proposal`, managerAuth, {
      method: 'POST',
      body: { proposal_id: withVisit.visit_proposals[0]!.id, proposal_version: 1 },
    });
    await apiCall(`/requests/${requestId}/actions/start-work`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId },
    });
    await apiCall(`/requests/${requestId}/actions/report-completion`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId, outcome: 'resolved', summary: 'Готово' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await waitFor(() => expect(screen.getByText('Мастер закончил ремонт')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Есть проблема' }));
    await screen.findByRole('heading', { name: 'Что не так?' });
    expect(screen.getByText(/заявка вернётся ему в работу/)).toBeInTheDocument();
    expect(screen.queryByText(/оператор/)).not.toBeInTheDocument();
    const send = screen.getByRole('button', { name: 'Отправить' });
    expect(send).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Шумит' }));
    await user.type(screen.getByLabelText('Описание'), 'Холодильник всё ещё не морозит');
    await user.click(send);

    await screen.findByRole('heading', { name: 'Отправили мастеру' });
    await user.click(screen.getByRole('button', { name: 'Готово' }));
    await waitFor(() => expect(screen.getByText('Мастер работает')).toBeInTheDocument());
  });
});

describe('отмена заявки до и после принятия', () => {
  it('до принятия — отмена сразу, без запроса', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    await apiCall(`/requests/${requestId}/actions/submit-to-own-service`, managerAuth, {
      method: 'POST',
      body: { photos_incomplete: true, photos_incomplete_reason: 'тест' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await screen.findByText('Ждём ответа сервиса');
    await user.click(await screen.findByRole('button', { name: 'Отменить заявку' }));

    await screen.findByRole('heading', { name: 'Что вы хотите сделать?' });
    expect(screen.getByText(/Исполнитель ещё не принял заявку/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /Отменить заявку/ })).toHaveAttribute('aria-checked', 'true');
    await user.type(screen.getByPlaceholderText('Причина отмены'), 'Проблема решилась сама');
    await user.click(screen.getByRole('button', { name: 'Отменить сейчас' }));

    await waitFor(() => expect(screen.getByText('Заявка отменена')).toBeInTheDocument());
  });

  it('после принятия — запрос отмены, ответ исполнителя виден, спор решается по истечении срока', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    expect(await screen.findAllByText('Принято исполнителем')).not.toHaveLength(0);
    await user.click(await screen.findByRole('button', { name: 'Отменить заявку' }));

    await screen.findByRole('heading', { name: 'Что вы хотите сделать?' });
    expect(screen.getByText(/Исполнитель уже принял заявку/)).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('Причина отмены'), 'Нашли другого мастера');
    await user.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    await waitFor(() => expect(screen.getByText('Отмена на согласовании')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Не отменять' })).toBeInTheDocument();
    expect(screen.getByText('Нашли другого мастера')).toBeInTheDocument();

    const cancellation = (await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth)).cancellation!;
    await apiCall(`/requests/${requestId}/actions/respond-cancellation`, providerAuth, {
      method: 'POST',
      body: {
        assignment_id: assignmentId,
        cancellation_id: cancellation.id,
        decision: 'decline',
        comment: 'Уже выехали к клиенту',
      },
    });

    await queryClient.invalidateQueries({ queryKey: ['requests'] });
    await screen.findByRole('region', { name: 'Исполнитель не согласен с отменой' });
    expect(screen.getByText(/Уже выехали к клиенту/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Прекратить в одностороннем порядке' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Отменить заявку' })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Не отменять' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Не отменять' }));
    const confirmDialog = await screen.findByRole('alertdialog', {}, { timeout: 4000 });
    await user.click(within(confirmDialog).getByRole('button', { name: 'Да' }));
    await waitFor(() =>
      expect(screen.queryByRole('region', { name: 'Исполнитель не согласен с отменой' })).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole('button', { name: 'Отменить заявку' })).toBeInTheDocument();
  }, 15000);

  it('исполнитель не ответил в срок — руководитель прекращает работы без спора', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    await submitAndAccept(requestId, managerAuth);
    await apiCall(`/requests/${requestId}/actions/request-cancellation`, managerAuth, {
      method: 'POST',
      body: { target: 'cancel_request', reason: 'Передумали' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await screen.findByText('Отмена на согласовании');
    expect(screen.getByRole('button', { name: 'Ждём ответа' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Прекратить в одностороннем порядке' })).not.toBeInTheDocument();

    expireCancellationDeadline(requestId);
    await queryClient.invalidateQueries({ queryKey: ['requests'] });

    const force = await screen.findByRole('button', { name: 'Прекратить в одностороннем порядке' });
    expect(screen.queryByRole('button', { name: 'Ждём ответа' })).not.toBeInTheDocument();
    await waitFor(() => expect(force).toBeEnabled());
    await user.click(force);
    const confirmDialog = await screen.findByRole('alertdialog', {}, { timeout: 4000 });
    expect(within(confirmDialog).getByText(/не ответил в срок/)).toBeInTheDocument();
    await user.click(within(confirmDialog).getByRole('button', { name: 'Прекратить в одностороннем порядке' }));

    await waitFor(async () => {
      const after = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
      expect(after.status).toBe('cancelled');
    });
  }, 15000);

  it('после отозванного запроса отмены заявку снова можно отменить из карточки', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    await submitAndAccept(requestId, managerAuth);
    const pending = await apiCall<RequestCustomer>(`/requests/${requestId}/actions/request-cancellation`, managerAuth, {
      method: 'POST',
      body: { target: 'cancel_request', reason: 'Передумали' },
    });
    await apiCall(`/requests/${requestId}/actions/withdraw-cancellation`, managerAuth, {
      method: 'POST',
      body: { cancellation_id: pending.cancellation!.id },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    expect(await screen.findAllByText('Принято исполнителем')).not.toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Не отменять' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Отменить заявку' }));
    await screen.findByRole('heading', { name: 'Что вы хотите сделать?' });
  });

  it('до подтверждения выбранным исполнителем заявку можно отменить целиком', async () => {
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
    await apiCall(`/requests/${draft.id}/actions/publish-search`, managerAuth, {
      method: 'POST',
      body: { attachment_ids: [], confirm_sensitive: false },
    });
    const providerAuth = await demoLoginRaw('provider_active_admin');
    const offer = await apiCall<Offer>(`/marketplace/requests/${draft.id}/offers`, providerAuth, {
      body: {
        visit_window_start: '2026-10-01T09:00:00Z',
        visit_window_end: '2026-10-01T12:00:00Z',
        amount_minor: 250000,
        currency: 'RUB',
        vat_mode: 'included',
        scope_description: 'Диагностика',
        valid_until: '2026-12-31T00:00:00Z',
      },
    });
    const selected = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/select-offer`, managerAuth, {
      method: 'POST',
      body: { offer_id: offer.id, offer_version: offer.version },
    });
    expect(selected.status).toBe('awaiting_assignment_confirmation');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${draft.id}`;

    expect(await screen.findByRole('button', { name: 'Отменить выбор' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отменить заявку' }));
    await screen.findByRole('heading', { name: 'Что вы хотите сделать?' });
    expect(screen.getByText(/Исполнитель ещё не принял заявку/)).toBeInTheDocument();
  });
});
