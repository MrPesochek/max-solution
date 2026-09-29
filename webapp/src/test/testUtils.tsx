import { render, screen, waitFor, within, type RenderResult } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect } from 'vitest';
import { MaxUI } from '@maxhub/max-ui';
import { App } from '../App';

export function renderApp(): RenderResult {
  return render(
    <MaxUI resetBody>
      <App />
    </MaxUI>,
  );
}

export async function findHomeScreen(): Promise<HTMLElement> {
  return screen.findByRole('link', { name: 'Главная', current: 'page' });
}

export async function loginAsDemo(userKey: string): Promise<void> {
  const user = userEvent.setup();
  const input = await screen.findByLabelText('Идентификатор демо-пользователя');
  await user.clear(input);
  await user.type(input, userKey);
  await user.click(screen.getByRole('button', { name: 'Войти в демо-режиме' }));
  await waitFor(() => {
    expect(screen.queryByText('Выполняется вход…')).not.toBeInTheDocument();
  });
}

export async function expectActiveContext(organization: string | null, role: string): Promise<void> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Меню' }));
  const dialog = within(await screen.findByRole('dialog'));
  if (organization) expect(dialog.getByText(organization)).toBeInTheDocument();
  expect(dialog.getByText(role)).toBeInTheDocument();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
}

export async function findRowLink(route: string): Promise<HTMLAnchorElement> {
  return waitFor(() => {
    const link = document.querySelector<HTMLAnchorElement>(`a[href="#${route}"]`);
    expect(link).not.toBeNull();
    return link!;
  });
}
