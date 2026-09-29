import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import * as rdb from '../mocks/requestsDb';
import type { RequestCustomer } from '../api/types';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { startRequestForBosch } from './requestWizardHelpers';

async function equipmentOf(auth: { token: string; organizationId: string }, brand: string): Promise<string> {
  const locs = await apiCall<{ items: { id: string }[] }>('/locations', auth);
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${locs.items[0]!.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === brand)!.id;
}

const firstBoschId = (auth: { token: string; organizationId: string }) => equipmentOf(auth, 'Bosch');

function capturePatches(): { bodies: Record<string, unknown>[]; stop: () => void } {
  const bodies: Record<string, unknown>[] = [];
  const onStart = ({ request }: { request: Request }) => {
    if (request.method === 'PATCH' && /\/requests\/[^/]+$/.test(new URL(request.url).pathname)) {
      void request
        .clone()
        .json()
        .then((body: Record<string, unknown>) => bodies.push(body));
    }
  };
  server.events.on('request:start', onStart);
  return { bodies, stop: () => server.events.removeListener('request:start', onStart) };
}

describe('мастер заявки: «без фото» и проверка полей', () => {
  it('причина «без фото» внешней заявки сотрудника сохраняется в черновике до согласования', async () => {
    const patches = capturePatches();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    await startRequestForBosch(user, 'Найти исполнителя');

    await user.type(screen.getByLabelText('Подробнее'), 'Не держит холод с утра');
    await user.click(screen.getByRole('radio', { name: 'Сегодня' }));
    await user.click(screen.getByRole('button', { name: 'Не могу сделать фото' }));
    await screen.findByRole('heading', { name: 'Почему нет фото?' });
    await user.click(screen.getByRole('radio', { name: 'Камера не работает' }));
    await user.click(screen.getByRole('button', { name: 'Далее' }));

    await screen.findByText('Шаг 3 из 3');
    await waitFor(() =>
      expect(patches.bodies.some((b) => b.photos_incomplete === true)).toBe(true),
    );
    const saved = patches.bodies.find((b) => b.photos_incomplete === true)!;
    expect(saved.urgency).toBe('critical');
    expect(saved.symptom_description).toBe('Не держит холод с утра');
    expect(String(saved.photos_incomplete_reason)).toContain('Камера не работает');
    patches.stop();
  });

  it('без описания «Далее» не блокируется молча: поле подсвечено, шаг не меняется', async () => {
    const patches = capturePatches();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');

    const next = screen.getByRole('button', { name: 'Далее' });
    expect(next).toBeEnabled();
    await user.click(next);
    expect(
      await screen.findByText('Опишите, что случилось: выберите признак или напишите пару слов.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Шаг 2 из 3')).toBeInTheDocument();
    expect(patches.bodies).toHaveLength(0);

    await user.type(screen.getByLabelText('Подробнее'), 'Шумит');
    expect(
      screen.queryByText('Опишите, что случилось: выберите признак или напишите пару слов.'),
    ).not.toBeInTheDocument();
    patches.stop();
  });
});

describe('черновик, возвращённый руководителем', () => {
  it('сотрудник видит комментарий руководителя', async () => {
    const employee = await demoLoginRaw('customer_employee');
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', employee, {
      method: 'POST',
      body: {
        equipment_id: await firstBoschId(employee),
        route: 'marketplace',
        urgency: 'normal',
        symptom_description: 'Течёт',
      },
    });
    const sent = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/request-approval`, employee, {
      method: 'POST',
      body: {},
    });
    await apiCall(`/requests/${draft.id}/actions/return-to-draft`, manager, {
      method: 'POST',
      body: { comment: 'Добавьте фото шильдика', expected_version: sent.version },
    });

    renderApp();
    await loginAsDemo('customer_employee');
    window.location.hash = `#/requests/${draft.id}`;

    expect(await screen.findByText('Заявку вернули на доработку')).toBeInTheDocument();
    expect(screen.getByText(/«Добавьте фото шильдика»/)).toBeInTheDocument();
  });
});

