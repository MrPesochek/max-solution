import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import type { RequestCustomer } from '../api/types';

async function boschEquipmentId(auth: { token: string; organizationId: string }): Promise<string> {
  const locs = await apiCall<{ items: { id: string; name: string }[] }>('/locations', auth);
  const cafe = locs.items.find((l) => l.name.includes('Тверской'))!;
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${cafe.id}`,
    auth,
  );
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

describe('хаб «Заявки» исполнителя (11a)', () => {
  it('пауза закрывает только новые заявки: входящие остаются в списке', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: {
        equipment_id: equipmentId,
        route: 'own_service',
        urgency: 'critical',
        symptom_description: 'Не держит холод на паузе',
      },
    });
    await apiCall(`/requests/${draft.id}/actions/submit-to-own-service`, managerAuth, {
      body: { photos_incomplete: false, photos_incomplete_reason: null },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('heading', { name: 'Заявки' });
    await screen.findByText('Не держит холод на паузе');
    const toggle = await screen.findByRole('switch', { name: 'Принимаю новые заявки' });
    expect(toggle).toBeChecked();
    await user.click(toggle);

    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Принимаю новые заявки' })).not.toBeChecked(),
    );
    await screen.findByText('Вы на паузе');
    expect(screen.getByText('Не держит холод на паузе')).toBeInTheDocument();

    await user.click(screen.getByRole('switch', { name: 'Принимаю новые заявки' }));
    await waitFor(() => expect(screen.queryByText('Вы на паузе')).not.toBeInTheDocument());
  });
});

describe('«Чаты» исполнителя', () => {
  it('порядок — по last_message_at из списка заявок, ленты грузятся только под превью', async () => {
    const managerAuth = await demoLoginRaw('customer_manager');
    const equipmentId = await boschEquipmentId(managerAuth);
    const providerAuth = await demoLoginRaw('provider_active_admin');
    const ids: string[] = [];
    for (const text of ['Первая переписка', 'Вторая переписка']) {
      const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
        body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
      });
      await apiCall(`/requests/${draft.id}/actions/submit-to-own-service`, managerAuth, {
        body: { photos_incomplete: false, photos_incomplete_reason: null },
      });
      const view = await apiCall<{ assignment: { id: string } }>(`/requests/${draft.id}`, providerAuth);
      await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
        body: { assignment_id: view.assignment.id },
      });
      await apiCall(`/requests/${draft.id}/messages`, managerAuth, { body: { body: text } });
      ids.push(draft.id);
    }
    const silent = await apiCall<RequestCustomer>('/requests', managerAuth, {
      body: { equipment_id: equipmentId, route: 'own_service', urgency: 'normal' },
    });
    await apiCall(`/requests/${silent.id}/actions/submit-to-own-service`, managerAuth, {
      body: { photos_incomplete: false, photos_incomplete_reason: null },
    });

    const feeds: string[] = [];
    const onRequest = ({ request }: { request: Request }) => {
      const match = /\/requests\/([^/]+)\/messages$/.exec(new URL(request.url).pathname);
      if (match && request.method === 'GET') feeds.push(match[1]!);
    };
    server.events.on('request:start', onRequest);
    try {
      const user = userEvent.setup();
      renderApp();
      await loginAsDemo('provider_active_admin');
      await user.click(await screen.findByRole('link', { name: 'Чаты' }));

      await screen.findByRole('link', { name: /Вторая переписка/ });
      const order = screen
        .getAllByRole('link')
        .map((link) => link.getAttribute('href') ?? '')
        .filter((href) => href.endsWith('?panel=messages'));
      expect(order.indexOf(`#/provider/requests/${ids[1]}?panel=messages`)).toBeLessThan(
        order.indexOf(`#/provider/requests/${ids[0]}?panel=messages`),
      );
      expect(feeds).not.toContain(silent.id);
    } finally {
      server.events.removeListener('request:start', onRequest);
    }
  });

  it('показывают переписку по заявке в работе и открывают карточку на ней', async () => {
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
    await apiCall(`/requests/${draft.id}/actions/accept`, providerAuth, {
      body: { assignment_id: view.assignment.id },
    });
    await apiCall(`/requests/${draft.id}/messages`, managerAuth, {
      body: { body: 'Подъезжайте со двора, код 4321' },
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await user.click(await screen.findByRole('link', { name: 'Чаты' }));

    await screen.findByRole('heading', { name: 'Чаты' });
    const chat = await screen.findByRole('link', { name: /Подъезжайте со двора, код 4321/ });
    expect(chat).toHaveAttribute('href', `#/provider/requests/${draft.id}?panel=messages`);
    expect(chat.querySelector('.ui-row__count')).toHaveTextContent(/^[1-9]\d*$/);
    await user.click(chat);

    const messages = await screen.findByRole('button', { name: /Переписка/ });
    expect(messages).toHaveAttribute('aria-expanded', 'true');
    expect(
      (await within(document.body).findAllByText('Подъезжайте со двора, код 4321')).length,
    ).toBeGreaterThan(0);
  });
});

describe('отзыв и жалоба исполнителя (15g)', () => {
  it('жалоба с причиной уходит оператору, отзыв остаётся виден; до решения её можно отозвать', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/provider/reviews';

    await screen.findByText(/заявка Р-\d+/);
    const open = await screen.findAllByRole('button', { name: 'Пожаловаться на отзыв' });
    await user.click(open[0]!);
    const send = screen.getByRole('button', { name: 'Отправить' });
    expect(send).toBeDisabled();
    const reasons = screen.getByRole('radiogroup', { name: 'Причина жалобы' });
    await user.click(within(reasons).getByRole('radio', { name: 'Отзыв не о нашей работе' }));
    expect(within(reasons).getByRole('radio', { name: 'Отзыв не о нашей работе' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await user.click(send);

    await screen.findByText('Жалоба на проверке');
    expect(screen.getByText('Проверяет оператор')).toBeInTheDocument();
    expect(screen.getByText(/Приехали в тот же день/)).toBeInTheDocument();

    const providerAuth = await demoLoginRaw('provider_active_admin');
    const mine = await apiCall<{ items: { reason_code?: string | null; review_id?: string | null }[] }>(
      '/complaints',
      providerAuth,
    );
    expect(mine.items.find((c) => c.review_id)?.reason_code).toBe('not_our_work');

    await user.click(screen.getByRole('button', { name: 'Отозвать жалобу' }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Отозвать' }));

    await screen.findByText('Жалоба отозвана. При необходимости можно подать новую.');
    expect(screen.queryByText('Жалоба на проверке')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Пожаловаться на отзыв' }).length).toBeGreaterThan(0);

    window.location.hash = '/complaints';
    await screen.findByText('Отозвана');
  });
});
