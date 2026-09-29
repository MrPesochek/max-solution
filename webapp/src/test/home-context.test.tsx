import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import * as db from '../mocks/db';
import type { Offer, RequestCustomer } from '../api/types';
import { expectActiveContext, findHomeScreen, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

function homeHeader(): HTMLElement {
  return document.querySelector<HTMLElement>('.home-top')!;
}

async function marketplaceWithOffer(): Promise<string> {
  const manager = await demoLoginRaw('customer_manager');
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>('/equipment', manager);
  const market = await apiCall<RequestCustomer>('/requests', manager, {
    body: { equipment_id: eq.items.find((e) => e.brand === 'Bosch')!.id, route: 'marketplace', urgency: 'normal' },
  });
  await apiCall(`/requests/${market.id}/actions/publish-search`, manager, {
    body: { attachment_ids: [], confirm_sensitive: false },
  });
  const provider = await demoLoginRaw('provider_active_admin');
  await apiCall<Offer>(`/marketplace/requests/${market.id}/offers`, provider, {
    body: { amount_minor: 200000, currency: 'RUB', valid_until: '2027-01-01T00:00:00Z' },
  });
  return market.id;
}

describe('главная: активная организация в шапке', () => {
  it('название организации видно без открытия меню, меню показывает тот же контекст', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    const name = db.demoSeed.demoCustomer.name;
    expect(within(homeHeader()).getByText(name)).toBeInTheDocument();
    await expectActiveContext(name, 'Руководитель заказчика');
  });

  it('при нескольких членствах в шапке — организация выбранного контекста', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('dual_manager');
    await screen.findByRole('heading', { name: 'Где работаем сегодня?' });
    await user.click(screen.getByRole('radio', { name: /Два берега.*Заказчик · руководитель/ }));
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    await findHomeScreen();
    expect(within(homeHeader()).getByText(/Два берега/)).toBeInTheDocument();
  });
});

describe('главная: «Нужно ваше решение» над вкладками', () => {
  it('решение по внешнему поиску не внутри «Мой сервис» и видно на обеих вкладках', async () => {
    const marketId = await marketplaceWithOffer();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    const heading = await screen.findByRole('heading', { name: 'Нужно ваше решение' });
    const section = heading.closest('section')!;
    const offers = await within(section).findByRole('link', { name: /Выберите исполнителя/ });
    expect(offers.getAttribute('href')).toContain(`/requests/${marketId}/offers`);
    expect(screen.getByRole('tabpanel')).not.toContainElement(section);
    const tablist = screen.getByRole('tablist');
    expect(section.compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(within(tablist).getByRole('tab', { name: 'Найти исполнителя' }));
    expect(screen.getByRole('heading', { name: 'Нужно ваше решение' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Выберите исполнителя/ })).toBeInTheDocument();
  });

  it('сотруднику решений руководителя нет ни на одной вкладке', async () => {
    await marketplaceWithOffer();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    await screen.findByRole('tabpanel');
    expect(screen.queryByRole('heading', { name: 'Нужно ваше решение' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Найти исполнителя' }));
    expect(screen.queryByRole('heading', { name: 'Нужно ваше решение' })).not.toBeInTheDocument();
  });
});
