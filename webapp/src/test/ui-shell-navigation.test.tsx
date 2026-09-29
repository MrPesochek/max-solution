import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MaxUI } from '@maxhub/max-ui';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '../api/queryClient';
import { Sheet } from '../ui/Sheet';
import { ListRow } from '../ui/List';
import { PhotoTile } from '../ui/PhotoGrid';
import { Screen } from '../ui/layout/Screen';
import { LayoutContext, type LayoutContextValue } from '../ui/layout/layoutContext';
import { dispatchBack, registerBack, resetBackStackForTests } from '../ui/layout/backStack';
import { getColorScheme } from '../max/bridge';
import { strings } from '../strings/ru';
import { findRowLink, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import type { RequestCustomer } from '../api/types';

function installMaxBridge(colorScheme?: 'light' | 'dark') {
  const handlers: Array<() => void> = [];
  const backButton = {
    show: vi.fn(),
    hide: vi.fn(),
    onClick: vi.fn((cb: () => void) => handlers.push(cb)),
    offClick: vi.fn(),
  };
  window.WebApp = { initData: 'query_id=1&hash=x', BackButton: backButton, colorScheme };
  return { backButton, press: () => handlers.forEach((cb) => cb()) };
}

const LAYOUT: LayoutContextValue = {
  inLayout: true,
  nested: false,
  parentPath: '/',
  leave: async (action) => action(),
  leaving: false,
  switchOrganization: () => {},
  registerScreen: () => () => {},
};

function renderInLayout(node: React.ReactNode, layout: Partial<LayoutContextValue> = {}) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MaxUI>
        <MemoryRouter>
          <LayoutContext.Provider value={{ ...LAYOUT, ...layout }}>{node}</LayoutContext.Provider>
        </MemoryRouter>
      </MaxUI>
    </QueryClientProvider>,
  );
}

beforeEach(() => resetBackStackForTests());
afterEach(() => resetBackStackForTests());

describe('системная «Назад» MAX: стек обработчиков', () => {
  it('сначала закрывает лист, потом уходит с экрана', () => {
    const screenBack = vi.fn();
    const sheetBack = vi.fn();
    const offScreen = registerBack('screen', screenBack);
    const offSheet = registerBack('overlay', sheetBack);
    dispatchBack();
    expect(sheetBack).toHaveBeenCalledTimes(1);
    expect(screenBack).not.toHaveBeenCalled();
    offSheet();
    dispatchBack();
    expect(screenBack).toHaveBeenCalledTimes(1);
    offScreen();
    expect(dispatchBack()).toBe(false);
  });

  it('открытый Sheet закрывается кнопкой MAX, а при locked нажатие поглощается', () => {
    const { backButton, press } = installMaxBridge();
    const onClose = vi.fn();
    const screenBack = vi.fn();
    registerBack('screen', screenBack);
    const { rerender } = render(
      <Sheet open title="Отказаться" onClose={onClose}>
        <input aria-label="Причина" />
      </Sheet>,
    );
    expect(backButton.show).toHaveBeenCalled();
    press();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screenBack).not.toHaveBeenCalled();

    rerender(
      <Sheet open locked title="Отказаться" onClose={onClose}>
        <input aria-label="Причина" />
      </Sheet>,
    );
    press();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screenBack).not.toHaveBeenCalled();

    rerender(<Sheet open={false} onClose={onClose} />);
    press();
    expect(screenBack).toHaveBeenCalledTimes(1);
  });
});

describe('шапка экрана в MAX', () => {
  it('на корне вкладки шапки нет, название приложения — не h1', () => {
    installMaxBridge();
    renderInLayout(<Screen title={strings.ui.appTitle}>тело</Screen>);
    expect(document.querySelector('.ui-header__bar')).toBeNull();
    expect(document.querySelector('.ui-header--bare')).not.toBeNull();
    expect(screen.queryByRole('heading', { name: strings.ui.appTitle })).toBeNull();
  });

  it('в браузере шапка есть, но название приложения — подпись, а не заголовок', () => {
    renderInLayout(<Screen title={strings.ui.appTitle}>тело</Screen>);
    expect(document.querySelector('.ui-header__bar')).not.toBeNull();
    expect(screen.getByText(strings.ui.appTitle).tagName).toBe('SPAN');
  });

  it('вложенный экран в MAX сохраняет заголовок и отдаёт «назад» системной кнопке', () => {
    const { backButton } = installMaxBridge();
    renderInLayout(<Screen title="Заявка Р-412">тело</Screen>, { nested: true });
    expect(screen.getByRole('heading', { level: 1, name: 'Заявка Р-412' })).toBeInTheDocument();
    expect(backButton.show).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: strings.ui.back })).toBeNull();
  });

  it('в MAX пункты меню — в той же ⋯ шапки, что и в браузере, и не дублируются в теле', async () => {
    installMaxBridge();
    const onSelect = vi.fn();
    const user = userEvent.setup();
    renderInLayout(
      <Screen title="Ключи" menu={[{ label: 'Выпустить ключ', onSelect }]}>
        тело
      </Screen>,
      { nested: true },
    );
    expect(screen.queryByRole('button', { name: 'Выпустить ключ' })).toBeNull();
    await user.click(screen.getByRole('button', { name: strings.ui.menu }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByRole('button', { name: strings.header.switchOrganization })).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Выпустить ключ' }));
    expect(onSelect).toHaveBeenCalled();
  });

  it('корень вкладки в MAX с пунктами меню шапку не теряет', () => {
    installMaxBridge();
    renderInLayout(
      <Screen title={strings.ui.appTitle} menu={[{ label: 'Выпустить ключ', onSelect: () => {} }]}>
        тело
      </Screen>,
    );
    expect(document.querySelector('.ui-header--bare')).toBeNull();
    expect(screen.getByRole('button', { name: strings.ui.menu })).toBeInTheDocument();
  });

  it('в браузере пункты меню остаются в ⋯ и не дублируются в теле', () => {
    renderInLayout(
      <Screen title="Ключи" menu={[{ label: 'Выпустить ключ', onSelect: () => {} }]}>
        тело
      </Screen>,
      { nested: true },
    );
    expect(screen.getByRole('button', { name: strings.ui.menu })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Выпустить ключ' })).toBeNull();
  });
});

