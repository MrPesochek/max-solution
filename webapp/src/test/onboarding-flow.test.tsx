import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen, expectActiveContext } from './testUtils';

describe('сценарий: онбординг → создать точку → добавить оборудование', () => {
  it('проводит нового пользователя от регистрации организации до добавленного оборудования', async () => {
    const user = userEvent.setup();
    renderApp();

    await loginAsDemo('new_user');

    await screen.findByRole('heading', { name: 'Ремонт техники без звонков' });
    expect(screen.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: /Заказчик/ }));
    await user.click(screen.getByRole('button', { name: 'Продолжить' }));

    await screen.findByRole('heading', { name: 'Ваша организация' });
    await user.type(await screen.findByLabelText('Название'), 'ООО Тест');
    await user.type(screen.getByLabelText('Телефон для обращений'), '+7 999 123-45-67');
    await user.type(screen.getByLabelText('Название точки'), 'Тестовая точка');
    expect(screen.queryByLabelText('Район')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Город'), 'Москва');
    expect(screen.getByLabelText('Район')).not.toBeRequired();
    await user.type(screen.getByLabelText('Адрес'), 'ул. Test, 1');

    await user.click(screen.getByRole('button', { name: 'Создать организацию' }));

    await findHomeScreen();
    await expectActiveContext('ООО Тест', 'Руководитель заказчика');

    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('link', { name: /^Точки/ }));

    await screen.findByRole('heading', { name: 'Точки' });
    expect(await screen.findByText('Тестовая точка')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Добавить точку' }));
    await screen.findByRole('heading', { name: 'Новая точка' });
    await user.type(await screen.findByLabelText('Название'), 'Вторая точка');
    expect(screen.queryByLabelText('Район')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Город'), 'Москва');
    await user.selectOptions(screen.getByLabelText('Район'), 'Южный');
    await user.selectOptions(screen.getByLabelText('Город'), 'Санкт-Петербург');
    expect(screen.getByLabelText('Район')).toHaveValue('');
    expect(screen.queryByRole('option', { name: 'Южный' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Василеостровский' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Адрес'), 'ул. Second, 2');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));

    await screen.findByRole('heading', { name: 'Точки' });
    expect(await screen.findByText('Вторая точка')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Назад' }));
    await user.click(await screen.findByRole('link', { name: 'Техника' }));
    await screen.findByRole('heading', { name: 'Техники пока нет' });
    await user.click(screen.getByRole('button', { name: 'Добавить технику' }));

    await screen.findByRole('heading', { name: 'Новая техника' });
    await user.click(await screen.findByRole('radio', { name: 'Вторая точка' }));
    await user.click(screen.getByRole('radio', { name: 'Другой тип' }));
    await user.type(screen.getByLabelText('Бренд'), 'Bosch');
    await user.type(screen.getByLabelText('Модель'), 'KGN39VL316');
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled();
    await user.type(screen.getByLabelText('Какой тип'), 'Охладитель воды');
    await user.click(screen.getByRole('button', { name: 'Добавить' }));

    await screen.findByRole('heading', { name: 'Техника' });
    expect(await screen.findByText(/Bosch KGN39VL316/)).toBeInTheDocument();
  }, 20_000);
});
