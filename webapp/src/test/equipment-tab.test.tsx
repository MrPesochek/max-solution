import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import * as db from '../mocks/db';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';

describe('вкладка «Техника» (15c)', () => {
  it('строка техники — статус обслуживания, раскрытие «Новая заявка / Карточка»; чипы фильтруют по точке', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Техника' }));
    await screen.findByRole('heading', { name: 'Техника' });

    const bosch = await screen.findByRole('button', { name: /Bosch KGN39VL316/ });
    expect(await within(bosch).findByText(/Сервис-Холод Плюс · |^Гарантия: /)).toBeInTheDocument();
    expect(
      within(screen.getByRole('button', { name: /Saeco Royal/ })).getByText('Мой контакт: Мастер Николай (частный)'),
    ).toBeInTheDocument();

    expect(bosch).toHaveAttribute('aria-expanded', 'false');
    await user.click(bosch);
    expect(bosch).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'Новая заявка' }).getAttribute('href')).toContain('/requests/new?equipment=');
    expect(screen.getByRole('button', { name: /^Карточка: .*Bosch KGN39VL316/ }).getAttribute('href')).toMatch(
      /^#\/equipment\/[^/]+\/[^/]+$/,
    );

    const segments = screen.getByRole('radiogroup', { name: 'Точка' });
    await user.click(within(segments).getByRole('radio', { name: 'Магазин на Невском' }));
    expect(await screen.findByText('На этой точке пока нет техники')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Bosch KGN39VL316/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Добавить технику' }).getAttribute('href')).toContain('location=');

    await user.click(within(segments).getByRole('radio', { name: 'Все' }));
    expect(await screen.findByRole('button', { name: /^Холодильник Bosch KGN39VL316/ })).toBeInTheDocument();
  });

  it('прежний адрес списка точки открывает вкладку с выбранной точкой', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${db.demoSeed.demoLocation1.id}`;

    const segments = await screen.findByRole('radiogroup', { name: 'Точка' });
    await waitFor(() =>
      expect(within(segments).getByRole('radio', { name: 'Кафе на Тверской' })).toHaveAttribute('aria-checked', 'true'),
    );
    expect(window.location.hash).toContain('/equipment?location=');
  });
});

describe('карточка техники (13b) и гарантия', () => {
  it('«История» — заявки этой техники, «Данные» — модель, заводской номер и шильдик', async () => {
    const user = userEvent.setup();
    const item = db.listEquipment(db.demoSeed.demoCustomer.id).items.find((e) => e.brand === 'Bosch')!;
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${item.location_id}/${item.id}`;
    await screen.findByRole('heading', { name: /Bosch KGN39VL316/ });

    await user.click(screen.getByRole('tab', { name: 'История' }));
    const panel = await screen.findByRole('tabpanel');
    await waitFor(() => expect(within(panel).queryByText('Загрузка…')).not.toBeInTheDocument());
    expect(panel).not.toHaveTextContent('₽');

    await user.click(screen.getByRole('tab', { name: 'Данные' }));
    expect(await screen.findByText('Заводской номер')).toBeInTheDocument();
    expect(screen.getByText(item.serial_number!)).toBeInTheDocument();
    expect(await screen.findByText('Фото шильдика')).toBeInTheDocument();
    expect(window.location.hash).toContain('tab=specs');
  });

  it('подтверждённый сервис и строка гарантии ведут на гарантийные сведения', async () => {
    const user = userEvent.setup();
    const item = db.listEquipment(db.demoSeed.demoCustomer.id).items.find((e) => e.brand === 'Bosch')!;
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${item.location_id}/${item.id}`;
    await screen.findByRole('heading', { name: /Bosch KGN39VL316/ });
    expect(screen.getByRole('tab', { name: 'Сервис' })).toHaveAttribute('aria-selected', 'true');

    expect(await screen.findByText('Подтверждённый сервис')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Найти исполнителя' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Заявка в Сервис-Холод Плюс' }).getAttribute('href')).toContain(
      '/requests/new?equipment=',
    );

    await user.click(screen.getByRole('link', { name: /Гарантия/ }));
    await screen.findByRole('heading', { name: 'Гарантия' });
    expect(await screen.findByText('Обслуживает')).toBeInTheDocument();
    expect(screen.getByText('Сервис-Холод Плюс')).toBeInTheDocument();
    expect(screen.getByText(/Относится ли конкретная поломка к гарантии/)).toBeInTheDocument();
  });

  it('техника только с личным контактом: предупреждение и действия «Подключить сервис» / «Найти исполнителя»', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Техника' }));
    await user.click(await screen.findByRole('link', { name: 'Добавить технику' }));
    await screen.findByRole('heading', { name: 'Новая техника' });
    const add = await screen.findByRole('button', { name: 'Добавить' });
    expect(add).toBeDisabled();
    await user.click(within(screen.getByRole('radiogroup', { name: 'Точка' })).getByRole('radio', { name: 'Магазин на Невском' }));
    await user.click(within(screen.getByRole('radiogroup', { name: 'Категория' })).getByRole('radio', { name: 'Холодильное оборудование' }));
    await user.type(screen.getByLabelText('Бренд'), 'Polair');
    await user.type(screen.getByLabelText('Модель'), 'TM2');
    await user.click(add);

    await user.click(await screen.findByRole('button', { name: /Polair TM2/ }));
    await user.click(screen.getByRole('button', { name: /^Карточка: .*Polair TM2/ }));
    await screen.findByRole('heading', { name: /Polair TM2/ });
    expect(await screen.findByText('Отправить заявку через приложение нельзя')).toBeInTheDocument();
    const connect = screen.getByRole('button', { name: 'Подключить сервис' });
    expect(connect.getAttribute('href')).toContain('/bindings/new?equipment=');
    expect(screen.getByRole('button', { name: 'Найти исполнителя' })).toBeInTheDocument();

    await user.click(connect);
    await user.click(await screen.findByRole('button', { name: /Сохранить контакт мастера/ }));
    await user.type(await screen.findByLabelText('Имя или название'), 'Мастер Сергей');
    expect(screen.getByLabelText('Техника')).not.toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Сохранить контакт' }));
    await screen.findByText('Контакт сохранён');
    await user.click(screen.getByRole('button', { name: 'Готово' }));

    await screen.findByRole('heading', { name: /Polair TM2/ });
    expect(await screen.findByText('Мастер Сергей')).toBeInTheDocument();
    expect(screen.getByText('мой контакт')).toBeInTheDocument();
    expect(screen.getByText('Этот мастер не подключён. Позвоните ему или найдите исполнителя через поиск.')).toBeInTheDocument();
  });
});