describe('отмена заявки без активного назначения', () => {
  it('в action_required нет «Сменить исполнителя», вместо него — «Найти другого»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      method: 'POST',
      body: { equipment_id: await firstBoschId(manager), route: 'marketplace', urgency: 'normal' },
    });
    rdb.getRequestRaw(draft.id).status = 'action_required';

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${draft.id}/cancel`;

    expect(await screen.findByText('Отменить заявку')).toBeInTheDocument();
    expect(screen.queryByText('Сменить исполнителя')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Найти другого' })).toHaveAttribute(
      'href',
      `#/requests/${draft.id}/publish`,
    );
  });
});

describe('повторная публикация поиска', () => {
  it('фото прошлой публикации отмечены заранее, остальные — нет', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      method: 'POST',
      body: { equipment_id: await firstBoschId(manager), route: 'marketplace', urgency: 'normal' },
    });
    const photo = (slot: string) =>
      rdb.addAttachment({
        ownerKind: 'request',
        requestId: draft.id,
        messageId: null,
        slot,
        visibilityClass: 'request_private',
        mimeType: 'image/jpeg',
        blob: new Blob(['x'], { type: 'image/jpeg' }),
      });
    const published = photo('overview');
    photo('general');
    await apiCall(`/requests/${draft.id}/actions/publish-search`, manager, {
      method: 'POST',
      body: { published_description: 'Не держит холод', attachment_ids: [published.id], confirm_sensitive: false },
    });
    rdb.getRequestRaw(draft.id).status = 'action_required';

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${draft.id}/publish`;

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Всё равно искать' }));
    await screen.findByRole('heading', { name: 'Что увидят исполнители' });
    const switches = await screen.findAllByRole('switch');
    expect(switches).toHaveLength(2);
    expect(switches.filter((s) => s.getAttribute('aria-checked') === 'true')).toHaveLength(1);
  });
});

describe('карточка: действия по статусу', () => {
  async function acceptedOwnService(): Promise<RequestCustomer> {
    const manager = await demoLoginRaw('customer_manager');
    const draft = await apiCall<RequestCustomer>('/requests', manager, {
      method: 'POST',
      body: { equipment_id: await firstBoschId(manager), route: 'own_service', urgency: 'normal' },
    });
    const submitted = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
      method: 'POST',
      body: { photos_incomplete: true, photos_incomplete_reason: 'Без фото' },
    });
    const provider = await demoLoginRaw('provider_active_admin');
    await apiCall(`/requests/${draft.id}/actions/accept`, provider, {
      body: { assignment_id: submitted.assignment!.id },
    });
    return apiCall<RequestCustomer>(`/requests/${draft.id}`, manager);
  }

  it('смета в статусе accepted — главная кнопка «Согласовать ремонт»', async () => {
    const accepted = await acceptedOwnService();
    const raw = rdb.getRequestRaw(accepted.id);
    rdb.createRepairQuote(
      accepted.id,
      rdb.getAssignmentProviderOrgId(accepted.assignment!.id)!,
      accepted.assignment!.id,
      {
        description_of_work: 'Замена реле по итогам удалённой диагностики',
        amount_minor: 320000,
        currency: 'RUB',
        vat_mode: 'without_vat',
        zero_cost_reason: null,
        valid_until: null,
      },
      raw.version,
    );

    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${accepted.id}`;
    expect(await screen.findByRole('button', { name: 'Согласовать ремонт' }, { timeout: 5000 })).toBeInTheDocument();
  });

  it('без сметы в accepted — только переписка и отмена, без кнопки сметы', async () => {
    const accepted = await acceptedOwnService();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/requests/${accepted.id}`;
    expect(await screen.findByRole('button', { name: /^Написать/ }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Согласовать ремонт' })).not.toBeInTheDocument();
  });
});
