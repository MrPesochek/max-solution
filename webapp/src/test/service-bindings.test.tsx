import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { api } from '../api/client';
import { ApiError } from '../api/errors';
import type { BindingRequestAccepted } from '../api/types';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';
import { server } from '../mocks/server';

async function pickProvider(user: ReturnType<typeof userEvent.setup>, query = 'Холод', name = 'Сервис-Холод Плюс') {
  await user.type(await screen.findByRole('textbox', { name: 'Сервис' }), query);
  await user.click(await screen.findByRole('radio', { name }));
}

async function rawCall(path: string, auth: { token: string; organizationId: string }, body: unknown) {
  return fetch(`/app-api/v1${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.token}`,
      'X-Organization-Id': auth.organizationId,
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify(body),
  });
}

async function openAddBindingScreen(
  user: ReturnType<typeof userEvent.setup>,
  way: RegExp = /По приглашению от сервиса/,
): Promise<void> {
  await findHomeScreen();
  await user.click(screen.getByRole('link', { name: 'Техника' }));
  await screen.findByRole('heading', { name: 'Техника' });
  await user.click(await screen.findByRole('button', { name: /Bosch KGN39VL316/ }));
  await user.click(screen.getByRole('button', { name: /^Карточка: .*Bosch KGN39VL316/ }));
  await screen.findByRole('heading', { name: /Bosch KGN39VL316/ });
  await user.click((await screen.findAllByRole('link', { name: /Сервис-Холод Плюс/ }))[0]!);
  await screen.findByRole('heading', { level: 1, name: 'Подключённые сервисы' });
  await user.click(await screen.findByRole('link', { name: 'Подключить сервис' }));
  await screen.findByRole('heading', { name: 'Как подключить сервис?' });
  await user.click(await screen.findByRole('button', { name: way }));
}

describe('приём приглашения на привязку', () => {
  it('руководитель заказчика видит точное предложение и подтверждает привязку', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openAddBindingScreen(user);

    await user.type(
      screen.getByLabelText('Ссылка или код приглашения'),
      'https://max.ru/repairbot/webapp?startapp=sb_demo-sb-valid-token',
    );
    await user.click(screen.getByRole('button', { name: 'Открыть приглашение' }));

    await screen.findByRole('heading', { name: 'Подключение' });
    await screen.findByText('Приглашение от Сервис-Холод Плюс');
    expect(screen.getByText('Договор № Д-300')).toBeInTheDocument();
    const position = () => screen.getByRole('button', { name: /^Холодильная витрина\./ });
    expect(position()).toHaveTextContent('Ваша: Холодильник Bosch KGN39VL316 · Кафе на Тверской');
    const confirm = screen.getByRole('button', { name: 'Подключить' });
    expect(confirm).toBeEnabled();

    await user.click(position());
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Не сопоставлять' }));
    expect(position()).toHaveTextContent('зав. № SN-001122 · Выберите свою технику');
    expect(confirm).toBeDisabled();

    await user.click(position());
    let sheet = within(await screen.findByRole('dialog'));
    await user.click(
      within(sheet.getByRole('radiogroup', { name: 'Ваша техника для позиции «Холодильная витрина»' })).getByRole('radio', {
        name: /Saeco Royal/,
      }),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await user.click(confirm);
    await screen.findByText(/Заводской номер выбранной техники не совпадает с позицией «Холодильная витрина»/);
    expect(position()).toHaveAttribute('aria-invalid', 'true');

    await user.click(position());
    sheet = within(await screen.findByRole('dialog'));
    await user.click(sheet.getByRole('radio', { name: /Bosch KGN39VL316/ }));
    await user.click(confirm);
    await screen.findByText('Сервис подключён');
    expect(screen.getByText('1 единица техники теперь обслуживает Сервис-Холод Плюс.')).toBeInTheDocument();
  });

  it('неизвестный и истёкший токен дают одинаково нейтральный отказ, не раскрывая причину', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openAddBindingScreen(user);

    await user.type(screen.getByLabelText('Ссылка или код приглашения'), 'sb_this-token-does-not-exist');
    await user.click(screen.getByRole('button', { name: 'Открыть приглашение' }));
    await screen.findByText('Приглашение недействительно');
    expect(
      screen.getByText('Ссылка устарела, отозвана или уже использована другой организацией.'),
    ).toBeInTheDocument();
  });

  it('истёкшее приглашение недействительно', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openAddBindingScreen(user);

    await user.type(screen.getByLabelText('Ссылка или код приглашения'), 'sb_demo-sb-expired-token');
    await user.click(screen.getByRole('button', { name: 'Открыть приглашение' }));
    await screen.findByText('Приглашение недействительно');
  });
});

