import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen, expectActiveContext } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';
import { queryClient } from '../api/queryClient';
import { getActiveMembershipId } from '../api/orgStore';
import type { AuthResponse, Membership } from '../api/types';

async function membershipsOf(userKey: string): Promise<Membership[]> {
  const response = await fetch('/app-api/v1/auth/demo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_key: userKey }),
  });
  return ((await response.json()) as AuthResponse).memberships;
}

function captureContextHeaders(): { membership: string | null; organization: string | null }[] {
  const seen: { membership: string | null; organization: string | null }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname.endsWith('/organizations/current')) {
      seen.push({
        membership: request.headers.get('X-Membership-Id'),
        organization: request.headers.get('X-Organization-Id'),
      });
    }
  });
  return seen;
}

describe('организация с двумя типами участия: контекст — членство', () => {
  it('выбор «Название · сторона», X-Membership-Id по активному членству, быстрое переключение', async () => {
    const memberships = await membershipsOf('dual_manager');
    const customer = memberships.find((m) => m.side === 'customer')!;
    const provider = memberships.find((m) => m.side === 'provider')!;
    expect(customer.organization.id).toBe(provider.organization.id);
    const headers = captureContextHeaders();

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('dual_manager');

    await screen.findByRole('heading', { name: 'Где работаем сегодня?' });
    expect(
      screen.getByRole('radio', { name: /Два берега.*Заказчик · руководитель/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Войти' })).toBeDisabled();
    await user.click(
      screen.getByRole('radio', { name: /Два берега.*Исполнитель · администратор/ }),
    );
    await user.click(screen.getByRole('button', { name: 'Войти' }));

    await screen.findByRole('link', { name: 'Профиль' });
    expect(getActiveMembershipId()).toBe(provider.id);
    expect(window.localStorage.getItem('max-webapp.active-membership-id')).toBe(provider.id);

    window.location.hash = '#/organization';
    await screen.findByRole('heading', { name: 'Организация' });
    await waitFor(() =>
      expect(headers.at(-1)).toEqual({
        membership: provider.id,
        organization: provider.organization.id,
      }),
    );
    window.location.hash = '#/organization/staff';
    await screen.findByRole('heading', { level: 1, name: 'Сотрудники' });
    await screen.findByText('Елена Двойнова');
    expect(screen.getByText('Администратор')).toBeInTheDocument();
    expect(screen.queryByText(/^Руководитель/)).not.toBeInTheDocument();
    window.location.hash = '#/organization';
    await screen.findByRole('heading', { name: 'Организация' });

    await user.click(
      await screen.findByRole('button', { name: 'Перейти: ООО «Два берега» · заказчик' }),
    );
    await findHomeScreen();
    expect(getActiveMembershipId()).toBe(customer.id);

    window.location.hash = '#/organization';
    await screen.findByRole('heading', { name: 'Организация' });
    await waitFor(() =>
      expect(headers.at(-1)).toEqual({
        membership: customer.id,
        organization: customer.organization.id,
      }),
    );

    const staffKeys = queryClient
      .getQueryCache()
      .findAll({ queryKey: ['memberships'] })
      .map((q) => q.queryKey[1]);
    expect(staffKeys).toEqual(expect.arrayContaining([provider.id, customer.id]));
    server.events.removeAllListeners();
  });

  it('по одному X-Organization-Id сервер не выбирает сторону — 409 MEMBERSHIP_AMBIGUOUS', async () => {
    const auth = await demoLoginRaw('dual_manager');
    await expect(apiCall('/organizations/current', auth)).rejects.toThrow(
      /409.*MEMBERSHIP_AMBIGUOUS/,
    );
  });

  it('при MEMBERSHIP_AMBIGUOUS приложение возвращает к выбору организации', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    server.use(
      http.get('*/organizations/current', () =>
        HttpResponse.json(
          {
            error: { code: 'MEMBERSHIP_AMBIGUOUS', message: 'выберите членство', request_id: 'r' },
          },
          { status: 409 },
        ),
      ),
    );
    window.location.hash = '#/organization';
    await screen.findByRole('heading', { name: 'Где работаем сегодня?' });
  });

  it('404 от /auth/demo (демо-вход выключен на сервере) — понятное сообщение', async () => {
    server.use(
      http.post('*/auth/demo', () =>
        HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'Not Found', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    renderApp();
    await loginAsDemo('customer_manager');
    expect(await screen.findByText('Демо-вход на этом сервере выключен.')).toBeInTheDocument();
  });
});

describe('профиль организации редактируется руководителем', () => {
  it('руководитель меняет контакт; ошибки реквизитов показываются понятным текстом', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });

    await user.click(await screen.findByRole('button', { name: 'Изменить профиль' }));
    const contactName = await screen.findByLabelText('Контактное лицо');
    await user.type(contactName, 'Иван Петров');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText(/Иван Петров, \+7 900 000-00-00/);

    server.use(
      http.patch('*/organizations/current', () =>
        HttpResponse.json(
          { error: { code: 'REQUISITES_UNDER_REVIEW', message: 'raw', request_id: 'r' } },
          { status: 409 },
        ),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Изменить профиль' }));
    const inn = await screen.findByLabelText('ИНН');
    await user.clear(inn);
    await user.type(inn, '7712345617');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(
      await screen.findByText(
        'Реквизиты сейчас на проверке — изменить их можно после решения оператора.',
      ),
    ).toBeInTheDocument();
  });

  it('ИНН проверенной организации заблокирован: поле недоступно, сервер (мок) отвечает INN_LOCKED', async () => {
    const auth = await demoLoginRaw('provider_active_admin');
    await expect(
      apiCall('/organizations/current', auth, { method: 'PATCH', body: { inn: '7712345617' } }),
    ).rejects.toThrow(/409.*INN_LOCKED/);

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('link', { name: 'Профиль' });
    window.location.hash = '#/organization';
    await user.click(await screen.findByRole('button', { name: 'Изменить профиль' }));
    expect(await screen.findByLabelText('ИНН')).toBeDisabled();
    expect(
      screen.getByText('ИНН проверенной организации меняется только через оператора платформы'),
    ).toBeInTheDocument();
  });
});

describe('второй тип участия организации', () => {
  it('руководитель заказчика становится исполнителем и переключается на новое членство', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Организация' }));
    await screen.findByRole('heading', { name: 'Организация' });

    await user.click(await screen.findByRole('button', { name: 'Стать исполнителем' }));
    await user.selectOptions(await screen.findByLabelText('Форма работы'), 'Компания');
    const customerMembershipId = getActiveMembershipId();
    const trail: { path: string; activeMembership: string | null }[] = [];
    server.events.on('request:start', ({ request }) => {
      const path = new URL(request.url).pathname;
      if (path.endsWith('/participation') || path.endsWith('/me')) {
        trail.push({ path: path.split('/').at(-1)!, activeMembership: getActiveMembershipId() });
      }
    });
    const submit = screen.getAllByRole('button', { name: 'Стать исполнителем' }).at(-1)!;
    await user.click(submit);

    await screen.findByRole('tab', { name: 'Входящие', selected: true });
    await expectActiveContext('ООО «Ромашка»', 'Администратор исполнителя');
    expect(trail).toEqual([
      { path: 'participation', activeMembership: customerMembershipId },
      { path: 'me', activeMembership: customerMembershipId },
    ]);
    server.events.removeAllListeners();

    const memberships = await membershipsOf('customer_manager');
    const sides = memberships
      .filter((m) => m.organization.name === 'ООО «Ромашка»')
      .map((m) => m.side);
    expect(sides.sort()).toEqual(['customer', 'provider']);
    expect(getActiveMembershipId()).toBe(memberships.find((m) => m.side === 'provider')!.id);

    window.location.hash = '#/organization';
    await screen.findByRole('button', { name: 'Перейти: ООО «Ромашка» · заказчик' });
    await user.click(screen.getByRole('button', { name: 'Сменить организацию' }));
    await screen.findByRole('heading', { name: 'Где работаем сегодня?' });
    expect(
      screen.getByRole('radio', { name: /Ромашка.*Заказчик · руководитель/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: /Ромашка.*Исполнитель · администратор/ }),
    ).toBeInTheDocument();

    const customerMembership = memberships.find((m) => m.side === 'customer')!;
    const response = await fetch(
      `/app-api/v1/organizations/${customerMembership.organization.id}/participation`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${(await demoLoginRaw('customer_manager')).token}`,
          'X-Membership-Id': customerMembership.id,
          'Idempotency-Key': crypto.randomUUID(),
        },
        body: JSON.stringify({ kind: 'provider', provider_kind: 'company' }),
      },
    );
    expect(response.status).toBe(409);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe(
      'PARTICIPATION_EXISTS',
    );
  });
});
