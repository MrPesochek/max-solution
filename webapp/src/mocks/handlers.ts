import { http, HttpResponse } from 'msw';
import * as db from './db';
import { getCached, setCached } from './idempotency';
import { requestsHandlers } from './requestsHandlers';
import * as rdb from './requestsDb';
import { operatorHandlers } from './operatorHandlers';
import { providerHandlers } from './provider';
import { bindingsHandlers } from './bindings';
import { integrationHandlers } from './integration';
import { reviewsHandlers } from './reviews';
import { portfolioHandlers } from './portfolio';
import { ownerAttachmentsHandlers } from './ownerAttachments';
import { operatorQueuesHandlers } from './operatorQueues';
import { operatorReputationHandlers } from './operatorReputation';
import { conflict, requireOrgMembership, validationFailed } from './httpHelpers';
import type {
  AuthResponse,
  CreateInvitationInput,
  CreateOrganizationInput,
  EquipmentInput,
  EquipmentUpdateInput,
  LocationInput,
  LocationUpdateInput,
  MeResponse,
  ParticipationInput,
  UpdateOrganizationInput,
} from '../api/types';
import { tracked } from './mockState';

const BASE = '/app-api/v1';

function errorBody(code: string, message: string, details?: Record<string, unknown>) {
  return { error: { code, message, request_id: `req_${Math.random().toString(36).slice(2)}`, details: details ?? {} } };
}

function requestScope(membership: { role: string; location_ids: string[] }): string[] | null {
  return membership.role === 'customer_employee' ? membership.location_ids : null;
}

function unauthenticated() {
  return HttpResponse.json(errorBody('UNAUTHENTICATED', 'Требуется вход'), { status: 401 });
}

function forbidden(message = 'Недостаточно прав') {
  return HttpResponse.json(errorBody('FORBIDDEN', message), { status: 403 });
}

function notFound() {
  return HttpResponse.json(errorBody('NOT_FOUND', 'Объект не найден'), { status: 404 });
}

function badRequest(message: string) {
  return HttpResponse.json(errorBody('BAD_REQUEST', message), { status: 400 });
}

function authenticate(request: Request): db.DbUser | null {
  const header = request.headers.get('Authorization');
  const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
  const session = db.findSession(token);
  if (!session) return null;
  return db.getUser(session.user_id);
}

const usedLinkTokens = tracked(new Set<string>());

const MANAGER_ROLES = new Set(['customer_manager', 'provider_admin']);

