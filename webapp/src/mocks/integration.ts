import { http, HttpResponse } from 'msw';
import * as db from './db';
import { getCached, setCached } from './idempotency';
import {
  authenticate,
  badRequest,
  conflict,
  forbidden,
  notFound,
  requireOrgMembership,
  unauthenticated,
  validationFailed,
} from './httpHelpers';
import { INTEGRATION_SCOPES } from '../api/types';
import type { ApiKeyCreateInput, WebhookSubscriptionCreateInput } from '../api/types';

const BASE = '/app-api/v1';

export const integrationHandlers = [
  http.get(`${BASE}/integration/api-keys`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    return HttpResponse.json(db.listApiKeys(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/integration/api-keys`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    if (getCached('api-keys', idempotencyKey)) {
      return conflict('IDEMPOTENT_SECRET_NOT_REPLAYABLE', 'Ключ уже выдан, повторно показать его нельзя');
    }

    const body = (await request.json()) as ApiKeyCreateInput;
    if (!body.name?.trim() || !body.scopes?.length) return badRequest('Укажите название и хотя бы один scope');
    const unknown = body.scopes.filter((s) => !(INTEGRATION_SCOPES as readonly string[]).includes(s));
    if (unknown.length > 0) return badRequest('Неизвестный scope');
    const conflicting = db.scopeConflicts(body.scopes);
    if (conflicting.length > 0) {
      return HttpResponse.json(
        {
          error: {
            code: 'SCOPE_CONFLICT',
            message: 'Право создавать привязки выдаётся отдельным ключом',
            request_id: 'mock',
            details: { field: 'scopes', conflicting },
          },
        },
        { status: 422 },
      );
    }

    const created = db.createApiKey(resolved.membership.organization_id, body);
    setCached('api-keys', idempotencyKey, 201, { id: created.id });
    return HttpResponse.json(created, { status: 201 });
  }),

  http.post(`${BASE}/integration/api-keys/:clientId/revoke`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const result = db.revokeApiKey(resolved.membership.organization_id, String(params.clientId));
    if (!result) return notFound();
    return HttpResponse.json(result);
  }),

  http.post(`${BASE}/integration/api-keys/:clientId/rotate`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const result = db.rotateApiKey(resolved.membership.organization_id, String(params.clientId));
    if (!result) return notFound();
    return HttpResponse.json(result);
  }),

  http.get(`${BASE}/integration/webhook-subscriptions`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    return HttpResponse.json(db.listWebhookSubscriptions(resolved.membership.organization_id));
  }),

  http.get(`${BASE}/integration/summary`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    return HttpResponse.json(db.integrationSummary(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/integration/webhook-subscriptions`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    const idempotencyKey = request.headers.get('Idempotency-Key');
    if (getCached('webhook-subscriptions', idempotencyKey)) {
      return conflict('IDEMPOTENT_SECRET_NOT_REPLAYABLE', 'Подписка уже создана, секрет повторно не показывается');
    }
    const body = (await request.json()) as WebhookSubscriptionCreateInput;
    if (!/^https:\/\//.test(body.url ?? '')) {
      return HttpResponse.json(
        { error: { code: 'WEBHOOK_URL_REJECTED', message: 'URL вебхука недопустим', request_id: 'mock' } },
        { status: 422 },
      );
    }
    const result = db.createWebhookSubscription(resolved.membership.organization_id, body);
    if (result === 'no_key') return conflict('NO_ACTIVE_API_KEY', 'Сначала выпустите ключ интеграции');
    if (result === 'client_not_found') return notFound();
    if (result === 'client_required') return validationFailed('client_id', 'Укажите ключ интеграции');
    setCached('webhook-subscriptions', idempotencyKey, 201, { id: result.id });
    return HttpResponse.json(result, { status: 201 });
  }),

  http.post(`${BASE}/integration/webhook-subscriptions/:id/:action`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    const orgId = resolved.membership.organization_id;
    const action = String(params.action);
    if (action === 'rotate-secret') {
      const rotated = db.rotateWebhookSecret(orgId, String(params.id));
      return rotated ? HttpResponse.json(rotated) : notFound();
    }
    if (action !== 'enable' && action !== 'disable') return notFound();
    const result = db.setWebhookSubscriptionEnabled(orgId, String(params.id), action === 'enable');
    if (result === null) return notFound();
    if (result === 'unchanged') {
      return conflict(
        action === 'enable' ? 'SUBSCRIPTION_ACTIVE' : 'SUBSCRIPTION_DISABLED',
        action === 'enable' ? 'Подписка уже включена' : 'Подписка уже отключена',
      );
    }
    return HttpResponse.json(result);
  }),

  http.get(`${BASE}/integration/deliveries`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    return HttpResponse.json(db.listDeliveries(resolved.membership.organization_id));
  }),

  http.post(`${BASE}/integration/deliveries/:deliveryId/redeliver`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const result = db.redeliverDelivery(resolved.membership.organization_id, String(params.deliveryId));
    if (!result) return notFound();
    return HttpResponse.json(result);
  }),
];
