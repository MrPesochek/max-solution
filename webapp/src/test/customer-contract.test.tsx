import { cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import type {
  Equipment,
  Page,
  RequestCustomer,
  RequestListItem,
  RequestMessage,
  ServiceBinding,
} from '../api/types';
import { findHomeScreen, loginAsDemo, renderApp } from './testUtils';
import { apiCall, demoLoginRaw } from './requestTestHelpers';

type Auth = { token: string; organizationId: string };

afterEach(() => cleanup());

function capturePaths(): string[] {
  const paths: string[] = [];
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    paths.push(`${request.method} ${url.pathname.replace('/app-api/v1', '')}${url.search}`);
  });
  return paths;
}

async function boschId(auth: Auth): Promise<string> {
  const eq = await apiCall<Page<Equipment>>('/equipment', auth);
  return eq.items.find((e) => e.brand === 'Bosch')!.id;
}

async function ownServiceRequest(): Promise<{ manager: Auth; request: RequestCustomer }> {
  const manager = await demoLoginRaw('customer_manager');
  const draft = await apiCall<RequestCustomer>('/requests', manager, {
    body: { equipment_id: await boschId(manager), route: 'own_service', urgency: 'normal' },
  });
  const request = await apiCall<RequestCustomer>(`/requests/${draft.id}/actions/submit-to-own-service`, manager, {
    body: { photos_incomplete: true, photos_incomplete_reason: 'Фото не требуются для теста' },
  });
  return { manager, request };
}

function todayAt(hours: number, minutes: number): string {
  const date = new Date();
  date.setHours(hours, minutes, 0, 0);
  return date.toISOString();
}

describe('главная (10a): счётчик исполнителей и сводка техники', () => {
  it('«Исполнителей в вашем районе» — из /providers/count по городу и району точки', async () => {
    const paths = capturePaths();
    server.use(http.get('*/providers/count', () => HttpResponse.json({ count: 14 })));
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    await user.click(screen.getByRole('tab', { name: 'Найти исполнителя' }));

    expect(await screen.findByText('Исполнителей в вашем районе')).toBeInTheDocument();
    expect(screen.getByText('14')).toBeInTheDocument();
    const counted = paths.find((p) => p.startsWith('GET /providers/count'));
    expect(counted).toContain('city_id=');
    expect(paths.some((p) => /^GET \/providers(\?|$)/.test(p))).toBe(false);

  });

  it('ноль исполнителей — строки со счётчиком нет (ТЗ S5)', async () => {
    let answered = false;
    server.use(
      http.get('*/providers/count', () => {
        answered = true;
        return HttpResponse.json({ count: 0 });
      }),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    await user.click(screen.getByRole('tab', { name: 'Найти исполнителя' }));
    await waitFor(() => expect(answered).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText('Исполнителей в вашем районе')).not.toBeInTheDocument();
    expect(await screen.findByText('В районе точки пока нет исполнителей')).toBeInTheDocument();
    expect(screen.queryByText(/пришлют время и цену/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Описать проблему/ })).not.toBeInTheDocument();
  });

  it('строка техники — из сводки EquipmentView: заявка в работе и сервис по договору, без /service-bindings', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const real = await apiCall<Page<Equipment>>('/equipment', manager);
    const [first, second] = real.items;
    const summary: Equipment[] = [
      {
        ...first!,
        category_code: 'commercial_display_fridge',
        category_name: 'Холодильная витрина',
        brand: 'Carboma',
        model: 'F16',
        active_request: { id: 'req_x', request_number: 412, status: 'scheduled' },
        binding: null,
      },
      {
        ...second!,
        location_id: first!.location_id,
        category_code: 'refrigerator_cabinet',
        category_name: 'Холодильный шкаф',
        brand: 'Polair',
        model: 'ШХ-0,7',
        active_request: null,
        binding: {
          id: 'sb_x',
          status: 'confirmed',
          basis: 'service_contract',
          is_contact_only: false,
          provider_name: 'ХолодСервис',
          valid_until: '2026-12-31',
          guarantor_kind: null,
          guarantor_name: null,
          provider_has_crm: true,
          guarantor_stated_by_provider: false,
        },
      },
    ];
    server.use(http.get('*/equipment', () => HttpResponse.json({ items: summary, next_cursor: null })));
    const paths = capturePaths();

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    expect(await screen.findByText('Выезд согласован · Р-412')).toBeInTheDocument();
    expect(screen.getByText('ХолодСервис · договор до 31 дек 2026')).toBeInTheDocument();
    expect(paths.some((p) => p.startsWith('GET /service-bindings'))).toBe(false);
  });

  it('«со слов сервиса» в строке техники — по guarantor_stated_by_provider из сводки', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const real = await apiCall<Page<Equipment>>('/equipment', manager);
    const [first, second] = real.items;
    const warrantyBinding = (stated: boolean, id: string): Equipment['binding'] => ({
      id,
      status: 'confirmed',
      basis: 'warranty',
      is_contact_only: false,
      provider_name: 'ХолодСервис',
      valid_until: null,
      guarantor_kind: 'manufacturer',
      guarantor_name: stated ? 'Bosch' : 'Polair',
      provider_has_crm: false,
      guarantor_stated_by_provider: stated,
      warranty_authorization_id: stated ? null : 'wa_1',
    });
    const summary: Equipment[] = [
      { ...first!, active_request: null, binding: warrantyBinding(true, 'sb_stated') },
      { ...second!, location_id: first!.location_id, active_request: null, binding: warrantyBinding(false, 'sb_verified') },
    ];
    server.use(http.get('*/equipment', () => HttpResponse.json({ items: summary, next_cursor: null })));

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    expect(await screen.findByText('Гарантия: Bosch (со слов сервиса)')).toBeInTheDocument();
    expect(screen.getByText('Гарантия: Polair')).toBeInTheDocument();
  });
});