describe('выпуск приглашения исполнителем: перечень позиций', () => {
  it('позиции добавляются и удаляются, без описания позиции приглашение не создаётся', async () => {
    const user = userEvent.setup();
    let sentBody: unknown = null;
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/service-binding-invitations')) {
        void request.clone().json().then((body: unknown) => {
          sentBody = body;
        });
      }
    });

    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('link', { name: 'Профиль' });
    window.location.hash = '#/bindings/invitations';
    await screen.findByRole('heading', { name: 'Приглашения клиентов' });

    await user.click(await screen.findByRole('button', { name: 'Создать приглашение' }));
    await screen.findByRole('heading', { name: 'Новое приглашение' });
    await user.type(screen.getByLabelText('ИНН заказчика'), '7712345600');
    await user.type(screen.getByLabelText('Номер договора'), 'Д-777');

    const submit = screen.getByRole('button', { name: 'Создать приглашение' });
    expect(submit).toBeDisabled();

    const first = screen.getByRole('group', { name: 'Позиция 1' });
    await user.type(within(first).getByLabelText('Описание'), 'Холодильная витрина');
    await user.type(within(first).getByLabelText('Серийный номер'), 'SN-001122');

    await user.click(screen.getByRole('button', { name: 'Добавить позицию' }));
    const second = screen.getByRole('group', { name: 'Позиция 2' });
    await user.type(within(second).getByLabelText('Описание'), 'Кофемашина');
    await user.type(within(second).getByLabelText('Модель'), 'Royal');

    await user.click(screen.getByRole('button', { name: 'Добавить позицию' }));
    expect(screen.getByRole('group', { name: 'Позиция 3' })).toBeInTheDocument();
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Удалить позицию: Позиция 3' }));
    expect(screen.queryByRole('group', { name: 'Позиция 3' })).not.toBeInTheDocument();

    await user.click(submit);
    await screen.findByText(/Полный токен показывается только сейчас/);
    expect(sentBody).toMatchObject({
      customer_inn: '7712345600',
      contract_number: 'Д-777',
      equipment_items: [
        { description: 'Холодильная витрина', serial_number: 'SN-001122', model: null },
        { description: 'Кофемашина', serial_number: null, model: 'Royal' },
      ],
    });
    await user.click(screen.getByRole('button', { name: 'Готово' }));
    await screen.findByRole('heading', { name: 'Приглашения клиентов' });
    expect(await screen.findByText(/2 единицы/)).toBeInTheDocument();
    server.events.removeAllListeners();
  });

  it('сервер (мок) отклоняет приглашение без позиций и сопоставление с повтором оборудования — 422', async () => {
    const provider = await demoLoginRaw('provider_active_admin');
    const noItems = await rawCall('/service-binding-invitations', provider, {
      customer_inn: '7712345600',
      contract_number: 'Д-778',
    });
    expect(noItems.status).toBe(422);

    const issued = await rawCall('/service-binding-invitations', provider, {
      customer_inn: '7712345600',
      contract_number: 'Д-779',
      equipment_items: [{ description: 'Витрина' }, { description: 'Кофемашина' }],
    });
    expect(issued.status).toBe(201);
    const { token } = (await issued.json()) as { token: string };

    const manager = await demoLoginRaw('customer_manager');
    const equipment = await apiCall<{ items: { id: string }[] }>('/equipment', manager);
    const eqId = equipment.items[0]!.id;
    const duplicate = await rawCall('/service-binding-invitations/accept', manager, {
      token,
      matches: [
        { item_index: 0, equipment_id: eqId },
        { item_index: 1, equipment_id: eqId },
      ],
    });
    expect(duplicate.status).toBe(422);
    const partial = await rawCall('/service-binding-invitations/accept', manager, {
      token,
      matches: [{ item_index: 0, equipment_id: eqId }],
    });
    expect(partial.status).toBe(422);
  });
});