describe('тема из bridge', () => {
  it('без initData тема MAX не считается заданной', () => {
    window.WebApp = { colorScheme: 'dark' };
    expect(getColorScheme()).toBeNull();
  });

  it('в мини-приложении тема берётся из bridge', () => {
    installMaxBridge('dark');
    expect(getColorScheme()).toBe('dark');
  });
});

describe('доступность строк и плиток', () => {
  it('aria-label строки не глушит подзаголовок и значение', () => {
    renderInLayout(
      <ListRow
        title="requests:read"
        subtitle="Чтение заявок"
        value="200"
        aria-label="Право requests:read"
        onClick={() => {}}
      />,
    );
    const row = screen.getByRole('button', { name: 'Право requests:read' });
    expect(row).toHaveAccessibleDescription('Чтение заявок 200');
  });

  it('без aria-label описание не добавляется', () => {
    renderInLayout(<ListRow title="Точки" subtitle="3 точки" onClick={() => {}} />);
    expect(screen.getByRole('button', { name: /Точки/ })).not.toHaveAttribute('aria-describedby');
  });

  it('строка, открывающая лист, — aria-haspopup без aria-expanded', () => {
    renderInLayout(<ListRow title="Жалоба" opensDialog expanded={false} onClick={() => {}} />);
    const row = screen.getByRole('button', { name: 'Жалоба' });
    expect(row).toHaveAttribute('aria-haspopup', 'dialog');
    expect(row).not.toHaveAttribute('aria-expanded');
  });

  it('статус плитки фото слышен вместе с описанием', () => {
    renderInLayout(
      <>
        <PhotoTile state="e" alt="Фото 1 заявки" />
        <PhotoTile state="q" alt="Фото 2 заявки" />
        <PhotoTile state="e" alt="Шильдик" onClick={() => {}} />
        <PhotoTile state="e" alt="Общий вид" actionLabel="Выбрать другое фото" onClick={() => {}} />
      </>,
    );
    expect(screen.getByRole('img', { name: 'Фото 1 заявки. Отклонено' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Фото 2 заявки. Проверяем…' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Шильдик. Отклонено' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать другое фото' })).toBeInTheDocument();
    expect(screen.getAllByText(strings.ui.photoReplace)).toHaveLength(2);
    expect(screen.getByText(strings.ui.photoRejected)).toBeInTheDocument();
  });
});

async function acceptedOwnServiceRequest(): Promise<string> {
  const managerAuth = await demoLoginRaw('customer_manager');
  const locs = await apiCall<{ items: { id: string; name: string }[] }>('/locations', managerAuth);
  const cafe = locs.items.find((l) => l.name.includes('Тверской'))!;
  const eq = await apiCall<{ items: { id: string; brand: string }[] }>(
    `/equipment?location_id=${cafe.id}`,
    managerAuth,
  );
  const bosch = eq.items.find((e) => e.brand === 'Bosch')!;
  const draft = await apiCall<RequestCustomer>('/requests', managerAuth, {
    body: { equipment_id: bosch.id, route: 'own_service', urgency: 'normal' },
  });
  const submitted = await apiCall<RequestCustomer>(
    `/requests/${draft.id}/actions/submit-to-own-service`,
    managerAuth,
    { body: { photos_incomplete: false, photos_incomplete_reason: null } },
  );
  return submitted.id;
}

describe('подэкраны карточки исполнителя: история и незаконченный ввод', () => {
  it('подэкран в адресе, «назад» с вводом спрашивает, без ввода — нет', async () => {
    const requestId = await acceptedOwnServiceRequest();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = `/provider/requests/${requestId}`;
    await user.click(await screen.findByRole('button', { name: 'Принять' }));
    await user.click(await screen.findByRole('button', { name: 'Предложить выезд' }));

    const price = await screen.findByLabelText('Стоимость выезда и диагностики');
    expect(window.location.hash).toContain('view=visit');

    await user.type(price, '1500');
    await user.click(screen.getByRole('button', { name: strings.ui.back }));
    const dialog = within(await screen.findByRole('alertdialog'));
    expect(dialog.getByText(strings.ui.unsavedTitle)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: strings.ui.unsavedStay }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(screen.getByLabelText('Стоимость выезда и диагностики')).toHaveValue('1500');

    await user.click(screen.getByRole('button', { name: strings.ui.back }));
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: strings.ui.unsavedLeave,
      }),
    );
    await screen.findByRole('button', { name: 'Предложить выезд' });
    await waitFor(() => expect(window.location.hash).not.toContain('view='));

    await user.click(screen.getByRole('button', { name: 'Предложить выезд' }));
    await screen.findByLabelText('Стоимость выезда и диагностики');
    await user.click(screen.getByRole('button', { name: strings.ui.back }));
    await screen.findByRole('button', { name: 'Предложить выезд' });
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });
});

describe('профиль исполнителя: смена организации в теле', () => {
  it('строка «Сменить организацию» ведёт к выбору организации', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/provider/profile';
    await findRowLink('/provider/reviews');
    await user.click(screen.getByRole('button', { name: /Сменить организацию/ }));
    await waitFor(() => expect(window.location.hash).toBe('#/organizations'));
  });
});
