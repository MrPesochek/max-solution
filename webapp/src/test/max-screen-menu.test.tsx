import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import * as db from '../mocks/db';
import { findHomeScreen, renderApp } from './testUtils';
import { startRequestForBosch } from './requestWizardHelpers';

function openInMax() {
  window.WebApp = {
    initData: 'demo:customer_manager',
    BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
  };
}

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  const header = document.querySelector<HTMLElement>('.ui-header')!;
  expect(header).not.toHaveClass('ui-header--bare');
  await user.click(within(header).getByRole('button', { name: 'Меню' }));
  return within(await screen.findByRole('dialog'));
}

describe('меню действий ⋯ внутри MAX', () => {
  it('карточка техники: «Изменить данные» — в ⋯ шапки и открывает редактирование', async () => {
    openInMax();
    const user = userEvent.setup();
    const item = db.listEquipment(db.demoSeed.demoCustomer.id).items.find((e) => e.brand === 'Bosch')!;
    renderApp();
    await findHomeScreen();
    window.location.hash = `#/equipment/${item.location_id}/${item.id}`;
    await screen.findByRole('heading', { name: /Bosch KGN39VL316/ });

    expect(screen.queryByRole('button', { name: 'Изменить данные' })).not.toBeInTheDocument();
    const menu = await openMenu(user);
    await user.click(menu.getByRole('button', { name: 'Изменить данные' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
  });

  it('мастер заявки: «Отменить черновик» — в ⋯ шапки, с подтверждением', async () => {
    openInMax();
    const user = userEvent.setup();
    renderApp();
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');

    expect(screen.queryByRole('button', { name: 'Отменить черновик' })).not.toBeInTheDocument();
    const menu = await openMenu(user);
    await user.click(menu.getByRole('button', { name: 'Отменить черновик' }));
    expect(
      await screen.findByText('Отменить черновик заявки? Действие нельзя отменить.'),
    ).toBeInTheDocument();
  });
});
