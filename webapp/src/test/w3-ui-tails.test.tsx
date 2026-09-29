import type { ReactNode } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { queryClient } from '../api/queryClient';
import type { PublicReview, RequestProvider } from '../api/types';
import { RequestPhotos } from '../screens/provider/request-detail/RequestPhotos';
import { ReportPhotoSlots } from '../screens/provider/request-detail/ReportPhotoSlots';
import { ReviewItem } from '../screens/reviews/ReviewFeed';
import { Segmented } from '../ui/Segmented';
import { loginAsDemo, renderApp } from './testUtils';

function withQuery(node: ReactNode) {
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}

function providerRequest(attachments: Array<{ id: string; slot: string | null; state: string }>): RequestProvider {
  return {
    id: 'req_tail',
    request_number: 77,
    attachments: attachments.map((a) => ({
      id: a.id,
      slot: a.slot,
      message_id: null,
      processing_state: a.state,
    })),
  } as unknown as RequestProvider;
}

describe('отклонённое фото можно заменить', () => {
  it('RequestPhotos: плитка «Отклонено» открывает выбор файла, пока дозагрузка открыта', async () => {
    const user = userEvent.setup();
    withQuery(<RequestPhotos request={providerRequest([{ id: 'att_bad', slot: null, state: 'rejected' }])} canUpload />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, 'click');
    await user.click(screen.getByRole('button', { name: 'Фото к заявке №77, 1: отклонено, заменить' }));
    expect(click).toHaveBeenCalled();
  });

  it('RequestPhotos: без права дозагрузки отклонённое фото — просто статус', () => {
    withQuery(
      <RequestPhotos request={providerRequest([{ id: 'att_bad', slot: null, state: 'rejected' }])} canUpload={false} />,
    );
    expect(screen.queryByRole('button', { name: /заменить/ })).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Фото к заявке №77, 1. Отклонено' })).toBeInTheDocument();
  });

  it('ReportPhotoSlots: замена уходит в слот отклонённого фото', async () => {
    const user = userEvent.setup();
    withQuery(<ReportPhotoSlots request={providerRequest([{ id: 'att_before', slot: 'before', state: 'rejected' }])} />);
    const replace = screen.getByRole('button', { name: /отклонено, заменить$/ });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, 'click');
    await user.click(replace);
    expect(click).toHaveBeenCalled();
    expect(input).toHaveAttribute('aria-label', expect.stringContaining('До'));
  });
});

describe('мелкие правки доступности', () => {
  it('счётчик сегмента — «N+», когда загружена не вся очередь', () => {
    render(
      <Segmented
        label="Очереди"
        items={[
          { id: 'a', label: 'Входящие', count: 50, countMore: true },
          { id: 'b', label: 'В работе', count: 3 },
        ]}
        value="b"
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole('radio', { name: /Входящие/ })).toHaveTextContent('50+');
    expect(screen.getByRole('radio', { name: /В работе/ })).toHaveTextContent(/3$/);
  });

  it('ответ компании на отзыв — обычный пузырь, не «своё сообщение»', () => {
    const review = {
      id: 'rev_1',
      rating: 5,
      text: 'Быстро',
      author_display_name: 'Кафе',
      published_at: '2026-09-01T10:00:00Z',
      photo_attachment_ids: [],
      reply: { body: 'Спасибо!', created_at: '2026-09-02T10:00:00Z' },
    } as unknown as PublicReview;
    const { container } = withQuery(<ReviewItem review={review} />);
    expect(screen.getByText('Спасибо!')).toBeInTheDocument();
    expect(container.querySelector('.ui-message--me')).toBeNull();
  });

  it('профили исполнителей у оператора: вкладки с tabpanel, строки открывают лист (aria-haspopup)', async () => {
    renderApp();
    await loginAsDemo('operator');
    window.location.hash = '#/operator/providers';
    const tab = await screen.findByRole('tab', { name: 'Профили' });
    const panel = await screen.findByRole('tabpanel');
    expect(tab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', tab.id);
    const rows = within(panel).queryAllByRole('button');
    for (const row of rows) {
      expect(row).not.toHaveAttribute('aria-expanded');
    }
    if (rows.length > 0) expect(rows.some((row) => row.getAttribute('aria-haspopup') === 'dialog')).toBe(true);
  });
});
