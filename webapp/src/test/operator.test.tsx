import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

describe('оператор платформы', () => {
  it('раздел не виден обычному пользователю', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    expect(screen.queryByRole('link', { name: 'Оператор' })).not.toBeInTheDocument();

    window.location.hash = '/operator';
    await screen.findByText('Открыт только пользователям с платформенной ролью оператора.');
  });

  it('решение без основания невозможно; после решения дело уходит из очереди', async () => {
    const providerAuth = await demoLoginRaw('provider_admin');
    await apiCall('/provider-profile', providerAuth, {
      method: 'PATCH',
      body: {
        inn: '7707083893',
        contact_name: 'Иван Механик',
        category_ids: ['cat_fridge'],
        service_areas: [{ city_id: 'city_msk', district_ids: [] }],
      },
    });
    await apiCall('/provider-profile/submit', providerAuth, { body: {} });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('operator');

    await user.click(await screen.findByRole('link', { name: 'Организация' }));
    await user.click(await screen.findByRole('link', { name: 'Оператор' }));
    await screen.findByRole('heading', { name: 'Очереди оператора' });
    await user.click(screen.getByText('Проверка профилей и представителей'));

    await screen.findByRole('heading', { name: 'Проверка профилей и представителей' });
    const caseRows = await screen.findAllByText('Сервис-Холод');
    expect(caseRows).toHaveLength(2);
    await user.click(caseRows[0]!);

    await screen.findByText('Отправить решение');
    const submitButton = screen.getByRole('button', { name: 'Отправить решение' });
    expect(submitButton).toBeDisabled();

    await user.type(screen.getByLabelText('Основание решения (обязательно)'), 'Позвонили по телефону из ЕГРЮЛ');
    expect(submitButton).toBeDisabled();

    await user.type(screen.getByLabelText('Источник проверки (обязательно)'), 'Обратный звонок, ЕГРЮЛ');
    expect(submitButton).not.toBeDisabled();

    await user.click(submitButton);
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(screen.getAllByText('Сервис-Холод')).toHaveLength(1));
  });
});
