import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { server } from '../mocks/server';
import { strings } from '../strings/ru';
import { urgencyLabel } from '../lib/status';
import { copyText } from '../lib/clipboard';
import type { Equipment, EquipmentBindingSummary } from '../api/types';
import { bindingSummary } from '../screens/requests/components/equipmentService';
import { equipmentFullName, equipmentTitle, listItemEquipmentName } from '../screens/requests/components/equipmentName';
import { equipmentLine } from '../screens/equipment/equipmentView';
import { listDate } from '../screens/requests/components/listStatus';
import { isInvalidInvitationError } from '../screens/invitations/invitationErrors';
import { ApiError } from '../api/errors';
import { InviteCopyRow } from '../screens/organization/InviteLinkField';
import { loginAsDemo, renderApp } from './testUtils';

function withBinding(binding: Partial<EquipmentBindingSummary> | null): Pick<Equipment, 'binding' | 'active_request'> {
  return {
    active_request: null,
    binding: binding
      ? ({
          id: 'sb_1',
          status: 'confirmed',
          basis: 'service_contract',
          is_contact_only: false,
          provider_name: 'ХолодСервис',
          valid_until: null,
          guarantor_kind: null,
          guarantor_name: null,
          provider_has_crm: false,
          guarantor_stated_by_provider: false,
          ...binding,
        } as EquipmentBindingSummary)
      : null,
  };
}

describe('срочность — один словарь (GAP 10b)', () => {
  it('мастер, «Изменить условия», карточка и исполнитель называют срочность одинаково', () => {
    for (const u of ['critical', 'urgent', 'normal'] as const) {
      const label = urgencyLabel(u);
      expect(strings.requests.wizard.urgencyOption[u]).toBe(label);
      expect(strings.requests.wizard.urgencyShort[u]).toBe(label);
      expect(strings.requests.updateDetails.urgencyOption[u]).toBe(label);
      expect(strings.workspace.jobUrgencyTag[u]).toBe(label);
    }
    expect(urgencyLabel('urgent')).toBe('1–3 дня');
    expect(Object.values(strings.requests.urgency)).not.toContain('Планово');
    expect(Object.values(strings.requests.urgency)).not.toContain('Критично');
  });
});

describe('роль диспетчер/мастер (Т-24)', () => {
  it('один словарь ролей: короткая, строчная и «вы …» не расходятся', () => {
    expect(strings.home.roleShort.provider_dispatcher).toBe('Диспетчер/мастер');
    expect(strings.orgPicker.roleLower.provider_dispatcher).toBe('диспетчер/мастер');
    expect(strings.organization.youAre.provider_dispatcher).toBe('вы диспетчер/мастер');
    expect(strings.home.roleShort.provider_dispatcher).not.toBe('Мастер');
  });
});

describe('имя техники — одно на все экраны', () => {
  it('категория, бренд и модель; без категории — бренд и модель; пусто — «Не указано»', () => {
    expect(equipmentFullName({ category: 'Холодильная витрина', brand: 'Carboma', model: 'F16' })).toBe('Витрина Carboma F16');
    expect(equipmentTitle({ brand: 'Bosch', model: 'KGN39' })).toBe('Bosch KGN39');
    expect(equipmentTitle({ category_name: 'Холодильная витрина', brand: null, model: null })).toBe('Холодильная витрина');
    expect(equipmentTitle({ brand: null, model: null })).toBe(strings.common.notSpecified);
  });

  it('строка списка заявок — с моделью, как в «Технике»', () => {
    expect(
      listItemEquipmentName({
        equipment_category_name: 'Холодильная витрина',
        equipment_brand: 'Carboma',
        equipment_model: 'F16',
      }),
    ).toBe('Витрина Carboma F16');
  });
});

describe('сводка сервиса техники — одна для главной, мастера и «Техники»', () => {
  it('ожидающая привязка — «ждёт подтверждения», а не «не привязан» (регресс главной)', () => {
    const item = withBinding({ status: 'pending' });
    expect(bindingSummary(item)).toMatchObject({ kind: 'pending', tone: 'warn' });
    expect(bindingSummary(item).text).toBe('ХолодСервис · ждёт подтверждения сервиса');
    expect(equipmentLine(item as Equipment).text).toBe(bindingSummary(item).text);
  });

  it('договор, постоянный сервис, контакт, без сервиса — один словарь и формат даты', () => {
    expect(bindingSummary(withBinding({ valid_until: '2026-12-31' })).text).toBe('ХолодСервис · договор до 31 дек 2026');
    expect(bindingSummary(withBinding({ basis: 'preferred_provider' })).text).toBe('ХолодСервис · постоянный сервис');
    expect(bindingSummary(withBinding({ is_contact_only: true, status: 'pending', provider_name: 'Иван' })).text).toBe(
      'Мой контакт: Иван',
    );
    expect(bindingSummary(withBinding(null))).toMatchObject({ kind: 'none', text: 'Сервис не привязан' });
    expect(bindingSummary(withBinding({ status: 'revoked' })).kind).toBe('none');
  });

  it('«со слов сервиса» — по признаку сервера, а не по наличию гаранта', () => {
    const stated = withBinding({
      basis: 'warranty',
      guarantor_kind: 'manufacturer',
      guarantor_name: 'Bosch',
      guarantor_stated_by_provider: true,
    });
    expect(bindingSummary(stated).text).toBe('Гарантия: Bosch (со слов сервиса)');
    const verified = withBinding({
      basis: 'warranty',
      guarantor_kind: 'manufacturer',
      guarantor_name: 'Bosch',
      guarantor_stated_by_provider: false,
      warranty_authorization_id: 'wa_1',
    });
    expect(bindingSummary(verified).text).toBe('Гарантия: Bosch');
    const unflagged = withBinding({ basis: 'warranty', guarantor_kind: 'manufacturer', guarantor_name: 'Bosch' });
    expect(bindingSummary(unflagged).text).toBe('Гарантия: Bosch');
  });
});

