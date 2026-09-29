import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen, expectActiveContext } from './testUtils';

describe('видимость действий по роли', () => {
  it('сотрудник заказчика не видит управление организацией и создание точек', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');

    await findHomeScreen();
    await expectActiveContext(null, 'Сотрудник заказчика');

    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    expect(screen.getByText('Сотрудник заказчика')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Сотрудники/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Точки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Изменить профиль' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Техника' }));
    await screen.findByRole('heading', { name: 'Техника' });
    await screen.findByRole('button', { name: /Bosch KGN39VL316/ });
    expect(screen.queryByRole('link', { name: 'Добавить технику' })).not.toBeInTheDocument();
  });

  it('руководитель заказчика видит управление организацией и точками', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');

    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    expect(await screen.findByRole('link', { name: /^Точки/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Сотрудники/ })).toBeInTheDocument();
  });

  it('диспетчер исполнителя не видит раздел «Интеграция» и не может править профиль', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_dispatcher');

    await screen.findByRole('link', { name: 'Профиль' });
    expect(screen.queryByRole('link', { name: 'Интеграция' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Организация' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.queryByRole('button', { name: 'Заполнить профиль' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Сотрудники/ })).not.toBeInTheDocument();
  });

  it('администратор исполнителя видит профиль, интеграцию и сотрудников, но не точки', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.getByRole('button', { name: 'Заполнить профиль' })).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: /^Сотрудники/ }));
    await screen.findByRole('heading', { name: 'Организация' });
    expect(await screen.findByRole('link', { name: /^Сотрудники/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Точки/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Интеграция' }));
    await screen.findByRole('heading', { name: 'Интеграция' });
  });
});
