import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

type StaffPage = { items: { id: string; status: string; user: { display_name: string } }[] };

async function openCustomerStaff(user: ReturnType<typeof userEvent.setup>) {
  await findHomeScreen();
  await user.click(screen.getByRole('link', { name: 'Организация' }));
  await screen.findByRole('heading', { name: 'Организация' });
  await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
  await screen.findByRole('heading', { level: 1, name: 'Сотрудники' });
}

describe('исключение сотрудника и отклонение заявки на вступление', () => {
  it('руководитель заказчика исключает сотрудника после подтверждения', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openCustomerStaff(user);

    await user.click(await screen.findByRole('button', { name: /Анна Смирнова/ }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Исключить' }),
    );

    const confirm = within(
      await screen.findByRole('alertdialog', { name: 'Исключить: Анна Смирнова?' }),
    );
    await user.click(confirm.getByRole('button', { name: 'Исключить' }));

    await waitFor(() => expect(screen.queryByText('Анна Смирнова')).not.toBeInTheDocument());
    expect(screen.getByText('Иван Петров')).toBeInTheDocument();
  });

  it('отмена на шаге подтверждения ничего не меняет', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openCustomerStaff(user);

    await user.click(await screen.findByRole('button', { name: /Анна Смирнова/ }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Исключить' }),
    );
    const confirm = within(await screen.findByRole('alertdialog'));
    await user.click(confirm.getByRole('button', { name: 'Отмена' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(screen.getByText('Анна Смирнова')).toBeInTheDocument();
  });

  it('свою строку руководитель не может открыть для исключения', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openCustomerStaff(user);

    await screen.findByText('Иван Петров');
    expect(screen.queryByRole('button', { name: /Иван Петров/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Иван Петров/ })).not.toBeInTheDocument();
  });

  it('администратор исполнителя отклоняет ожидающего участника', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('button', { name: /Ольга Зимина/ }));
    const dialog = within(await screen.findByRole('alertdialog'));
    expect(dialog.getByRole('button', { name: 'Подтвердить' })).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Отклонить' }));

    await waitFor(() => expect(screen.queryByText('Ольга Зимина')).not.toBeInTheDocument());
  });

  it('сервер: отклонённого нельзя подтвердить, последнего руководителя — исключить', async () => {
    const admin = await demoLoginRaw('provider_admin');
    const staff = await apiCall<StaffPage>('/memberships', admin);
    const pending = staff.items.find((m) => m.status === 'pending')!;
    await apiCall(`/memberships/${pending.id}/revoke`, admin, { body: {} });
    await expect(
      apiCall(`/memberships/${pending.id}/approve`, admin, { body: {} }),
    ).rejects.toThrow(/-> 404/);

    const self = staff.items.find(
      (m) => m.status === 'active' && m.user.display_name !== pending.user.display_name,
    )!;
    await expect(apiCall(`/memberships/${self.id}/revoke`, admin, { body: {} })).rejects.toThrow(
      /LAST_MANAGER/,
    );
  });

  it('исключённых из ответа сервера (он отдаёт историю) в списке нет', async () => {
    const member = (id: string, name: string, status: string) => ({
      id,
      user: { id: `usr_${id}`, display_name: name },
      role: 'customer_employee',
      side: 'customer',
      status,
      location_ids: [],
    });
    server.use(
      http.get('*/memberships', () =>
        HttpResponse.json({
          items: [
            member('mem_x1', 'Анна Смирнова', 'active'),
            member('mem_x2', 'Пётр Уволенный', 'revoked'),
          ],
          next_cursor: null,
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openCustomerStaff(user);

    await screen.findByText('Анна Смирнова');
    expect(screen.queryByText('Пётр Уволенный')).not.toBeInTheDocument();
  });
});
