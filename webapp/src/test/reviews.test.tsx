import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { addAttachment } from '../mocks/requestsDb';
import { server } from '../mocks/server';
import type { RequestCustomer } from '../api/types';

async function createOwnServiceDraft() {
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

async function scheduleVisit(requestId: string, managerAuth: { token: string; organizationId: string }, providerAuth: { token: string; organizationId: string }, assignmentId: string) {
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
}

async function completeRequest(requestId: string, managerAuth: { token: string; organizationId: string }, providerAuth: { token: string; organizationId: string }, assignmentId: string) {
  await apiCall(`/requests/${requestId}/actions/start-work`, providerAuth, {
    method: 'POST',
    body: { assignment_id: assignmentId },
  });
  await apiCall(`/requests/${requestId}/actions/report-completion`, providerAuth, {
    method: 'POST',
    body: { assignment_id: assignmentId, outcome: 'resolved', summary: 'Заменили компрессор' },
  });
  const current = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
  await apiCall(`/requests/${requestId}/actions/confirm-completion`, managerAuth, {
    method: 'POST',
    body: { expected_version: current.version },
  });
}

describe('отзыв о ремонте', () => {
  it('отмена до начала работ — отзыв недоступен, показана причина и путь жалобы на неявку', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);

    const current = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
    await apiCall(`/requests/${requestId}/actions/request-cancellation`, managerAuth, {
      method: 'POST',
      body: { target: 'cancel_request', reason: 'Оборудование заменили', expected_version: current.version },
    });
    const withCancellation = await apiCall<RequestCustomer>(`/requests/${requestId}`, managerAuth);
    await apiCall(`/requests/${requestId}/actions/respond-cancellation`, providerAuth, {
      method: 'POST',
      body: { assignment_id: assignmentId, cancellation_id: withCancellation.cancellation!.id, decision: 'accept' },
    });

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await screen.findByText('Отзыв о ремонте');
    await screen.findByText(
      'Заявка отменена до начала работ — звёзд за ремонт здесь не бывает. Если дело в неявке или недобросовестном отказе исполнителя — подайте жалобу на взаимодействие.',
    );
    expect(screen.getByRole('button', { name: 'Жалоба на неявку' })).toBeInTheDocument();
  });

  it('создание отзыва → «на модерации» → редактирование без создания второй оценки', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}`;

    await user.click(await screen.findByRole('button', { name: 'Оценить мастера' }, { timeout: 5000 }));
    await screen.findByRole('heading', { name: 'Как прошёл ремонт?' });
    expect(screen.getByRole('switch', { name: 'Показывать название компании' })).not.toBeChecked();

    await user.click(screen.getByRole('radio', { name: '5 из 5' }));
    await user.type(screen.getByLabelText('Отзыв'), 'Отличная работа, всё в срок');
    await user.click(screen.getByRole('button', { name: 'Отправить отзыв' }));

    await screen.findByText('Отзыв на модерации');

    await user.click(screen.getByRole('button', { name: 'Изменить отзыв' }));
    await screen.findByText('Правка снова пройдёт модерацию. Пока решение не принято, виден прежний опубликованный текст. Новая оценка не создаётся — оценка входит в общий рейтинг только после публикации версии.');
    const textField = screen.getByLabelText('Отзыв') as HTMLTextAreaElement;
    expect(textField.value).toBe('Отличная работа, всё в срок');
    await user.clear(textField);
    await user.type(textField, 'Уточнение: приехали даже раньше срока');
    await user.click(screen.getByRole('button', { name: 'Сохранить правку' }));

    await waitFor(() => expect(screen.getAllByText('Отзыв на модерации')).toHaveLength(1));
  });

  it('фото для отзыва выбираются отдельно от фото заявки — по умолчанию ничего не выбрано', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);

    addAttachment({
      ownerKind: 'request',
      requestId,
      messageId: null,
      slot: 'device_photo',
      visibilityClass: 'request_private',
      mimeType: 'image/jpeg',
      blob: new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' }),
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/review`;

    const photoButtons = await screen.findAllByRole('button', { name: /^Фотография \d/ });
    expect(photoButtons.length).toBeGreaterThan(0);
    photoButtons.forEach((btn) => expect(btn).toHaveAttribute('aria-pressed', 'false'));

    await user.click(photoButtons[0]!);
    expect(photoButtons[0]).toHaveAttribute('aria-pressed', 'true');
  });

  it('провайдер отвечает на отзыв только один раз', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);

    const review = await apiCall<{ id: string }>(`/requests/${requestId}/review`, managerAuth, {
      method: 'PUT',
      body: { rating: 4, text: 'Хорошо, но дорого', show_customer_name: false, photo_attachment_ids: [] },
    });
    await apiCall(`/reviews/${review.id}/reply`, providerAuth, { method: 'POST', body: { body: 'Спасибо за обратную связь!' } });

    await expect(
      apiCall(`/reviews/${review.id}/reply`, providerAuth, { method: 'POST', body: { body: 'Ещё раз спасибо' } }),
    ).rejects.toThrow();
  });

  it('фото шильдика публикуется только с явным подтверждением; отзыв привязан к назначению', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);
    const nameplate = addAttachment({
      ownerKind: 'request',
      requestId,
      messageId: null,
      slot: 'nameplate',
      visibilityClass: 'request_sensitive',
      mimeType: 'image/jpeg',
      blob: new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' }),
    });

    const sent: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PUT' && new URL(request.url).pathname.endsWith('/review')) {
        void request
          .clone()
          .json()
          .then((body: unknown) => sent.push(body));
      }
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/review`;

    await user.click(await screen.findByRole('radio', { name: '5 из 5' }));
    await user.click((await screen.findAllByRole('button', { name: /^Фотография \d/ }))[0]!);
    const confirm = screen.getByRole('checkbox', { name: 'На фото может быть серийный номер — опубликовать?' });
    expect(confirm).not.toBeChecked();
    await user.click(confirm);
    expect(confirm).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Отправить отзыв' }));

    await screen.findByText('Отзыв на модерации');
    expect(sent).toEqual([
      expect.objectContaining({
        rating: 5,
        assignment_id: assignmentId,
        photo_attachment_ids: [nameplate.id],
        confirm_sensitive: true,
      }),
    ]);

    const state = await apiCall<{ review: { assignment_id: string } }>(`/requests/${requestId}/review`, managerAuth);
    expect(state.review.assignment_id).toBe(assignmentId);
    server.events.removeAllListeners();
  });

  it('сервер (мок) отклоняет фото шильдика без confirm_sensitive — 422 SENSITIVE_PHOTO_NOT_CONFIRMED', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);
    const nameplate = addAttachment({
      ownerKind: 'request',
      requestId,
      messageId: null,
      slot: 'nameplate',
      visibilityClass: 'request_sensitive',
      mimeType: 'image/jpeg',
      blob: new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' }),
    });

    await expect(
      apiCall(`/requests/${requestId}/review`, managerAuth, {
        method: 'PUT',
        body: { rating: 5, show_customer_name: false, photo_attachment_ids: [nameplate.id] },
      }),
    ).rejects.toThrow(/422.*SENSITIVE_PHOTO_NOT_CONFIRMED/);
  });

  it('REVIEW_ALREADY_EXISTS: отзыв уже сохранён в другом окне — экран показывает его вместо ошибки', async () => {
    const { managerAuth, requestId } = await createOwnServiceDraft();
    const { providerAuth, assignmentId } = await submitAndAccept(requestId, managerAuth);
    await scheduleVisit(requestId, managerAuth, providerAuth, assignmentId);
    await completeRequest(requestId, managerAuth, providerAuth, assignmentId);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${requestId}/review`;
    await screen.findByRole('button', { name: 'Отправить отзыв' });

    await apiCall(`/requests/${requestId}/review`, managerAuth, {
      method: 'PUT',
      body: { rating: 4, text: 'Из другого окна', show_customer_name: false, assignment_id: assignmentId },
    });
    server.use(
      http.put(
        '*/requests/:id/review',
        () =>
          HttpResponse.json(
            { error: { code: 'REVIEW_ALREADY_EXISTS', message: 'Отзыв по этому назначению уже создан', request_id: 'r' } },
            { status: 409 },
          ),
        { once: true },
      ),
    );

    await user.click(screen.getByRole('radio', { name: '5 из 5' }));
    await user.click(screen.getByRole('button', { name: 'Отправить отзыв' }));

    await screen.findByText('Из другого окна');
    expect(screen.getByText('Отзыв на модерации')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отправить отзыв' })).not.toBeInTheDocument();
  });
});

describe('мои жалобы', () => {
  it('жалобу до решения оператора можно отозвать — статус «Отозвана»', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const providerAuth = await demoLoginRaw('provider_active_admin');
    await apiCall('/complaints', managerAuth, {
      body: {
        subject_type: 'provider_profile',
        target_id: providerAuth.organizationId,
        description: 'Фото в профиле не их работ',
      },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = '/complaints';

    const withdraw = await screen.findAllByRole('button', { name: /Отозвать жалобу/ });
    await user.click(withdraw[0]!);
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Отозвать' }));

    await screen.findByText('Отозвана');
  });
});
