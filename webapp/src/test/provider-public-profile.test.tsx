import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { demoSeed, listProviderCatalog } from '../mocks/db';
import { seedPendingPortfolioAttachment } from '../mocks/portfolio';
import { approveModeratedAttachment, setPortfolioCaption } from '../mocks/requestsDb';

async function openProvidersCatalog(_user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await findHomeScreen();
  window.location.hash = '#/providers';
  await screen.findByRole('heading', { name: 'Исполнители' });
}

describe('каталог и публичный профиль исполнителя: модель доверия без единого «Проверен»', () => {
  it('каталог показывает только допущенных исполнителей и ведёт на публичный профиль', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openProvidersCatalog(user);

    await screen.findByText('Сервис-Холод Плюс');
    expect(screen.queryByText('Сервис-Холод')).not.toBeInTheDocument();

    await user.click(screen.getByText('Сервис-Холод Плюс'));
    await screen.findByRole('heading', { name: 'Сервис-Холод Плюс' });
  });

  it('публичный профиль показывает раздельные признаки проверки с расшифровкой, без единого значка', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openProvidersCatalog(user);

    await screen.findByText('Сервис-Холод Плюс');
    await user.click(screen.getByText('Сервис-Холод Плюс'));
    await screen.findByRole('heading', { name: 'Сервис-Холод Плюс' });

    expect(screen.queryByText(/^Проверен$/)).not.toBeInTheDocument();

    const requisites = screen.getByRole('button', { name: /^Реквизиты проверены/ });
    const representative = screen.getByRole('button', { name: /^Представитель подтверждён/ });
    expect(requisites).toHaveAttribute('aria-expanded', 'false');
    const demoLabels = screen.getAllByText('Демонстрационная проверка');
    expect(demoLabels.length).toBeGreaterThan(0);

    await user.click(requisites);
    await user.click(representative);
    expect(requisites).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByText(/Организация, ИП или статус НПД найдены в официальном источнике/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Не подтверждает право выполнять ремонт любого бренда/)).toBeInTheDocument();

    expect(screen.getAllByText('Со слов исполнителя').length).toBeGreaterThan(0);
    const reviewsRow = screen.getByRole('link', { name: /Отзывы · ★ 4,6/ });
    expect(screen.queryByText('Мало отзывов')).not.toBeInTheDocument();

    expect(screen.getByText('Исполнитель ещё не добавил фотографии работ')).toBeInTheDocument();

    await user.click(reviewsRow);
    await screen.findByRole('heading', { name: '★ 4,6' });
    await screen.findByText(/^Подтверждённый бизнес-клиент · ★/);
    expect(screen.getByText('Приехали в тот же день, аккуратно поменяли компрессор. Рекомендуем.')).toBeInTheDocument();
    expect(screen.getByText('Спасибо за отзыв! Рады, что всё прошло гладко.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Пожаловаться на отзыв' })).toBeInTheDocument();
  });

  it('работы в профиле — gallery_items с подписями (11c, K-18)', async () => {
    const orgId = demoSeed.demoActiveProvider.id;
    const captioned = seedPendingPortfolioAttachment(orgId);
    const plain = seedPendingPortfolioAttachment(orgId);
    setPortfolioCaption(captioned.id, orgId, 'Замена компрессора витрины');
    approveModeratedAttachment(captioned.id);
    approveModeratedAttachment(plain.id);
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openProvidersCatalog(user);
    await user.click(await screen.findByText('Сервис-Холод Плюс'));
    await screen.findByRole('heading', { name: 'Сервис-Холод Плюс' });

    expect(screen.getByText('Замена компрессора витрины')).toBeInTheDocument();
    expect(screen.queryByText('Исполнитель ещё не добавил фотографии работ')).not.toBeInTheDocument();
  });

  it('поиск по названию в моке — как на сервере: начало слова, знаки не мешают (K-10)', () => {
    const names = (q: string) => listProviderCatalog({ q }).items.map((p) => p.name);
    expect(names('Холод')).toContain('Сервис-Холод Плюс');
    expect(names('Сервис-Холод')).toContain('Сервис-Холод Плюс');
    expect(names('«сервис холод»')).toContain('Сервис-Холод Плюс');
    expect(names('холод плюс')).toContain('Сервис-Холод Плюс');
    expect(names('олод')).not.toContain('Сервис-Холод Плюс');
    expect(names('сервис плюс')).not.toContain('Сервис-Холод Плюс');
  });
});
