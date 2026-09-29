import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { loginAsDemo, renderApp } from './testUtils';
import { startRequestForBosch } from './requestWizardHelpers';

async function openDetailsStep() {
  const user = userEvent.setup();
  renderApp();
  await loginAsDemo('customer_manager');
  await startRequestForBosch(user, 'Мой сервис');
  return user;
}

describe('выход из мобильного мастера', () => {
  it('сохраняет текст текущего шага при возврате в список', async () => {
    const user = await openDetailsStep();
    await user.type(
      screen.getByLabelText('Подробнее'),
      'Не охлаждает после включения',
    );
    await user.click(screen.getByRole('link', { name: 'Назад' }));
    await screen.findByRole('heading', { name: 'Заявки' });
    await user.click(await screen.findByRole('link', { name: /Bosch/ }));
    await screen.findByText('Заявка ещё не отправлена');
    expect(screen.getByText('Описание').closest('.ui-row')).not.toHaveTextContent('не заполнено');
    expect(screen.getByText('Фото').closest('.ui-row')).toHaveTextContent('не добавлены');
    await user.click(screen.getByRole('button', { name: 'Продолжить заполнение' }));
    await screen.findByText('Шаг 2 из 3');
    expect(await screen.findByLabelText('Подробнее')).toHaveValue('Не охлаждает после включения');
  });

  it('оставляет пользователя на шаге с введённым текстом, если сохранение не удалось', async () => {
    const user = await openDetailsStep();
    await user.type(screen.getByLabelText('Подробнее'), 'Текст не должен потеряться');
    server.use(
      http.patch('*/requests/:id', () =>
        HttpResponse.json(
          { error: { code: 'UNAVAILABLE', message: 'Не удалось сохранить' } },
          { status: 503 },
        ),
      ),
    );
    await user.click(screen.getByRole('link', { name: 'Назад' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Подробнее')).toHaveValue(
      'Текст не должен потеряться',
    );
    expect(screen.getByText('Шаг 2 из 3')).toBeInTheDocument();
  });
});
