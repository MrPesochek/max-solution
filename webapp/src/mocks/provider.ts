import { http, HttpResponse } from 'msw';
import * as db from './db';
import { getCached, setCached } from './idempotency';
import { registerProfileAppeal } from './reviews';
import {
  authenticate,
  badRequest,
  conflict,
  forbidden,
  notFound,
  requireOrgMembership,
  unauthenticated,
} from './httpHelpers';
import type { ProviderProfileUpdateInput, VerificationInformationInput } from '../api/types';

const BASE = '/app-api/v1';

const PROVIDER_ROLES = new Set(['provider_admin', 'provider_dispatcher']);

export const providerHandlers = [
  http.get(`${BASE}/provider-profile`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();
    const profile = db.getProviderProfile(resolved.membership.organization_id);
    if (!profile) return notFound();
    return HttpResponse.json(profile);
  }),

  http.patch(`${BASE}/provider-profile`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const body = (await request.json()) as ProviderProfileUpdateInput;
    const result = db.updateProviderProfile(resolved.membership.organization_id, body);
    if (result === null) return notFound();
    if (result === 'not_editable') return conflict('INVALID_TRANSITION', 'Профиль нельзя изменить в текущем состоянии');
    if (result === 'requisites_locked') {
      return conflict('REVERIFICATION_REQUIRED', 'Изменение реквизитов проверенного профиля выполняется через оператора');
    }
    return HttpResponse.json(result);
  }),

  http.post(`${BASE}/provider-profile/appeal`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    const body = (await request.json().catch(() => null)) as { text?: unknown } | null;
    const text = typeof body?.text === 'string' ? body.text.trim() : '';
    if (!text) return badRequest('Опишите основания обжалования');
    const result = db.appealProviderProfile(resolved.membership.organization_id, text);
    if (result === null) return notFound();
    if (result === 'not_allowed') {
      return conflict('APPEAL_NOT_ALLOWED', 'Обжаловать можно только отказ или приостановку профиля');
    }
    if (result === 'already_open') return conflict('PROFILE_APPEAL_ALREADY_OPEN', 'Обжалование уже на рассмотрении');
    const profile = db.getProviderProfile(resolved.membership.organization_id);
    registerProfileAppeal({
      id: result.id,
      filerOrgId: resolved.membership.organization_id,
      description: text,
      profileStatus: profile?.status ?? 'suspended',
      statusReason: profile?.status_reason ?? null,
      createdAt: result.created_at,
    });
    return HttpResponse.json(result, { status: 201 });
  }),

  http.post(`${BASE}/provider-profile/submit`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const result = db.submitProviderProfile(resolved.membership.organization_id);
    if (result === null) return notFound();
    if (result === 'invalid') return conflict('INVALID_TRANSITION', 'Профиль уже отправлен на проверку или проверен');
    return HttpResponse.json(result);
  }),

  http.post(`${BASE}/provider-profile/accepting`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const body = (await request.json()) as { accepting: boolean };
    const result = db.setProviderAccepting(resolved.membership.organization_id, body.accepting);
    if (result === null) return notFound();
    if (result === 'invalid') return conflict('INVALID_TRANSITION', 'Приём заявок доступен только допущенному профилю');
    return HttpResponse.json(result);
  }),

  http.get(`${BASE}/providers`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const url = new URL(request.url);
    const q = url.searchParams.get('q')?.trim() || undefined;
    if (q && !/^[\d\s]+$/.test(q) && q.length < 3) {
      return HttpResponse.json(
        { error: { code: 'VALIDATION_FAILED', message: 'Введите не меньше 3 символов названия или ИНН целиком', request_id: 'mock' } },
        { status: 422 },
      );
    }
    const page = db.listProviderCatalog({
      categoryId: url.searchParams.get('category_id') ?? undefined,
      cityId: url.searchParams.get('city_id') ?? undefined,
      districtId: url.searchParams.get('district_id') ?? undefined,
      q,
    });
    return HttpResponse.json(page);
  }),

  http.get(`${BASE}/providers/count`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const url = new URL(request.url);
    const count = db.countProviderCatalog({
      categoryId: url.searchParams.get('category_id') ?? undefined,
      cityId: url.searchParams.get('city_id') ?? undefined,
      districtId: url.searchParams.get('district_id') ?? undefined,
    });
    return HttpResponse.json({ count });
  }),

  http.get(`${BASE}/providers/:providerId`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const profile = db.getPublicProviderProfile(String(params.providerId));
    if (!profile) return notFound();
    return HttpResponse.json(profile);
  }),

  http.get(`${BASE}/verification`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!PROVIDER_ROLES.has(resolved.membership.role)) return forbidden();
    return HttpResponse.json(db.listVerificationCases(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/verification`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('verification', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const body = (await request.json()) as VerificationInformationInput;
    if (!body.note?.trim()) return badRequest('Опишите, что можете подтвердить');
    db.submitVerificationInformation(resolved.membership.organization_id, body);
    const result = { ok: true };
    setCached('verification', idempotencyKey, 200, result);
    return HttpResponse.json(result);
  }),
];