describe('«Мои заявки» (13a): поля строки списка (K-03)', () => {
  it('окно выезда, «Мастер едет», непрочитанные и «Выполнено · ★ 5»', async () => {
    const { manager } = await ownServiceRequest();
    const list = await apiCall<Page<RequestListItem>>('/requests?active=true', manager);
    const base = list.items[0]!;
    const items: RequestListItem[] = [
      {
        ...base,
        id: 'req_en_route',
        status: 'scheduled',
        visit_window_start: todayAt(14, 30),
        visit_window_end: todayAt(16, 0),
        timezone: null,
        en_route_at: todayAt(14, 2),
        unread_messages_count: 3,
      },
      {
        ...base,
        id: 'req_scheduled',
        status: 'scheduled',
        equipment_brand: 'Polair',
        visit_window_start: todayAt(10, 0),
        visit_window_end: todayAt(12, 0),
        timezone: null,
        en_route_at: null,
        unread_messages_count: 0,
      },
      {
        ...base,
        id: 'req_closed',
        status: 'closed',
        equipment_brand: 'Frostor',
        my_review_rating: 5,
        closed_at: '2026-09-12T10:00:00Z',
      },
    ];
    server.use(
      http.get('*/requests', ({ request }) => {
        const active = new URL(request.url).searchParams.get('active');
        const done = items.filter((i) => i.status === 'closed');
        const open = items.filter((i) => i.status !== 'closed');
        return HttpResponse.json({ items: active === 'false' ? done : open, next_cursor: null });
      }),
    );

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await user.click(screen.getByRole('link', { name: 'Заявки' }));
    await screen.findByRole('heading', { name: 'Заявки' });

    expect(await screen.findByText('Мастер едет · 14:30')).toBeInTheDocument();
    expect(screen.getByText('Выезд согласован · 10:00')).toBeInTheDocument();
    const enRoute = screen.getByText('Мастер едет · 14:30').closest('a')!;
    expect(enRoute).toHaveAccessibleName(/Непрочитанных сообщений: 3/);
    expect(within(enRoute).getByText('3')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Завершённые' }));
    expect(await screen.findByText('Выполнено · ★ 5')).toBeInTheDocument();
    expect(screen.getByText('12 сент')).toBeInTheDocument();
  });
});

describe('карточка заявки (9a, 15d, 13c): поля назначения и переписки', () => {
  it('«Мастер едет» по en_route_at и рейтинг исполнителя из Assignment.provider', async () => {
    const { request } = await ownServiceRequest();
    const card: RequestCustomer = {
      ...request,
      status: 'scheduled',
      assignment: {
        ...request.assignment!,
        state: 'accepted',
        en_route_at: todayAt(14, 2),
        provider: {
          id: request.assignment!.provider_organization_id,
          display_name: request.assignment!.provider_display_name ?? 'Сервис',
          verification_marks: [],
          rating: 4.9,
          rating_label: null,
          reviews_count: 64,
          unique_reviewer_orgs_count: 9,
        },
      },
    };
    server.use(http.get(`*/requests/${request.id}`, () => HttpResponse.json(card)));

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${request.id}`;
    expect(await screen.findByRole('heading', { name: 'Мастер едет' })).toBeInTheDocument();
    expect(screen.getByText(/отметил выезд в 14:02/)).toBeInTheDocument();
    expect(screen.getByText(/★ 4,9 \(64 отзыва\)/)).toBeInTheDocument();
  });

  it('«Подождать» — время напоминания сервису из Assignment.reminder_at', async () => {
    const { request } = await ownServiceRequest();
    const card: RequestCustomer = {
      ...request,
      submitted_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
      assignment: { ...request.assignment!, reminder_at: todayAt(18, 45) },
    };
    server.use(http.get(`*/requests/${request.id}`, () => HttpResponse.json(card)));

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${request.id}`;
    await user.click(await screen.findByRole('button', { name: 'Подождать' }));
    expect(await screen.findByText('Напомним вам в 18:45, если сервис не ответит')).toBeInTheDocument();
  });

  it('в переписке — имена авторов, подпись CRM и «Доставлено в CRM»', async () => {
    const { request } = await ownServiceRequest();
    const at = (minutes: number) => new Date(Date.now() - (60 - minutes) * 60_000).toISOString();
    const message = (id: string, extra: Partial<RequestMessage>): RequestMessage => ({
      id,
      request_id: request.id,
      author_kind: 'provider_membership',
      author_membership_id: null,
      thread_provider_id: null,
      body: '',
      created_at: at(0),
      author_display_name: null,
      author_organization_name: null,
      author_label: null,
      delivery: null,
      ...extra,
    });
    const messages: RequestMessage[] = [
      message('msg_1', {
        body: 'Выехал, буду к 14:40',
        created_at: at(1),
        author_display_name: 'Олег Рябов',
        author_organization_name: 'Сервис-Холод Плюс',
      }),
      message('msg_2', {
        author_kind: 'integration_client',
        body: 'Пришлите фото шильдика',
        created_at: at(2),
        author_display_name: 'CRM Сервис-Холод Плюс',
        author_organization_name: 'Сервис-Холод Плюс',
        author_label: 'Ольга, диспетчер',
      }),
      message('msg_3', {
        author_kind: 'customer_membership',
        body: 'Вход со двора',
        created_at: at(3),
        delivery: { state: 'delivered', channel: 'crm', delivered_at: at(3), last_attempt_at: at(3), next_attempt_at: null },
      }),
    ];
    server.use(http.get(`*/requests/${request.id}/messages`, () => HttpResponse.json({ items: messages, next_cursor: null })));

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/${request.id}/messages`;
    expect(await screen.findByText('Олег Рябов')).toBeInTheDocument();
    expect(screen.getByText('Ольга, диспетчер · Сервис-Холод Плюс · CRM')).toBeInTheDocument();
    expect(screen.getByText(/· Доставлено в CRM$/)).toBeInTheDocument();
  });
});

describe('карточка техники (13b): история по equipment_id (K-04)', () => {
  it('история запрашивается с фильтром техники и догружается по курсору', async () => {
    const { manager, request } = await ownServiceRequest();
    const eq = await apiCall<Page<Equipment>>('/equipment', manager);
    const bosch = eq.items.find((e) => e.brand === 'Bosch')!;
    const list = await apiCall<Page<RequestListItem>>(`/requests?equipment_id=${bosch.id}`, manager);
    const older: RequestListItem = {
      ...list.items[0]!,
      id: 'req_older',
      request_number: 7,
      symptom_description: 'Шумит вентилятор',
      created_at: '2026-06-14T10:00:00Z',
    };
    const paths = capturePaths();
    server.use(
      http.get('*/requests', ({ request: http }) => {
        const url = new URL(http.url);
        if (url.searchParams.get('equipment_id') !== bosch.id) return undefined;
        return url.searchParams.get('cursor')
          ? HttpResponse.json({ items: [older], next_cursor: null })
          : HttpResponse.json({ items: list.items, next_cursor: 'page2' });
      }),
    );

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${bosch.location_id}/${bosch.id}?tab=history`;
    const history = within(await screen.findByRole('list', { name: 'История' }));
    expect(await history.findByRole('link', { name: new RegExp(`^Р-${request.request_number}:`) })).toBeInTheDocument();
    expect(paths.some((p) => p.startsWith('GET /requests?') && p.includes(`equipment_id=${bosch.id}`))).toBe(true);
    expect(paths.some((p) => p.startsWith('GET /requests?') && p.includes('location_id='))).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Показать ещё' }));
    expect(await screen.findByRole('link', { name: 'Р-7: Шумит вентилятор' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: new RegExp(`^Р-${request.request_number}:`) })).toBeInTheDocument();
  });
});

describe('мастер заявки (15a): техника из адреса', () => {
  it('/requests/new?equipment=<id> — техника уже выбрана, «Далее» доступно', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const eq = await apiCall<Page<Equipment>>('/equipment', manager);
    const saeco = eq.items.find((e) => e.brand === 'Saeco')!;

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/requests/new?equipment=${saeco.id}`;
    const group = within(await screen.findByRole('radiogroup', { name: 'Техника' }));
    const checked = group.getAllByRole('radio').filter((r) => r.getAttribute('aria-checked') === 'true');
    expect(checked).toHaveLength(1);
    expect(checked[0]).toHaveAccessibleName(/Saeco/);
    expect(screen.getByRole('button', { name: 'Далее' })).toBeEnabled();
    expect(screen.getByText('Мой контакт: Мастер Николай (частный)')).toBeInTheDocument();
    expect(screen.getByText('Заявку через приложение не доставить — позвоните: +7 900 111-22-33')).toBeInTheDocument();
  });
});

describe('нет доступа (16e): «Запросить доступ» (K-21)', () => {
  it('сотрудник отправляет запрос без заявки и точки; ответ одинаковый', async () => {
    const bodies: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && request.url.endsWith('/memberships/me/access-requests')) {
        void request.clone().json().then((body: unknown) => bodies.push(body));
      }
    });
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');
    await findHomeScreen();
    window.location.hash = '#/requests/req_unknown_000';
    await screen.findByText('Заявка недоступна');
    expect(screen.getByText(/нет доступа к её точке/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Запросить доступ' }));
    expect(await screen.findByRole('button', { name: 'Запрос отправлен' })).toBeDisabled();
    await waitFor(() => expect(bodies).toEqual([{}]));
    expect(screen.getByRole('button', { name: 'К моим заявкам' })).toHaveAttribute('href', expect.stringContaining('/requests'));
  });

  it('руководителю кнопки нет — он и так видит все точки', async () => {
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = '#/requests/req_unknown_000';
    await screen.findByText('Заявка недоступна');
    expect(screen.queryByRole('button', { name: 'Запросить доступ' })).not.toBeInTheDocument();
  });
});

describe('гарантия техники (K-13): гарант со слов сервиса', () => {
  it('guarantor_stated_by_provider — рядом с гарантом «со слов сервиса»', async () => {
    const manager = await demoLoginRaw('customer_manager');
    const eq = await apiCall<Page<Equipment>>('/equipment', manager);
    const bosch = eq.items.find((e) => e.brand === 'Bosch')!;
    const bindings = await apiCall<Page<ServiceBinding>>(`/service-bindings?equipment_id=${bosch.id}`, manager);
    const binding: ServiceBinding = {
      ...bindings.items.find((b) => !b.is_contact_only)!,
      status: 'confirmed',
      basis: 'warranty',
      guarantor_kind: 'manufacturer',
      guarantor_name: 'Bosch',
      warranty_authorization: null,
      guarantor_stated_by_provider: true,
    };
    server.use(http.get('*/service-bindings', () => HttpResponse.json({ items: [binding], next_cursor: null })));

    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    window.location.hash = `#/equipment/${bosch.location_id}/${bosch.id}/warranty`;
    await screen.findByRole('heading', { name: 'Гарантия' });
    expect(await screen.findByText('Bosch')).toBeInTheDocument();
    expect(screen.getByText('со слов сервиса')).toBeInTheDocument();
  });
});