export const handlers = [
  http.get(`${BASE}/showcase`, () => HttpResponse.json({ enabled: false })),
  http.post(`${BASE}/auth/max`, async ({ request }) => {
    const body = (await request.json()) as { init_data?: string };
    if (!body.init_data) return unauthenticated();
    if (body.init_data === 'trigger-401') return unauthenticated();

    const demoMatch = /^demo:(.+)$/.exec(body.init_data);
    const userId = demoMatch
      ? db.findUserIdByDemoKey(demoMatch[1] ?? '')
      : db.findUserIdByDemoKey('customer_manager');
    if (!userId) return unauthenticated();

    const user = db.getUser(userId);
    if (!user) return unauthenticated();

    const session = db.createSession(user.id);
    const response: AuthResponse = {
      token: session.token,
      expires_at: new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString(),
      user: { id: user.id, display_name: user.display_name },
      memberships: db.getMembershipsForUser(user.id),
      organizations: db.getOrganizationsForUser(user.id),
    };
    return HttpResponse.json(response, { status: 200 });
  }),

  http.post(`${BASE}/auth/demo`, async ({ request }) => {
    const body = (await request.json()) as { user_key?: string };
    const userId = body.user_key ? db.findUserIdByDemoKey(body.user_key) : null;
    if (!userId) return unauthenticated();

    const user = db.getUser(userId);
    if (!user) return unauthenticated();

    const session = db.createSession(user.id);
    const response: AuthResponse = {
      token: session.token,
      expires_at: new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString(),
      user: { id: user.id, display_name: user.display_name },
      memberships: db.getMembershipsForUser(user.id),
      organizations: db.getOrganizationsForUser(user.id),
    };
    return HttpResponse.json(response, { status: 200 });
  }),

  http.post(`${BASE}/auth/link`, async ({ request }) => {
    const body = (await request.json()) as { token?: string };
    const match = /^demo:([^:]+)(?::(.+))?$/.exec(body.token ?? '');
    const userId =
      match && !usedLinkTokens.has(body.token ?? '')
        ? db.findUserIdByDemoKey(match[1] ?? '')
        : null;
    const user = userId ? db.getUser(userId) : null;
    if (!user) {
      return HttpResponse.json(
        errorBody('LOGIN_LINK_INVALID', 'Ссылка для входа устарела или уже использована'),
        { status: 401 },
      );
    }
    usedLinkTokens.add(body.token ?? '');
    const session = db.createSession(user.id);
    return HttpResponse.json(
      {
        token: session.token,
        expires_at: new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString(),
        user: { id: user.id, display_name: user.display_name },
        memberships: db.getMembershipsForUser(user.id),
        organizations: db.getOrganizationsForUser(user.id),
        target: match?.[2] ?? null,
      },
      { status: 200 },
    );
  }),

  http.get(`${BASE}/me`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const response: MeResponse = {
      user: { id: user.id, display_name: user.display_name },
      memberships: db.getMembershipsForUser(user.id),
      organizations: db.getOrganizationsForUser(user.id),
    };
    return HttpResponse.json(response);
  }),

  http.post(`${BASE}/auth/logout`, ({ request }) => {
    const header = request.headers.get('Authorization');
    const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
    if (token) db.revokeSession(token);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${BASE}/directories/cities`, () => HttpResponse.json(db.getCities())),
  http.get(`${BASE}/directories/equipment-categories`, () =>
    HttpResponse.json(db.getEquipmentCategories()),
  ),

  http.post(`${BASE}/organizations`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('organizations', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const input = (await request.json()) as CreateOrganizationInput;
    if (!input.name || !input.contact_phone || !input.kind) return badRequest('Не заполнены обязательные поля');

    const result = db.createOrganizationWithMembership(user.id, input);
    setCached('organizations', idempotencyKey, 201, result);
    return HttpResponse.json(result, { status: 201 });
  }),

  http.get(`${BASE}/organizations/current`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const org = db.getCurrentOrganization(resolved.membership.organization_id);
    if (!org) return notFound();
    return HttpResponse.json(org);
  }),

  ...(['current', ':organizationId'] as const).map((segment) =>
    http.patch(`${BASE}/organizations/${segment}`, async ({ request, params }) => {
      const user = authenticate(request);
      if (!user) return unauthenticated();
      const resolved = requireOrgMembership(request, user);
      if ('error' in resolved) return resolved.error;
      const { membership } = resolved;
      if (params.organizationId && params.organizationId !== membership.organization_id) return notFound();
      if (!MANAGER_ROLES.has(membership.role)) return forbidden();

      const input = (await request.json()) as UpdateOrganizationInput;
      if (input.name !== undefined && input.name !== null && !input.name.trim()) {
        return validationFailed('name', 'Укажите название организации');
      }
      const result = db.updateOrganization(membership.organization_id, input);
      if (result === null) return notFound();
      if (result === 'INN_LOCKED') {
        return conflict('INN_LOCKED', 'ИНН проверенной организации изменить нельзя, обратитесь к оператору');
      }
      if (result === 'REQUISITES_UNDER_REVIEW') {
        return conflict('REQUISITES_UNDER_REVIEW', 'Реквизиты на проверке, изменить их сейчас нельзя');
      }
      return HttpResponse.json(result);
    }),
  ),

  http.post(`${BASE}/organizations/:organizationId/participation`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const { membership } = resolved;
    if (params.organizationId !== membership.organization_id) return notFound();
    if (!MANAGER_ROLES.has(membership.role)) return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('participation', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const input = (await request.json()) as ParticipationInput;
    if (input.kind !== 'customer' && input.kind !== 'provider') {
      return validationFailed('kind', 'Укажите тип участия');
    }
    const result = db.addParticipation(user.id, membership.organization_id, input);
    if (result === null) return notFound();
    if (result === 'PARTICIPATION_EXISTS') {
      return conflict('PARTICIPATION_EXISTS', 'Организация уже участвует в этом качестве');
    }
    if (result === 'INN_ALREADY_VERIFIED') {
      return conflict('INN_ALREADY_VERIFIED', 'ИНН уже подтверждён у другой организации');
    }
    setCached('participation', idempotencyKey, 201, result);
    return HttpResponse.json(result, { status: 201 });
  }),

  http.get(`${BASE}/locations`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    return HttpResponse.json(db.listLocations(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/locations`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('locations', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const input = (await request.json()) as LocationInput;
    const location = db.createLocationForOrg(resolved.membership.organization_id, input);
    setCached('locations', idempotencyKey, 201, location);
    return HttpResponse.json(location, { status: 201 });
  }),

  http.get(`${BASE}/locations/:id`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const location = db.getLocation(String(params.id), resolved.membership.organization_id);
    if (!location) return notFound();
    return HttpResponse.json(location);
  }),

  http.patch(`${BASE}/locations/:id`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const input = (await request.json()) as LocationUpdateInput;
    const location = db.updateLocation(String(params.id), resolved.membership.organization_id, input);
    if (!location) return notFound();
    return HttpResponse.json(location);
  }),

  http.get(`${BASE}/equipment`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const url = new URL(request.url);
    const locationId = url.searchParams.get('location_id') ?? undefined;
    const orgId = resolved.membership.organization_id;
    const page = db.listEquipment(orgId, locationId);
    const scope = requestScope(resolved.membership);
    return HttpResponse.json({ ...page, items: page.items.map((item) => rdb.withEquipmentSummary(item, orgId, scope)) });
  }),

  http.post(`${BASE}/equipment`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('equipment', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const input = (await request.json()) as EquipmentInput;
    const item = db.createEquipmentForOrg(resolved.membership.organization_id, input);
    if (!item) return badRequest('Точка не найдена');
    setCached('equipment', idempotencyKey, 201, item);
    return HttpResponse.json(item, { status: 201 });
  }),

  http.get(`${BASE}/equipment/:id`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const item = db.getEquipmentItem(String(params.id), resolved.membership.organization_id);
    if (!item) return notFound();
    return HttpResponse.json(
      rdb.withEquipmentSummary(item, resolved.membership.organization_id, requestScope(resolved.membership)),
    );
  }),

  http.patch(`${BASE}/equipment/:id`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const input = (await request.json()) as EquipmentUpdateInput;
    const updated = db.updateEquipmentItem(String(params.id), resolved.membership.organization_id, input);
    if (!updated) return notFound();
    return HttpResponse.json(updated);
  }),

  http.post(`${BASE}/memberships/me/access-requests`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    if ('request_id' in body) return validationFailed('request_id', 'Лишнее поле');
    return HttpResponse.json({ status: 'sent' }, { status: 202 });
  }),

  http.get(`${BASE}/memberships`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();
    const { membership } = resolved;
    return HttpResponse.json(db.listStaff(membership.organization_id, db.sideOfRole(membership.role)));
  }),

  http.post(`${BASE}/memberships/:id/approve`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();

    const approved = db.approveMembership(
      resolved.membership.organization_id,
      String(params.id),
      db.sideOfRole(resolved.membership.role),
    );
    if (!approved) return notFound();
    return HttpResponse.json(approved);
  }),

  http.post(`${BASE}/memberships/:id/revoke`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();

    const revoked = db.revokeMembership(resolved.membership, String(params.id));
    if (revoked === 'not_found') return notFound();
    if (revoked === 'already_revoked') return conflict('CONFLICT', 'Участник уже отозван');
    if (revoked === 'last_manager') {
      return conflict('LAST_MANAGER', 'Нельзя отозвать последнего руководителя организации');
    }
    if (revoked === 'self') return conflict('SELF_REVOKE', 'Нельзя исключить самого себя');
    return HttpResponse.json(revoked);
  }),

  http.put(`${BASE}/memberships/:id/locations`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const body = (await request.json()) as { location_ids: string[] };
    const updated = db.setMembershipLocations(resolved.membership.organization_id, String(params.id), body.location_ids);
    if (!updated) return notFound();
    return HttpResponse.json(updated);
  }),

  http.get(`${BASE}/invitations`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();
    const { membership } = resolved;
    return HttpResponse.json(db.listInvitations(membership.organization_id, db.sideOfRole(membership.role)));
  }),

  http.post(`${BASE}/invitations`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('invitations', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const input = (await request.json()) as CreateInvitationInput;
    if (db.sideOfRole(input.role) !== db.sideOfRole(resolved.membership.role)) return forbidden();
    const invitation = db.createInvitation(resolved.membership.organization_id, input, user.display_name);
    setCached('invitations', idempotencyKey, 201, invitation);
    return HttpResponse.json(invitation, { status: 201 });
  }),

  http.post(`${BASE}/invitations/:id/revoke`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!MANAGER_ROLES.has(resolved.membership.role)) return forbidden();

    const revoked = db.revokeInvitation(resolved.membership.organization_id, String(params.id));
    if (revoked === null) return notFound();
    if (revoked === 'invalid') {
      return HttpResponse.json(errorBody('INVITATION_INVALID', 'Приглашение недействительно'), { status: 409 });
    }
    return HttpResponse.json(revoked);
  }),

  http.post(`${BASE}/invitations/preview`, async ({ request }) => {
    const body = (await request.json().catch(() => null)) as { token?: unknown } | null;
    const token = typeof body?.token === 'string' ? body.token : '';
    if (token.length < 8) return validationFailed('token', 'Не указан токен');
    const preview = db.previewInvitation(token);
    if (!preview) return notFound();
    return HttpResponse.json(preview);
  }),

  http.post(`${BASE}/invitations/accept`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();

    const body = (await request.json()) as { token?: string };
    if (!body.token) return badRequest('Не указан токен');

    const result = db.acceptInvitation(body.token, user.id);
    if (result === null || result === 'foreign') {
      return HttpResponse.json(errorBody('INVITATION_INVALID', 'Приглашение недействительно'), { status: 409 });
    }
    if (result === 'invalid') {
      return HttpResponse.json(
        errorBody('INVITATION_INVALID', 'Приглашение недействительно', { reason: 'expired' }),
        { status: 409 },
      );
    }
    return HttpResponse.json(result, { status: 201 });
  }),

  ...requestsHandlers,
  ...providerHandlers,
  ...bindingsHandlers,
  ...integrationHandlers,
  ...reviewsHandlers,
  ...portfolioHandlers,
  ...ownerAttachmentsHandlers,
  ...operatorHandlers,
  ...operatorQueuesHandlers,
  ...operatorReputationHandlers,
];
