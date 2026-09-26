import { http, HttpResponse } from 'msw';
import * as db from './db';

const BASE = '/operator-api/v1';

export function errorBody(code: string, message: string, details?: Record<string, unknown>) {
  return { error: { code, message, request_id: `req_${Math.random().toString(36).slice(2)}`, details: details ?? {} } };
}

export function unauthenticated() {
  return HttpResponse.json(errorBody('UNAUTHENTICATED', 'Требуется вход'), { status: 401 });
}

export function forbidden() {
  return HttpResponse.json(errorBody('FORBIDDEN', 'Недостаточно прав'), { status: 403 });
}

export function notFound() {
  return HttpResponse.json(errorBody('NOT_FOUND', 'Объект не найден'), { status: 404 });
}

export function validationFailed(message: string) {
  return HttpResponse.json(errorBody('VALIDATION_FAILED', message), { status: 422 });
}

export function requireOperator(request: Request): db.DbUser | { error: Response } {
  const header = request.headers.get('Authorization');
  const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
  const session = db.findSession(token);
  if (!session) return { error: unauthenticated() };
  const user = db.getUser(session.user_id);
  if (!user) return { error: unauthenticated() };
  if (!db.isOperatorUser(user.id)) return { error: forbidden() };
  return user;
}

export function withOperator(handler: (request: Request) => Response | Promise<Response>) {
  return ({ request }: { request: Request }) => {
    const resolved = requireOperator(request);
    if ('error' in resolved) return resolved.error;
    return handler(request);
  };
}

export const operatorHandlers = [
  http.get(`${BASE}/verification-cases`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const decision = url.searchParams.get('decision') ?? undefined;
      const items = db.listAllVerificationCasesForOperator(decision);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.get(`${BASE}/verification-cases/:id`, ({ request, params }) =>
    withOperator(() => {
      const item = db.getVerificationCaseForOperator(String(params.id));
      if (!item) return notFound();
      return HttpResponse.json(item);
    })({ request }),
  ),

  http.post(`${BASE}/verification-cases/:id/decision`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as {
        decision: string;
        reason: string;
        source?: string | null;
        expires_at?: string | null;
      };
      if (!body.reason || !body.reason.trim()) {
        return validationFailed('Основание решения обязательно');
      }
      if (body.decision === 'approved' && (!body.source || !body.source.trim())) {
        return validationFailed('Источник проверки обязателен для подтверждения');
      }
      if (!['approved', 'rejected', 'needs_information'].includes(body.decision)) {
        return validationFailed('Неизвестное решение');
      }
      const updated = db.decideVerificationCaseByOperator(
        String(params.id),
        body.decision as 'approved' | 'rejected' | 'needs_information',
        body.reason.trim(),
        body.source?.trim() || null,
        body.expires_at ?? null,
      );
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.get(`${BASE}/provider-profiles`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const status = url.searchParams.get('status') ?? undefined;
      const items = db.listAllProviderProfilesForOperator(status);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.post(`${BASE}/provider-profiles/:organizationId/suspend`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { reason: string };
      if (!body.reason || !body.reason.trim()) return validationFailed('Причина обязательна');
      const updated = db.operatorSetProfileStatus(String(params.organizationId), 'suspended', body.reason.trim());
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.post(`${BASE}/provider-profiles/:organizationId/reinstate`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { reason: string };
      if (!body.reason || !body.reason.trim()) return validationFailed('Причина обязательна');
      const updated = db.operatorSetProfileStatus(String(params.organizationId), 'active', body.reason.trim());
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),
];
