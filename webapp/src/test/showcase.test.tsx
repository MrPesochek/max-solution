import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { server } from '../mocks/server';
import * as db from '../mocks/db';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';

it('открывает общие демоданные после входа и выбора роли', async () => {
  const user = userEvent.setup();
  renderApp();
  await loginAsDemo('customer_manager');
  await findHomeScreen();
  const membership = db.getMembershipsForUser(db.findUserIdByDemoKey('customer_manager')!)
    .find((m) => m.organization.id === db.demoSeed.demoCustomer.id)!;
  server.use(
    http.get('*/showcase', () => HttpResponse.json({ enabled: true })),
    http.post('*/showcase/join', async ({ request }) => {
      expect(await request.json()).toEqual({ side: 'customer' });
      return HttpResponse.json(membership);
    }),
  );
  window.location.hash = '#/organizations';
  await user.click(await screen.findByRole('button', { name: 'Демо: я заказчик' }));
  await findHomeScreen();
});

it('обычный пользователь принимает демо-решение и видит его в истории', async () => {
  const user = userEvent.setup();
  let approved = false;
  server.use(
    http.get('*/showcase', () => HttpResponse.json({ enabled: true })),
    http.get('*/showcase/verification-cases', () => HttpResponse.json({
      items: [{ id: 'ver_demo', organization_name: 'Демо: проверяемый сервис',
        check_kind: 'requisites', decision: approved ? 'approved' : 'pending',
        organization_inn: null, evidence_note: 'Регистрация сервиса',
        decision_reason: approved ? 'Данные совпадают' : null,
        source: approved ? 'Демо-реестр' : null }], next_cursor: null,
    })),
    http.post('*/showcase/verification-cases/ver_demo/decision', async ({ request }) => {
      expect(await request.json()).toMatchObject({ decision: 'approved', is_demo: true });
      approved = true;
      return HttpResponse.json({});
    }),
  );
  renderApp();
  await loginAsDemo('customer_manager');
  await findHomeScreen();
  window.location.hash = '#/organizations';
  await user.click(await screen.findByRole('button', { name: 'Демо: оператор' }));
  await screen.findByRole('heading', { name: 'Демо: проверка организаций' });
  await user.click(await screen.findByText('Демо: проверяемый сервис'));
  expect(screen.getByRole('button', { name: 'Отправить решение' })).toBeDisabled();
  await user.type(screen.getByLabelText('Основание решения (обязательно)'), 'Данные совпадают');
  await user.type(screen.getByLabelText('Источник проверки (обязательно)'), 'Демо-реестр');
  await user.click(screen.getByRole('button', { name: 'Отправить решение' }));
  await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Подтвердить' }));
  await screen.findByText('Очередь пуста');
  await user.click(screen.getByRole('radio', { name: 'Решения' }));
  await user.click(await screen.findByText('Демо: проверяемый сервис'));
  await screen.findByText('Данные совпадают');
  expect(screen.queryByRole('button', { name: 'Отправить решение' })).not.toBeInTheDocument();
});
