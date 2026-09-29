import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { loginAsDemo, renderApp } from './testUtils';
import { demoLoginRaw } from './requestTestHelpers';
import { seedPendingPortfolioAttachment } from '../mocks/portfolio';

interface OperatorPage<T> {
  items: T[];
}

async function operatorApiCall<T>(
  path: string,
  auth: { token: string },
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const response = await fetch(`/operator-api/v1${path}`, {
    method: options.method ?? (options.body ? 'POST' : 'GET'),
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.token}`,
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok)
    throw new Error(
      `${options.method ?? 'GET'} ${path} -> ${response.status}: ${await response.text()}`,
    );
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

describe('оператор: очередь отзывов, жалоб и полномочий (ТЗ 8.3.5, 6.6.4, 14.1)', () => {
  it('отклонение отзыва без причины невозможно', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('operator');
    window.location.hash = '#/operator/reviews';

    await screen.findByRole('heading', { name: 'Отзывы на модерации' });
    await user.click(await screen.findByRole('button', { name: /Сервис-Холод Плюс/ }));
    await screen.findByText(/Мастер задержался/);

    await user.click(screen.getByRole('radio', { name: 'Отклонить' }));
    const submit = screen.getByRole('button', { name: 'Отправить решение' });
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByLabelText('Причина (обязательна для отклонения и удаления)'),
      'Похоже на накрутку конкурентом',
    );
    expect(submit).not.toBeDisabled();
    await user.click(submit);

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить' }));

    await waitFor(() => expect(screen.queryByText(/Мастер задержался/)).not.toBeInTheDocument());
  });

  it('пометка накрутки не скрывает отзыв — он остаётся опубликованным', async () => {
    const operatorAuth = await demoLoginRaw('operator');
    const published = await operatorApiCall<
      OperatorPage<{ id: string; provider_organization_id: string; text: string | null }>
    >('/reviews?status=published', operatorAuth);
    const review = published.items.find((r) => r.text?.includes('Приехали в тот же день'));
    expect(review).toBeTruthy();

    await operatorApiCall(`/reviews/${review!.id}/fraud`, operatorAuth, {
      method: 'POST',
      body: { suspected: true, reason: 'Один и тот же IP, что и ещё три отзыва' },
    });

    const afterFlag = await operatorApiCall<{ items: { id: string; suspected_fraud: boolean }[] }>(
      '/reviews?status=published',
      operatorAuth,
    );
    expect(afterFlag.items.find((r) => r.id === review!.id)?.suspected_fraud).toBe(true);

    const publicReviews = await (
      await fetch(`/app-api/v1/providers/${review!.provider_organization_id}/reviews`, {
        headers: { Authorization: `Bearer ${operatorAuth.token}` },
      })
    ).json();
    expect((publicReviews.items as { id: string }[]).some((r) => r.id === review!.id)).toBe(true);
  });

  it('выдача гарантийного полномочия без источника проверки невозможна', async () => {
    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('operator');
    window.location.hash = '#/operator/warranty';

    await screen.findByRole('heading', { name: 'Гарантийные полномочия' });
    await user.click(screen.getByRole('button', { name: 'Выдать полномочие' }));

    await user.type(screen.getByLabelText('Исполнитель (id организации)'), 'org_demo_provider');
    await user.type(
      screen.getByLabelText('Основание выдачи (обязательно)'),
      'Официальное письмо производителя',
    );
    const submit = screen.getByRole('button', { name: 'Выдать' });
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByLabelText('Источник проверки (обязательно)'),
      'Письмо на фирменном бланке, сверено с сайтом',
    );
    expect(submit).not.toBeDisabled();
  });

  it('решение по изображению на модерации требует причины при отклонении', async () => {
    const attachment = seedPendingPortfolioAttachment();

    const user = userEvent.setup();
    renderApp();
    await loginAsDemo('operator');
    window.location.hash = '#/operator/attachments';

    await screen.findByRole('heading', { name: 'Изображения на модерации' });
    await screen.findByText(new RegExp(attachment.mime_type.replace('/', '\\/')));

    await user.click(screen.getByRole('button', { name: 'Отклонить' }));
    const sheet = within(await screen.findByRole('dialog'));
    expect(sheet.getByRole('button', { name: 'Отклонить' })).toBeDisabled();

    await user.type(
      sheet.getByLabelText('Причина отклонения (обязательно)'),
      'Виден шильдик с серийным номером',
    );
    await user.click(sheet.getByRole('button', { name: 'Отклонить' }));

    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: 'Изображения на модерации' }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText(new RegExp(attachment.mime_type.replace('/', '\\/'))),
    ).not.toBeInTheDocument();
  });
});
