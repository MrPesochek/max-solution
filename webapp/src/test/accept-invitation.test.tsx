import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen, expectActiveContext } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

describe('сценарий: приём приглашения', () => {
  it('руководитель заказчика создаёт приглашение сотруднику', async () => {
    const user = userEvent.setup();
    renderApp();

    await loginAsDemo('customer_manager');

    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });

    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
    await user.click(await screen.findByRole('button', { name: 'Пригласить сотрудника' }));

    await user.click(await screen.findByRole('radio', { name: /^Сотрудник/ }));
    expect(screen.getByRole('radio', { name: /^Сотрудник/ })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Кафе на Тверской' }));
    await user.click(screen.getByRole('button', { name: 'Создать ссылку' }));

    await screen.findByText('Приглашение создано');
    expect(screen.queryByDisplayValue(/startapp=inv_/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Скопировать ссылку' }));
    expect(await navigator.clipboard.readText()).toContain('startapp=inv_');
  });

  it('без адресата: принявший ждёт подтверждения руководителя', async () => {
    const invitationLink = await issueInvitation({});

    const user = userEvent.setup();
    renderApp();
    await openInvitationAsNewUser(user, invitationLink);

    await user.click(screen.getByRole('button', { name: 'Принять' }));

    await screen.findByText('Ждёт подтверждения руководителя');
    expect(screen.queryByText('Вы в команде')).not.toBeInTheDocument();
  });

  it('именное приглашение адресату открывает доступ сразу', async () => {
    const invitationLink = await issueInvitation({ recipient_max_user_id: await newUserId() });

    const user = userEvent.setup();
    renderApp();
    await openInvitationAsNewUser(user, invitationLink);

    await user.click(screen.getByRole('button', { name: 'Принять' }));

    await screen.findByText('Вы в команде');
    await user.click(screen.getByRole('button', { name: 'На главную' }));
    await findHomeScreen();
    await expectActiveContext('ООО «Ромашка»', 'Сотрудник заказчика');
  });

  it('чужое именное приглашение не срабатывает и остаётся действующим', async () => {
    const invitationLink = await issueInvitation({ recipient_max_user_id: 'другой-пользователь' });

    const user = userEvent.setup();
    renderApp();
    await openInvitationAsNewUser(user, invitationLink);

    await user.click(screen.getByRole('button', { name: 'Принять' }));

    await screen.findByText('Приглашение не сработало');
    const manager = await demoLoginRaw('customer_manager');
    const listed = await apiCall<{ items: { state: string; named: boolean }[] }>(
      '/invitations',
      manager,
    );
    expect(listed.items.some((i) => i.named && i.state === 'active')).toBe(true);
  });

  it('руководитель заказчика видит имя из MAX и время принятия и подтверждает', async () => {
    const invitationLink = await issueInvitation({ recipient_name: 'Пётр Новиков' });
    const token = invitationLink.split('startapp=')[1]!;
    const newcomer = await demoAuth('new_user');
    await fetch('/app-api/v1/invitations/accept', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${newcomer.token}`,
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({ token }),
    });

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
    await screen.findByRole('heading', { level: 1, name: 'Сотрудники' });

    await user.click(await screen.findByRole('button', { name: new RegExp(newcomer.name) }));
    const dialog = within(await screen.findByRole('alertdialog'));
    expect(dialog.getByText('Имя в MAX')).toBeInTheDocument();
    expect(dialog.getByText('Пётр Новиков')).toBeInTheDocument();
    expect(dialog.getByText('Приглашение принято')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    const manager = await demoLoginRaw('customer_manager');
    const staff = await apiCall<{ items: { status: string; user: { display_name: string } }[] }>(
      '/memberships',
      manager,
    );
    expect(staff.items.find((m) => m.user.display_name === newcomer.name)?.status).toBe('active');
  });

  it('на экране приглашения можно указать адресата', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });
    await user.click(await screen.findByRole('link', { name: /^Сотрудники/ }));
    await user.click(await screen.findByRole('button', { name: 'Пригласить сотрудника' }));

    await user.click(await screen.findByRole('radio', { name: /^Сотрудник/ }));
    await user.click(screen.getByRole('button', { name: 'Кафе на Тверской' }));
    await user.type(screen.getByLabelText('Имя сотрудника'), 'Ольга');
    await user.type(screen.getByLabelText('ID пользователя в MAX'), '123456');
    await user.click(screen.getByRole('button', { name: 'Создать ссылку' }));

    await screen.findByText('Приглашение создано');
    expect(screen.getByText('Ольга')).toBeInTheDocument();
    expect(screen.getByText('Сразу — только указанному пользователю MAX')).toBeInTheDocument();
  });
});

async function demoAuth(userKey: string): Promise<{ token: string; id: string; name: string }> {
  const response = await fetch('/app-api/v1/auth/demo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_key: userKey }),
  });
  const data = (await response.json()) as { token: string; user: { id: string; display_name: string } };
  return { token: data.token, id: data.user.id, name: data.user.display_name };
}

async function newUserId(): Promise<string> {
  return (await demoAuth('new_user')).id;
}

async function issueInvitation(recipient: {
  recipient_max_user_id?: string;
  recipient_name?: string;
}): Promise<string> {
  const manager = await demoLoginRaw('customer_manager');
  const locations = await apiCall<{ items: { id: string; name: string }[] }>('/locations', manager);
  const invitation = await apiCall<{ token: string }>('/invitations', manager, {
    body: {
      role: 'customer_employee',
      location_ids: [locations.items.find((l) => l.name === 'Кафе на Тверской')!.id],
      ...recipient,
    },
  });
  return `https://max.ru/app?startapp=${invitation.token}`;
}

async function openInvitationAsNewUser(
  user: ReturnType<typeof userEvent.setup>,
  invitationLink: string,
): Promise<void> {
  await loginAsDemo('new_user');

  await screen.findByRole('heading', { name: 'Ремонт техники без звонков' });
  await user.click(screen.getByRole('button', { name: 'Ввести код' }));

  await screen.findByRole('dialog', { name: 'Ввести приглашение' });
  await user.type(screen.getByLabelText('Ссылка или код приглашения'), invitationLink);
  await user.click(screen.getByRole('button', { name: 'Открыть приглашение' }));

  await screen.findByRole('heading', { name: 'Приглашение' });
  expect(screen.getByText('Вас приглашают в ООО «Ромашка»')).toBeInTheDocument();
  expect(screen.getByText('Сотрудник')).toBeInTheDocument();
}