describe('запрос привязки по номеру договора', () => {
  it('экран одинаков при любом исходе и обрабатывает лимит попыток (429)', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openAddBindingScreen(user, /По номеру договора/);

    await pickProvider(user);
    await user.type(screen.getByLabelText('Номер договора'), 'НЕСУЩЕСТВУЮЩИЙ-999');
    await user.click(screen.getAllByRole('checkbox')[0]!);
    await user.click(screen.getByRole('button', { name: 'Запросить подтверждение' }));

    await screen.findByText('Ждём подтверждения');
    expect(
      screen.getByText('Мы не показываем, найден ли договор, — это защищает данные клиентов сервиса.'),
    ).toBeInTheDocument();

    const equipmentPage = await api.get<{ items: { id: string }[] }>('/equipment');
    const equipmentId = equipmentPage.items[0]!.id;
    const catalog = await api.get<{ items: { id: string; name: string }[] }>('/providers', {
      withoutOrganization: true,
    });
    const providerId = catalog.items.find((p) => p.name === 'Сервис-Холод Плюс')!.id;

    const call = (contractNumber: string) =>
      api.post<BindingRequestAccepted>('/service-bindings/requests', {
        provider_organization_id: providerId,
        contract_number: contractNumber,
        equipment_ids: [equipmentId],
        basis: 'service_contract',
      });

    for (const [index, contractNumber] of ['Д-1', 'Д-2', 'Д-3', 'Д-4'].entries()) {
      const result = await call(contractNumber);
      expect(result).toEqual({
        status: 'submitted',
        message: 'Запрос отправлен на проверку',
        remaining_attempts: 3 - index,
      });
    }

    await expect(call('Д-5')).rejects.toSatisfy(
      (error: unknown) => error instanceof ApiError && error.isRateLimited,
    );
  });
});

describe('«Мой контакт» — личный контакт без проверки платформой', () => {
  it('форма сохраняет контакт и явно предупреждает, что это не гарантийная привязка', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await openAddBindingScreen(user, /Сохранить контакт мастера/);

    expect(
      screen.getByText('Обычный подрядчик без проверки платформой — это не гарантийная привязка'),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText('Имя или название'), 'Частный мастер Пётр');
    await user.selectOptions(screen.getByLabelText('Техника'), 'Холодильник Bosch KGN39VL316');
    await user.click(screen.getByRole('button', { name: 'Сохранить контакт' }));
    await screen.findByText('Контакт сохранён');
  });

  it('на карточке личный контакт помечен как «мой контакт», а не как подтверждённое обслуживание', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');

    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Техника' }));
    await screen.findByRole('heading', { name: 'Техника' });
    await user.click(await screen.findByRole('button', { name: /Saeco Royal/ }));
    await user.click(screen.getByRole('button', { name: /^Карточка: .*Saeco Royal/ }));
    await screen.findByRole('heading', { name: /Saeco Royal/ });

    expect(await screen.findByText('Мастер Николай (частный)')).toBeInTheDocument();
    expect(screen.getByText('+7 900 111-22-33 · мой контакт')).toBeInTheDocument();
    expect(screen.getByText('Ждёт подтверждения сервиса')).toBeInTheDocument();
    expect(screen.queryByText('Подтверждённый сервис')).not.toBeInTheDocument();
  });

  it('в «Подключённых сервисах» личный контакт открывается с честным пояснением платформы', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings';
    await screen.findByRole('heading', { name: 'Подключённые сервисы' });

    await user.click(await screen.findByRole('button', { name: /Мастер Николай/ }));
    const sheet = within(await screen.findByRole('dialog'));
    expect(
      sheet.getByText('Личный контакт. Платформа не подтверждала обслуживание и не доставляет обращения этой компании'),
    ).toBeInTheDocument();
    expect(sheet.getByText('Мой контакт')).toBeInTheDocument();
  });
});

