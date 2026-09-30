import { cleanup, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import * as db from '../mocks/db';
import type { Attachment } from '../api/types';
import { api } from '../api/client';
import { loginAsDemo, renderApp } from './testUtils';

function stubEquipmentPhotos() {
  const store: Attachment[] = [];
  let counter = 0;
  server.use(
    http.post('*/equipment/:id/photos', () => {
      counter += 1;
      const attachment: Attachment = {
        id: `att_eq_${counter}`,
        owner_kind: 'equipment',
        request_id: null,
        message_id: null,
        slot: null,
        visibility_class: 'request_private',
        processing_state: 'ready',
        publication_state: null,
        rejected_reason: null,
        mime_type: 'image/png',
        byte_size: 4,
        pixel_width: null,
        pixel_height: null,
        created_at: new Date().toISOString(),
      };
      store.push(attachment);
      return HttpResponse.json(attachment, { status: 201 });
    }),
    http.get('*/equipment/:id/photos', () => HttpResponse.json(store)),
    http.get(
      '*/attachments/:id/content',
      () =>
        new HttpResponse(new Uint8Array([137, 80, 78, 71]), {
          headers: { 'Content-Type': 'image/png' },
        }),
    ),
  );
  return store;
}

describe('фото оборудования', () => {
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:equipment-photo');
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    cleanup();
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  });

  it('заказчик загружает фото на карточке оборудования и видит безопасную копию', async () => {
    const store = stubEquipmentPhotos();
    const item = db.listEquipment(db.demoSeed.demoCustomer.id).items[0]!;

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/equipment/${item.location_id}/${item.id}`;

    const title = `${item.brand} ${item.model}`;
    await screen.findByRole('heading', { name: new RegExp(title) });
    await user.click(screen.getByRole('tab', { name: 'Данные' }));
    await screen.findByRole('button', { name: 'Добавить фото: Общий вид' });
    expect(screen.getByRole('button', { name: 'Добавить фото: Шильдик' })).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();

    const file = new File([new Uint8Array([137, 80, 78, 71])], 'fridge.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Файл фото'), file);

    const photoName = new RegExp(`^Фото техники .*${title}, 1$`);
    await waitFor(() =>
      expect(screen.getByRole('img', { name: photoName })).toHaveAttribute('src', 'blob:equipment-photo'),
    );
    expect(store).toHaveLength(1);
  });

  it('плитка слота загружает фото с кодом слота шаблона (подпись на карточке — по slot)', async () => {
    stubEquipmentPhotos();
    const post = vi.spyOn(api, 'post');
    const item = db.listEquipment(db.demoSeed.demoCustomer.id).items[0]!;

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/equipment/${item.location_id}/${item.id}?tab=specs`;
    await user.click(await screen.findByRole('button', { name: 'Добавить фото: Шильдик' }));
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'plate.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Файл фото'), file);

    await waitFor(() => expect(post).toHaveBeenCalledWith(`/equipment/${item.id}/photos`, expect.any(FormData), expect.anything()));
    const form = post.mock.calls.find(([path]) => path === `/equipment/${item.id}/photos`)![1] as FormData;
    expect(form.get('slot')).toBe('nameplate');
    post.mockRestore();
  });

  it('фото, выбранные в форме новой техники, загружаются после её создания', async () => {
    const store = stubEquipmentPhotos();
    const locationId = db.demoSeed.demoLocation1.id;

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = `#/equipment/${locationId}/new`;

    await screen.findByRole('heading', { name: 'Новая техника' });
    const location = db.demoSeed.demoLocation1.name;
    expect(within(await screen.findByRole('radiogroup', { name: 'Точка' })).getByRole('radio', { name: location })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await user.click(screen.getByRole('radio', { name: 'Холодильное оборудование' }));
    await user.type(screen.getByLabelText('Бренд'), 'Liebherr');
    await user.type(screen.getByLabelText('Модель'), 'CN 4015');
    const file = new File([new Uint8Array([1, 2, 3])], 'plate.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Файл фото: Шильдик'), file);
    expect(screen.getByText('Фото добавлено')).toBeInTheDocument();
    expect(screen.getByText('Видят только вы и ваш сервис')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Убрать фото: Шильдик' }));
    expect(screen.queryByText('Фото добавлено')).not.toBeInTheDocument();
    await user.upload(screen.getByLabelText('Файл фото: Шильдик'), file);

    await user.click(screen.getByRole('button', { name: 'Добавить' }));
    await screen.findByText(/Liebherr CN 4015/);
    await waitFor(() => expect(store).toHaveLength(1));
  });
});
