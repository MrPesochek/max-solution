import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../mocks/server';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { stubAttachmentUploads } from './requestTestHelpers';
import { startRequestForBosch } from './requestWizardHelpers';

describe('мастер новой заявки своему сервису', () => {
  it('показывает сервис у техники, пропускает необязательное фото и отправляет заявку сервису', async () => {
    const uploadStub = stubAttachmentUploads();
    uploadStub.slotOrder.push('overview', 'nameplate');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();

    await user.click(screen.getByRole('button', { name: 'Новая заявка' }));
    const bosch = await screen.findByRole('radio', { name: /Bosch/ });
    expect(bosch).toHaveTextContent('Кафе на Тверской · Гарантия: Bosch');
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled();
    await user.click(bosch);
    const own = await screen.findByRole('radio', { name: /^Сервис-Холод Плюс/ });
    expect(own).toHaveTextContent('Ваш гарантийный сервис · напрямую');
    expect(own).toHaveAttribute('aria-checked', 'true');
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText('Шаг 2 из 3');

    expect(screen.getByRole('heading', { name: 'Что случилось?' })).toHaveFocus();
    expect(screen.getByRole('button', { name: /^Изменить технику: Холодильник Bosch/ })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Не срочно' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/^Черновик сохранён · \d\d:\d\d$/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    expect(
      await screen.findByText('Опишите, что случилось: выберите признак или напишите пару слов.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Подробнее')).toHaveFocus();
    expect(screen.getByText('Шаг 2 из 3')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Не держит холод' }));
    await user.type(screen.getByLabelText('Подробнее'), 'Гудит компрессор');

    expect(screen.getByText('Экран / код ошибки')).toBeInTheDocument();
    const fileInput = screen.getByTestId('wizard-photo-input');

    await user.click(screen.getByRole('button', { name: 'Добавить фото: Общий вид' }));
    await user.upload(fileInput, new File(['overview'], 'overview.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Общий вид, фото 1: заменить или удалить' });

    await user.click(screen.getByRole('button', { name: 'Добавить фото: Шильдик' }));
    await user.upload(fileInput, new File(['nameplate'], 'nameplate.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Шильдик, фото 1: заменить или удалить' });

    await user.click(screen.getByRole('button', { name: 'Далее' }));

    await screen.findByText('Шаг 3 из 3');
    expect(screen.getByRole('heading', { name: 'Всё верно?' })).toHaveFocus();
    expect(screen.queryByText('Не хватает обязательных фото')).not.toBeInTheDocument();
    expect(screen.getByText('Сервис-Холод Плюс, гарантийный сервис')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Фото: 2 из 3/ })).toBeInTheDocument();
    expect(screen.getByText('Не держит холод. Гудит компрессор')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Заявку увидят только сотрудники сервиса Сервис-Холод Плюс. Если сервис не ответит, предложим найти другого исполнителя.',
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));

    await screen.findByRole('heading', { name: 'Заявка отправлена' });
    expect(screen.getByText(/^Р-\d+ · Сервис-Холод Плюс\. Статус пришлём в чат MAX\.$/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Открыть заявку' }));
    await waitFor(() => expect(screen.getByText('Ждём ответа сервиса')).toBeInTheDocument());
  });

  it('срочную заявку можно отправить без фото, указав причину', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');

    await user.type(screen.getByLabelText('Подробнее'), 'Полностью не включается, холод стоит');
    await user.click(screen.getByRole('radio', { name: 'Сегодня' }));
    await user.click(screen.getByRole('button', { name: 'Не могу сделать фото' }));
    await screen.findByRole('heading', { name: 'Почему нет фото?' });
    const next = screen.getByRole('button', { name: 'Далее' });
    await user.click(next);
    expect(await screen.findByText('Выберите причину — мастер увидит её в заявке.')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Нет времени, срочно' }));
    await user.click(next);

    await screen.findByText('Шаг 3 из 3');
    expect(screen.getByRole('heading', { name: 'Всё верно?' })).toBeInTheDocument();
    expect(screen.getByText('Полностью не включается, холод стоит')).toBeInTheDocument();
    expect(screen.getAllByText(/Нет времени, срочно/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));

    await screen.findByRole('heading', { name: 'Заявка отправлена' });
    await user.click(screen.getByRole('button', { name: 'Открыть заявку' }));
    await waitFor(() => expect(screen.getByText('Ждём ответа сервиса')).toBeInTheDocument());
    expect(screen.getByText('Отправлено с неполными фото')).toBeInTheDocument();
  });

  it('обычную заявку без обязательных фото и без причины не отправить', async () => {
    server.use(http.patch('*/requests/:id', async ({ request }) => {
      const body = await request.clone().json() as { photos_incomplete?: boolean; photos_incomplete_reason?: string | null };
      expect(body.photos_incomplete && !body.photos_incomplete_reason).not.toBe(true);
    }));
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');

    await user.click(screen.getByRole('button', { name: 'Шумит' }));
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText('Шаг 3 из 3');

    expect(screen.getByText('Не хватает обязательных фото')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отправить заявку' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /^Фото: 0 из 3/ }));
    await screen.findByText('Шаг 2 из 3');
    expect(screen.getByRole('button', { name: 'Шумит' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('файл больше 10 МБ не загружается — слот показывает ошибку, остальное сохраняется', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');

    await user.click(screen.getByRole('button', { name: 'Добавить фото: Шильдик' }));
    const big = new File([new Uint8Array(11 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' });
    await user.upload(screen.getByTestId('wizard-photo-input'), big);

    expect(
      await screen.findByText(
        'Шильдик: файл больше 10 МБ. Снимите заново или выберите другой — остальное сохранено.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Шильдик · 11 МБ')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать другое фото: Шильдик' })).toBeInTheDocument();
  });

  it('без сети при отправке показывает «Нет соединения» и повторяет отправку тем же ключом', async () => {
    const uploadStub = stubAttachmentUploads();
    uploadStub.slotOrder.push('overview', 'nameplate');
    const keys: (string | null)[] = [];
    let failNext = true;
    server.use(
      http.post('*/requests/:id/actions/submit-to-own-service', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        if (failNext) {
          failNext = false;
          return HttpResponse.error();
        }
        return undefined;
      }),
    );

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    await findHomeScreen();
    await startRequestForBosch(user, 'Мой сервис');
    await user.type(screen.getByLabelText('Подробнее'), 'Не охлаждает');
    const fileInput = screen.getByTestId('wizard-photo-input');
    await user.click(screen.getByRole('button', { name: 'Добавить фото: Общий вид' }));
    await user.upload(fileInput, new File(['overview'], 'overview.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Общий вид, фото 1: заменить или удалить' });
    await user.click(screen.getByRole('button', { name: 'Добавить фото: Шильдик' }));
    await user.upload(fileInput, new File(['nameplate'], 'nameplate.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Шильдик, фото 1: заменить или удалить' });
    await user.click(screen.getByRole('button', { name: 'Далее' }));
    await screen.findByText('Шаг 3 из 3');

    await user.click(screen.getByRole('button', { name: 'Отправить заявку' }));
    await screen.findByRole('heading', { name: 'Нет соединения' });
    expect(screen.getByText(/^Заявка не отправлена\. Черновик сохранён на сервере в \d\d:\d\d\./)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Повторить отправку' }));
    await screen.findByRole('heading', { name: 'Заявка отправлена' });
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });
});