describe('привязка, принятая по приглашению', () => {
  it('в списке привязок видно, какой позиции приглашения она соответствует', async () => {
    const provider = await demoLoginRaw('provider_active_admin');
    const issued = await rawCall('/service-binding-invitations', provider, {
      customer_inn: '7712345600',
      contract_number: 'Д-790',
      equipment_items: [{ description: 'Витрина' }, { description: 'Кофемашина' }],
    });
    const { token } = (await issued.json()) as { token: string };
    const manager = await demoLoginRaw('customer_manager');
    const equipment = await apiCall<{ items: { id: string }[] }>('/equipment', manager);
    const accepted = await rawCall('/service-binding-invitations/accept', manager, {
      token,
      matches: [
        { item_index: 0, equipment_id: equipment.items[0]!.id },
        { item_index: 1, equipment_id: equipment.items[1]!.id },
      ],
    });
    expect(accepted.status).toBeLessThan(300);

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/bindings';
    await screen.findByRole('heading', { name: 'Подключённые сервисы' });
    expect(await screen.findAllByText('Позиция 1 из приглашения: Витрина')).not.toHaveLength(0);
    expect(screen.getAllByText('Позиция 2 из приглашения: Кофемашина')).not.toHaveLength(0);
  });
});

describe('лимит запросов по договору в интерфейсе', () => {
  it('после исчерпания лимита вместо формы — экран с ожиданием, «Понятно» возвращает к форме', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    const equipmentPage = await api.get<{ items: { id: string }[] }>('/equipment');
    const catalog = await api.get<{ items: { id: string; name: string }[] }>('/providers', {
      withoutOrganization: true,
    });
    const providerId = catalog.items.find((p) => p.name === 'Сервис-Холод Плюс')!.id;
    for (let i = 0; i < 6; i += 1) {
      try {
        await api.post('/service-bindings/requests', {
          provider_organization_id: providerId,
          contract_number: `Л-${i}`,
          equipment_ids: [equipmentPage.items[0]!.id],
          basis: 'service_contract',
        });
      } catch (error) {
        if (error instanceof ApiError && error.isRateLimited) break;
        throw error;
      }
    }

    await openAddBindingScreen(user, /По номеру договора/);
    await pickProvider(user);
    await user.type(screen.getByLabelText('Номер договора'), 'Д-42');
    await user.click(screen.getAllByRole('checkbox')[0]!);
    await user.click(screen.getByRole('button', { name: 'Запросить подтверждение' }));

    await screen.findByText('Попробуйте через 15 минут');
    expect(screen.getByText('Можно отправить не больше 5 запросов за 15 минут.')).toBeInTheDocument();
    expect(screen.queryByText('Ждём подтверждения')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Понятно' }));
    expect(await screen.findByLabelText('Номер договора')).toHaveValue('Д-42');
  });
});

describe('«Клиенты» у исполнителя', () => {
  it('запрос по договору подтверждается из нижнего листа и уходит в подтверждённые', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('link', { name: 'Профиль' });
    window.location.hash = '#/bindings/incoming';
    await screen.findByRole('heading', { name: 'Клиенты' });

    const request = (await screen.findAllByRole('button', { name: /Договор Д-205/ }))[0]!;
    expect(within(request).getByText('Проверьте по своей CRM')).toBeInTheDocument();
    await user.click(request);
    const sheet = within(await screen.findByRole('dialog'));
    expect(sheet.getByText('Видно только заявленное — истории оборудования у вас пока нет')).toBeInTheDocument();
    await user.click(sheet.getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole('button', { name: /Договор Д-205/ })).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { name: 'Подтверждённые' })).toBeInTheDocument();
  });

  it('у истёкшего приглашения нет действия «Отозвать»', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    await screen.findByRole('link', { name: 'Профиль' });
    window.location.hash = '#/bindings/invitations';
    await screen.findByRole('heading', { name: 'Приглашения клиентов' });

    const expired = await screen.findByRole('button', { name: /Договор Д-301/ });
    expect(within(expired).getByText('Истекло')).toBeInTheDocument();
    await user.click(expired);
    expect(within(await screen.findByRole('dialog')).queryByRole('button', { name: 'Отозвать приглашение' })).toBeNull();
  });
});
