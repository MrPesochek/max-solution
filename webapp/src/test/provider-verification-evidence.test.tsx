import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import { loginAsDemo, renderApp } from './testUtils';

describe('проверка исполнителя: документы-доказательства (ТЗ 6.5.2)', () => {
  it('администратор прикладывает документ, и его id уходит в attachment_refs вместе с заметкой', async () => {
    let submitted: { note?: string; attachment_refs?: string[] } | null = null;
    server.use(
      http.post('*/verification/attachments', () =>
        HttpResponse.json(
          {
            id: 'att_evidence_1',
            owner_kind: 'verification_case',
            request_id: null,
            message_id: null,
            slot: 'evidence',
            visibility_class: 'verification_evidence',
            processing_state: 'ready',
            publication_state: null,
            rejected_reason: null,
            mime_type: 'application/pdf',
            byte_size: 3,
            pixel_width: null,
            pixel_height: null,
            created_at: new Date().toISOString(),
          },
          { status: 201 },
        ),
      ),
      http.post('*/verification', async ({ request }) => {
        submitted = (await request.json()) as typeof submitted;
        return HttpResponse.json({ ok: true });
      }),
    );

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('provider_needs_info_admin');
    window.location.hash = '#/provider/verification';

    await screen.findByRole('heading', { name: 'Проверка' });
    const file = new File([new Uint8Array([1, 2, 3])], 'egrul.pdf', { type: 'application/pdf' });
    await user.upload(await screen.findByLabelText('Прикрепить документ'), file);
    await screen.findByText(/egrul\.pdf/);

    await user.type(
      screen.getByPlaceholderText(/Опишите, что можете подтвердить/),
      'Выписка ЕГРЮЛ приложена',
    );
    await user.click(screen.getByRole('button', { name: 'Отправить сведения' }));

    await screen.findByText('Сведения отправлены оператору');
    expect(submitted).toEqual({
      note: 'Выписка ЕГРЮЛ приложена',
      attachment_refs: ['att_evidence_1'],
    });
    expect(screen.queryByText(/egrul\.pdf/)).not.toBeInTheDocument();
  });

  it('без открытого дела загрузка документов недоступна', async () => {
    renderApp();
    await loginAsDemo('provider_active_admin');
    window.location.hash = '#/provider/verification';

    await screen.findByRole('heading', { name: 'Проверка' });
    expect(
      await screen.findByText('Документы можно приложить, когда открыто дело проверки'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Прикрепить документ' })).not.toBeInTheDocument();
  });
});
