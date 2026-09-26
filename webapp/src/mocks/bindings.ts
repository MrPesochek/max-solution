import { http, HttpResponse } from 'msw';
import * as db from './db';
import { getCached, setCached } from './idempotency';
import {
  authenticate,
  errorBody,
  badRequest,
  conflict,
  forbidden,
  notFound,
  rateLimited,
  requireOrgMembership,
  unauthenticated,
  validationFailed,
} from './httpHelpers';
import type {
  BindingInvitationAcceptInput,
  BindingInvitationCreateInput,
  BindingRequestInput,
  BindingRespondInput,
  BindingRevokeInput,
  ContactBindingInput,
} from '../api/types';

const BASE = '/app-api/v1';

const PROVIDER_ROLES = new Set(['provider_admin', 'provider_dispatcher']);

export const bindingsHandlers = [
  http.get(`${BASE}/service-bindings`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const url = new URL(request.url);
    const side = PROVIDER_ROLES.has(resolved.membership.role) ? 'provider' : 'customer';
    const page = db.listBindings(resolved.membership.organization_id, side, {
      equipmentId: url.searchParams.get('equipment_id') ?? undefined,
      status: url.searchParams.get('status') ?? undefined,
    });
    return HttpResponse.json(page);
  }),

  http.post(`${BASE}/service-bindings/requests`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('binding-requests', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const body = (await request.json()) as BindingRequestInput;
    if (!body.contract_number?.trim() || !body.equipment_ids?.length) {
      return badRequest('Укажите номер договора и оборудование');
    }
    const result = db.requestBinding(resolved.membership.organization_id, body);
    if (result === 'not_found') return notFound();
    if ('rateLimited' in result) {
      return rateLimited('Слишком много запросов на привязку, попробуйте позже', {
        retry_after_seconds: result.retryAfterSeconds,
      });
    }
    setCached('binding-requests', idempotencyKey, 202, result);
    return HttpResponse.json(result, { status: 202 });
  }),

  http.post(`${BASE}/service-bindings/contacts`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('binding-contacts', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const body = (await request.json()) as ContactBindingInput;
    if (!body.contact_name?.trim()) return badRequest('Укажите контакт');
    const result = db.createContactBinding(resolved.membership.organization_id, body);
    if (result === 'not_found') return badRequest('Оборудование не найдено');
    setCached('binding-contacts', idempotencyKey, 201, result);
    return HttpResponse.json(result, { status: 201 });
  }),

  http.get(`${BASE}/service-bindings/:bindingId`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const view = db.getBindingView(resolved.membership.organization_id, String(params.bindingId));
    if (!view) return notFound();
    return HttpResponse.json(view);
  }),

  http.post(`${BASE}/service-bindings/:bindingId/respond`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();

    const body = (await request.json()) as BindingRespondInput;
    const result = db.respondBinding(
      resolved.membership.organization_id,
      String(params.bindingId),
      body.decision,
      body.reason,
    );
    if (result === 'not_found') return notFound();
    if (result === 'invalid') return conflict('INVALID_TRANSITION', 'Привязка уже обработана');
    return HttpResponse.json(result);
  }),

  http.post(`${BASE}/service-bindings/:bindingId/revoke`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const body = (await request.json()) as BindingRevokeInput;
    if (!body.reason?.trim()) return badRequest('Укажите причину отзыва');
    const result = db.revokeBinding(resolved.membership.organization_id, String(params.bindingId), body.reason.trim());
    if (result === 'not_found') return notFound();
    if (result === 'invalid') return conflict('INVALID_TRANSITION', 'Привязка уже прекращена');
    return HttpResponse.json(result);
  }),

  http.get(`${BASE}/service-binding-invitations`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();
    return HttpResponse.json(db.listBindingInvitations(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/service-binding-invitations`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('binding-invitations', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const body = (await request.json()) as BindingInvitationCreateInput;
    if (!body.customer_inn?.trim() || !body.contract_number?.trim()) {
      return badRequest('Укажите ИНН заказчика и номер договора');
    }
    const items = body.equipment_items ?? [];
    if (items.length === 0) return validationFailed('equipment_items', 'Добавьте хотя бы одну позицию оборудования');
    const emptyIndex = items.findIndex((item) => !item.description?.trim());
    if (emptyIndex >= 0) {
      return validationFailed(`equipment_items.${emptyIndex}.description`, 'Укажите описание позиции');
    }
    const result = db.createBindingInvitation(resolved.membership.organization_id, { ...body, equipment_items: items });
    if (result === 'provider_not_active') return conflict('INVALID_TRANSITION', 'Профиль ещё не допущен к обслуживанию');
    if (result === 'self_binding') {
      return conflict('SELF_BINDING_FORBIDDEN', 'Организация не может быть собственным сервисом');
    }
    setCached('binding-invitations', idempotencyKey, 201, result);
    return HttpResponse.json(result, { status: 201 });
  }),

  http.post(`${BASE}/service-binding-invitations/preview`, async ({ request }) => {
    const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
    const token = typeof body?.token === 'string' ? body.token : '';
    if (token.length < 8) return validationFailed('token', 'Не указан токен');
    const user = authenticate(request);
    if (!user) return unauthenticated();
    let viewer: { organizationId: string; role: string } | null = null;
    if (request.headers.get('X-Membership-Id') || request.headers.get('X-Organization-Id')) {
      const resolved = requireOrgMembership(request, user);
      if ('error' in resolved) return resolved.error;
      viewer = { organizationId: resolved.membership.organization_id, role: resolved.membership.role };
    }
    const preview = db.previewBindingInvitation(token, viewer);
    if (!preview) return notFound();
    return HttpResponse.json(preview);
  }),

  http.post(`${BASE}/service-binding-invitations/accept`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('binding-invitations-accept', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const body = (await request.json()) as BindingInvitationAcceptInput;
    if (!body.token) return badRequest('Не указан токен');
    if (!body.matches || body.matches.length === 0) {
      return validationFailed('matches', 'Сопоставьте каждую позицию приглашения со своим оборудованием');
    }
    const result = db.acceptBindingInvitation(resolved.membership.organization_id, body.token, body.matches);
    if (!Array.isArray(result)) {
      switch (result.code) {
        case 'INVITATION_INVALID':
          return conflict('INVITATION_INVALID', 'Приглашение недействительно');
        case 'SELF_BINDING_FORBIDDEN':
          return conflict('SELF_BINDING_FORBIDDEN', 'Организация не может быть собственным сервисом');
        case 'MATCHES_INVALID':
          return validationFailed('matches', result.message);
        case 'SERIAL_NUMBER_MISMATCH':
          return HttpResponse.json(
            errorBody('SERIAL_NUMBER_MISMATCH', 'Серийный номер оборудования не совпадает с позицией приглашения', {
              field: 'matches',
              item_index: result.itemIndex,
            }),
            { status: 422 },
          );
      }
    }
    const response = { items: result };
    setCached('binding-invitations-accept', idempotencyKey, 201, response);
    return HttpResponse.json(response, { status: 201 });
  }),

  http.post(`${BASE}/service-binding-invitations/decline`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const body = (await request.json()) as { token?: string; reason?: string | null };
    if (!body.token) return badRequest('Не указан токен');
    const result = db.declineBindingInvitation(resolved.membership.organization_id, body.token, body.reason ?? null);
    if (result === 'invalid') return conflict('INVITATION_INVALID', 'Приглашение недействительно');
    return HttpResponse.json(result);
  }),

  http.post(`${BASE}/service-binding-invitations/:invitationId/revoke`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();

    const result = db.revokeBindingInvitation(resolved.membership.organization_id, String(params.invitationId));
    if (result === null) return notFound();
    if (result === 'invalid') return conflict('INVITATION_INVALID', 'Приглашение недействительно');
    return HttpResponse.json(result);
  }),
];