describe('дата строки списка — в поясе точки', () => {
  it('«сегодня» считается по поясу точки, а не браузера', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-29T20:30:00Z'));
    try {
      expect(listDate('2026-09-29T21:00:00Z', 'Asia/Vladivostok')).toBe(strings.requests.dayToday);
      expect(listDate('2026-09-29T10:00:00Z', 'Asia/Vladivostok')).toBe(strings.requests.dayYesterday);
      expect(listDate(null, 'Europe/Moscow')).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('приглашения: сбой сети — не «недействительно»', () => {
  it('недействительны только 404/400/422', () => {
    expect(isInvalidInvitationError(new ApiError(404, null, 'x'))).toBe(true);
    expect(isInvalidInvitationError(new ApiError(503, null, 'x'))).toBe(false);
    expect(isInvalidInvitationError(new ApiError(429, null, 'x'))).toBe(false);
    expect(isInvalidInvitationError(new TypeError('Failed to fetch'))).toBe(false);
  });

  it('503 на предпросмотре приглашения сотрудника — ошибка с повтором, не «не найдено»', async () => {
    server.use(http.post('*/invitations/preview', () => HttpResponse.json(null, { status: 503 })));
    renderApp();
    await loginAsDemo('new_user');
    window.location.hash = '#/invitations/accept?token=inv_some-token-value';
    expect(await screen.findByText(strings.states.unavailableTitle)).toBeInTheDocument();
    expect(screen.queryByText(strings.invitationAccept.invalidTitle)).not.toBeInTheDocument();
  });

  it('404 на предпросмотре — «Приглашение не найдено»', async () => {
    server.use(
      http.post('*/invitations/preview', () =>
        HttpResponse.json({ error: { code: 'NOT_FOUND', message: 'Не найдено' } }, { status: 404 }),
      ),
    );
    renderApp();
    await loginAsDemo('new_user');
    window.location.hash = '#/invitations/accept?token=inv_some-token-value';
    expect(await screen.findByText(strings.invitationAccept.invalidTitle)).toBeInTheDocument();
  });

  it('503 на предпросмотре подключения сервиса — не «недействительно»', async () => {
    server.use(http.post('*/service-binding-invitations/preview', () => HttpResponse.json(null, { status: 503 })));
    renderApp();
    await loginAsDemo('customer_manager');
    window.location.hash = '#/bindings/accept?token=sb_some-token-value';
    expect(await screen.findByText(strings.states.unavailableTitle)).toBeInTheDocument();
    expect(screen.queryByText(strings.bindings.acceptInvalid)).not.toBeInTheDocument();
  });
});

describe('копирование ссылки-приглашения', () => {
  afterEach(() => vi.restoreAllMocks());

  it('успех — «Скопировано», поле со ссылкой не показывается', async () => {
    const user = userEvent.setup();
    render(<InviteCopyRow label="Скопировать ссылку" value="https://max.ru/app?startapp=inv_x" />);
    await user.click(screen.getByRole('button', { name: /Скопировать ссылку/ }));
    expect(await screen.findByText(strings.common.copied)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/startapp=inv_x/)).not.toBeInTheDocument();
  });

  it('буфер недоступен — ошибка и поле со ссылкой для ручного копирования', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
    const exec = vi.fn(() => false);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
    render(<InviteCopyRow label="Скопировать ссылку" value="https://max.ru/app?startapp=inv_x" />);
    await user.click(screen.getByRole('button', { name: /Скопировать ссылку/ }));
    await waitFor(() => expect(screen.getByDisplayValue('https://max.ru/app?startapp=inv_x')).toBeInTheDocument());
    expect(screen.getByText(strings.common.copyFailed)).toBeInTheDocument();
    expect(screen.queryByText(strings.common.copied)).not.toBeInTheDocument();
  });

  it('copyText без Clipboard API пробует запасной путь', async () => {
    const exec = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true });
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('no'));
    expect(await copyText('abc')).toBe(true);
    expect(exec).toHaveBeenCalledWith('copy');
  });
});
