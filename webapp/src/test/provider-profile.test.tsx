import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { seedPendingPortfolioAttachment } from '../mocks/portfolio';
import { getAttachmentRecord } from '../mocks/requestsDb';
import { decideComplaintByOperator, listComplaintsForOperator } from '../mocks/reviews';
import { getActiveOrganizationId } from '../api/orgStore';
import { queryClient } from '../api/queryClient';
import { loginAsDemo, renderApp } from './testUtils';

describe('профиль исполнителя: заполнение, отправка, статусы', () => {
  it('администратор проходит регистрацию по шагам, видит ошибку по ИНН и отправляет на проверку', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });

    expect(
      await screen.findByText('До статуса «Допущен» заявки вашей компании не поступают.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Профиль не отправлен')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Заполнить профиль' }));
    await screen.findByText('Как вы работаете?');
    expect(screen.getByText('Шаг 1 из 3')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /Самостоятельный мастер/ }));
    await user.click(screen.getByRole('radio', { name: 'ИП' }));
    await user.click(screen.getByRole('button', { name: 'Далее' }));

    await user.type(await screen.findByLabelText('ИНН'), '1234567890');
    expect(
      screen.queryByText('Проверьте ИНН — контрольные цифры не сходятся'),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText('Проверьте ИНН — контрольные цифры не сходятся');

    await user.clear(screen.getByLabelText('ИНН'));
    await user.type(screen.getByLabelText('ИНН'), '7707083893');
    await user.click(screen.getByRole('checkbox', { name: 'Холодильное оборудование' }));
    await user.click(screen.getByRole('checkbox', { name: 'Обслуживаем этот город: Москва' }));
    await user.click(screen.getByRole('button', { name: 'Далее' }));

    await screen.findByText('Подтвердим, что вы представляете компанию');
    const patches: Record<string, unknown>[] = [];
    const onStart = ({ request }: { request: Request }) => {
      if (
        request.method === 'PATCH' &&
        new URL(request.url).pathname.endsWith('/provider-profile')
      ) {
        void request
          .clone()
          .json()
          .then((body: Record<string, unknown>) => patches.push(body));
      }
    };
    server.events.on('request:start', onStart);
    await user.type(screen.getByLabelText('Ваше имя'), 'Иван Механик');
    await user.type(screen.getByLabelText('Ваша должность'), 'Директор');
    await user.click(screen.getByRole('button', { name: 'Отправить на проверку' }));

    await screen.findByText('Проверяем профиль');
    server.events.removeListener('request:start', onStart);
    expect(patches.at(-1)).toMatchObject({
      contact_name: 'Иван Механик',
      representative_position: 'Директор',
      legal_form: 'ip',
    });
    await user.click(screen.getByRole('button', { name: 'Заполнить профиль' }));
    await screen.findByText('Профиль на проверке');
    expect(screen.queryByRole('button', { name: 'Заполнить профиль' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Изменить города и районы' }));
    const moscow = await screen.findByRole('checkbox', { name: 'Обслуживаем этот город: Москва' });
    if (moscow.getAttribute('aria-checked') === 'true') await user.click(moscow);
    await user.click(screen.getByRole('checkbox', { name: 'Обслуживаем этот город: Санкт-Петербург' }));
    const type = screen.getByRole('checkbox', { name: 'Холодильник для напитков' });
    const wasChecked = type.getAttribute('aria-checked') === 'true';
    await user.click(type);
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    await screen.findByText('Профиль на проверке');
    await user.click(screen.getByRole('link', { name: 'Изменить виды техники' }));
    expect(await screen.findByRole('checkbox', { name: 'Обслуживаем этот город: Санкт-Петербург' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Обслуживаем этот город: Москва' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Холодильник для напитков' }).getAttribute('aria-checked')).toBe(String(!wasChecked));

  });

  it('переключатель приёма заявок недоступен, пока профиль не допущен', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.getByRole('switch', { name: 'Принимаю новые заявки' })).toBeDisabled();
  });

  it('допущенный профиль можно переключить на приём заявок', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.getByRole('heading', { name: 'Сервис-Холод Плюс' })).toBeInTheDocument();

    const toggle = screen.getByRole('switch', { name: 'Принимаю новые заявки' });
    expect(toggle).not.toBeDisabled();
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await waitFor(() => {
      expect(screen.getByRole('switch', { name: 'Принимаю новые заявки' })).not.toBeChecked();
    });
  });

  it('ответ оператору — прямо из профиля «нужны уточнения»', async () => {
    let submitted: unknown = null;
    server.use(
      http.post('*/verification', async ({ request }) => {
        submitted = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_needs_info_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByText('Нужны уточнения');
    const send = screen.getByRole('button', { name: 'Отправить' });
    expect(send).toBeDisabled();
    await user.type(
      screen.getByLabelText('Ответ оператору'),
      'Удобно звонить в будни, 10:00–13:00',
    );
    await user.click(send);
    await screen.findByText('Сведения отправлены оператору');
    expect(submitted).toEqual({ note: 'Удобно звонить в будни, 10:00–13:00', attachment_refs: [] });
  });

  it('профиль «нужны сведения» ведёт на экран «Проверка», где можно донести сведения текстом', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_needs_info_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.getByText('Нужны уточнения')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Проверка и документы' }));
    await screen.findByRole('heading', { name: 'Проверка' });
    expect(await screen.findByText('Реквизиты компании')).toBeInTheDocument();
    expect(screen.getByText('Полномочия представителя')).toBeInTheDocument();
    expect(screen.getByText(/Подтверждено/)).toBeInTheDocument();
    expect(screen.getByText('Категории работ')).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText(
        'Опишите, что можете подтвердить: как связаться с представителем, ссылки на источники…',
      ),
      'Позвоните нашему директору по номеру с сайта компании',
    );
    await user.click(screen.getByRole('button', { name: 'Отправить сведения' }));
    await screen.findByText('Сведения отправлены оператору');
  });

  it('приостановленный и отклонённый профиль объясняют причину и путь обжалования, форма скрыта', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_suspended_admin');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(screen.getByText('Профиль приостановлен')).toBeInTheDocument();
    expect(screen.getByText(/Повторные обоснованные жалобы заказчиков/)).toBeInTheDocument();
    expect(screen.getByText('Текущие заявки и отзывы сохранены.')).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'Реквизиты и специализация' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Принимаю новые заявки' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: /^Обжаловать/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Обжаловать решение' });
    const send = within(dialog).getByRole('button', { name: 'Отправить обжалование' });
    expect(send).toBeDisabled();
    await user.type(within(dialog).getByLabelText('Основания'), 'Неявки были по вине заказчика');
    await user.click(send);
    expect(await screen.findByText('Обжалование на рассмотрении')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Обжаловать/ })).not.toBeInTheDocument();
  });

  it('повторное обжалование, пока первое открыто, — понятный текст 409, введённое остаётся', async () => {
    server.use(
      http.post('/app-api/v1/provider-profile/appeal', () =>
        HttpResponse.json(
          {
            error: {
              code: 'PROFILE_APPEAL_ALREADY_OPEN',
              message: 'Обжалование уже на рассмотрении',
              request_id: 'r1',
            },
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_suspended_admin');
    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('button', { name: /^Обжаловать/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Обжаловать решение' });
    await user.type(within(dialog).getByLabelText('Основания'), 'Повторно');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить обжалование' }));
    expect(
      await within(dialog).findByText(
        'Обжалование уже на рассмотрении — дождитесь решения оператора.',
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Основания')).toHaveValue('Повторно');
  });

  it('решение оператора по обжалованию видно в профиле с причиной', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_suspended_admin');
    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await user.click(await screen.findByRole('button', { name: /^Обжаловать/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Обжаловать решение' });
    await user.type(within(dialog).getByLabelText('Основания'), 'Жалобы урегулированы');
    await user.click(within(dialog).getByRole('button', { name: 'Отправить обжалование' }));
    await screen.findByText('Обжалование на рассмотрении');

    const orgId = getActiveOrganizationId();
    const [appeal] = listComplaintsForOperator('provider_profile', 'pending', 'appeal').filter(
      (c) => c.filerOrgId === orgId,
    );
    decideComplaintByOperator(appeal!.id, 'rejected', 'Нарушения повторяются');
    await queryClient.invalidateQueries({ queryKey: ['provider-profile'] });
    expect(await screen.findByText('Обжалование отклонено')).toBeInTheDocument();
    expect(screen.getByText(/Нарушения повторяются/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Обжаловать снова' })).toBeInTheDocument();
  });

  it('диспетчер не видит поля редактирования профиля и не может отправить его на проверку', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_dispatcher');

    await user.click(await screen.findByRole('link', { name: 'Профиль' }));
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(
      screen.queryByRole('link', { name: /Реквизиты и специализация/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Заполнить профиль' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('ИНН')).not.toBeInTheDocument();
  });
});

describe('портфолио: подписи к фото', () => {
  it('подпись сохраняется через PATCH /provider-profile/portfolio/{id}', async () => {
    const photo = seedPendingPortfolioAttachment();
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '/provider/profile/portfolio';

    const tiles = await screen.findAllByRole('button', { name: /^Открыть работу/ });
    await user.click(tiles[tiles.length - 1]!);
    const sheet = await screen.findByRole('dialog');
    const save = within(sheet).getByRole('button', { name: 'Сохранить подпись' });
    expect(save).toBeDisabled();
    await user.type(within(sheet).getByLabelText('Подпись к фото'), '  Замена компрессора ');
    await user.click(save);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    const saved = getAttachmentRecord(photo.id);
    expect(saved?.caption).toBe('Замена компрессора');
    expect(saved?.publication_state).toBe('pending');
  });
});
