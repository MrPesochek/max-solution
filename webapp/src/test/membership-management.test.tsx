import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen, expectActiveContext } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

describe('сценарий: подтверждение участника и точки сотрудника', () => {
  it('администратор исполнителя подтверждает ожидающего сотрудника', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));

    await screen.findByRole('heading', { level: 1, name: 'Сотрудники' });
    await screen.findByText('Ольга Зимина');
    expect(screen.getByText('Ждёт подтверждения')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Ольга Зимина/ }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.click(dialog.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => {
      expect(screen.queryByText('Ждёт подтверждения')).not.toBeInTheDocument();
    });
  });

  it('подтверждённый сотрудник исполнителя сразу попадает в организацию', async () => {
    const admin = await demoLoginRaw('provider_admin');
    const staff = await apiCall<{ items: { id: string; status: string; user: { display_name: string } }[] }>(
      '/memberships',
      admin,
    );
    const pending = staff.items.find((m) => m.user.display_name === 'Ольга Зимина' && m.status === 'pending')!;
    await apiCall(`/memberships/${pending.id}/approve`, admin, { body: {} });
    renderApp();
    await loginAsDemo('provider_dispatcher_pending');

    await screen.findByRole('link', { name: 'Профиль' });
    await expectActiveContext(null, 'Диспетчер/мастер исполнителя');
  });

  it('руководитель заказчика меняет точки сотрудника', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');

    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));

    await screen.findByText('Анна Смирнова');
    expect(screen.queryByRole('button', { name: /Иван Петров/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Анна Смирнова/ }));
    await user.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Изменить точки' }),
    );

    await screen.findByRole('heading', { name: 'Анна Смирнова' });
    const secondLocation = screen.getByRole('checkbox', { name: /Магазин на Невском/ });
    expect(secondLocation).not.toBeChecked();

    await user.click(secondLocation);
    expect(secondLocation).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await screen.findByRole('heading', { level: 1, name: 'Сотрудники' });
    expect(await screen.findByText(/Кафе на Тверской, Магазин на Невском/)).toBeInTheDocument();
  });
});
