import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp, findHomeScreen } from './testUtils';
import { apiCall, demoLoginRaw, stubAttachmentUploads } from './requestTestHelpers';
import { startRequestForBosch } from './requestWizardHelpers';

const SYMPTOM_TEXT = 'Не морозит, посторонний шум в компрессоре';

describe('внешняя заявка: сотрудник готовит → согласование → менеджер публикует', () => {
  it('сотрудник отправляет черновик внешнего поиска на согласование руководителю', async () => {
    const uploadStub = stubAttachmentUploads();
    uploadStub.slotOrder.push('overview', 'nameplate');

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_employee');

    await findHomeScreen();
    await startRequestForBosch(user, 'Найти исполнителя');

    await user.type(screen.getByLabelText('Подробнее'), SYMPTOM_TEXT);
    const fileInput = screen.getByTestId('wizard-photo-input');
    await user.click(screen.getByRole('button', { name: 'Добавить фото: Общий вид' }));
    await user.upload(fileInput, new File(['overview'], 'overview.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Общий вид, фото 1: заменить или удалить' });
    await user.click(screen.getByRole('button', { name: 'Добавить фото: Шильдик' }));
    await user.upload(fileInput, new File(['nameplate'], 'nameplate.jpg', { type: 'image/jpeg' }));
    await screen.findByRole('button', { name: 'Шильдик, фото 1: заменить или удалить' });
    await user.click(screen.getByRole('button', { name: 'Далее' }));

    await screen.findByText('Шаг 3 из 3');
    expect(screen.getByText('Найти исполнителя, опубликует руководитель')).toBeInTheDocument();
    expect(screen.getByText('Опубликует руководитель')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отправить руководителю' }));

    await screen.findByRole('heading', { name: 'Заявка отправлена руководителю' });
    await user.click(screen.getByRole('button', { name: 'Открыть заявку' }));

    await waitFor(() => expect(screen.getByText('Ждёт решения руководителя')).toBeInTheDocument());
    expect(
      screen.getByText('Согласование и отмена — действия руководителя. Вы можете следить за статусом и перепиской.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Проверить и опубликовать' })).not.toBeInTheDocument();
  });

  it('руководитель видит черновик в «Ожидают согласования» и публикует внешний поиск', async () => {
    const employee = await demoLoginRaw('customer_employee');
    const equipment = await apiCall<{ items: { id: string; brand: string }[] }>('/equipment', employee);
    const draft = await apiCall<{ id: string }>('/requests', employee, {
      body: {
        equipment_id: equipment.items.find((e) => e.brand === 'Bosch')!.id,
        route: 'marketplace',
        urgency: 'normal',
        symptom_description: SYMPTOM_TEXT,
      },
    });
    await apiCall(`/requests/${draft.id}/actions/request-approval`, employee, { body: {} });
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');

    await findHomeScreen();
    await screen.findByText('Проверьте и опубликуйте');
    await user.click(screen.getByText('Проверьте и опубликуйте'));

    await waitFor(() => expect(screen.getByText('Нужно ваше решение')).toBeInTheDocument());
    expect(screen.getByText(SYMPTOM_TEXT)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Проверить и опубликовать' }));

    await screen.findByText('У этой техники есть сервис');
    await user.click(screen.getByRole('button', { name: 'Всё равно искать' }));

    await screen.findByRole('heading', { name: 'Что увидят исполнители' });
    await waitFor(() => expect(screen.getByText(/Подходящих исполнителей/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Опубликовать' }));

    await waitFor(() => expect(screen.getByText('Ищем исполнителя')).toBeInTheDocument());
  });
});
