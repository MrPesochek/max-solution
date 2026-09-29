import { screen } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { expect } from 'vitest';

export async function startRequestForBosch(
  user: UserEvent,
  route: 'Мой сервис' | 'Найти исполнителя',
): Promise<void> {
  await user.click(await screen.findByRole('button', { name: 'Новая заявка' }));
  await screen.findByRole('heading', { name: 'Что сломалось?' });
  const bosch = await screen.findByRole('radio', { name: /Bosch/ });
  expect(bosch).toHaveTextContent('Кафе на Тверской');
  await user.click(bosch);

  const radio = await screen.findByRole('radio', {
    name: route === 'Мой сервис' ? /^Сервис-Холод Плюс/ : /^Найти исполнителя/,
  });
  await user.click(radio);
  expect(radio).toHaveAttribute('aria-checked', 'true');
  await user.click(screen.getByRole('button', { name: 'Далее' }));
  await screen.findByText('Шаг 2 из 3');
  await screen.findAllByRole('button', { name: /^Добавить фото: / });
}
