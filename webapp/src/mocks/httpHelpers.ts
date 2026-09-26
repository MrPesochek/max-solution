import { HttpResponse } from 'msw';
import * as db from './db';

export function errorBody(code: string, message: string, details?: Record<string, unknown>) {
  return { error: { code, message, request_id: `req_${Math.random().toString(36).slice(2)}`, details: details ?? {} } };
}

export function unauthenticated() {
  return HttpResponse.json(errorBody('UNAUTHENTICATED', 'Требуется вход'), { status: 401 });
}

export function forbidden(message = 'Недостаточно прав') {
  return HttpResponse.json(errorBody('FORBIDDEN', message), { status: 403 });
}

export function notFound() {
  return HttpResponse.json(errorBody('NOT_FOUND', 'Объект не найден'), { status: 404 });
}

export function badRequest(message: string) {
  return HttpResponse.json(errorBody('BAD_REQUEST', message), { status: 400 });
}

export function conflict(code: string, message: string) {
  return HttpResponse.json(errorBody(code, message), { status: 409 });
}

export function rateLimited(message: string, details?: Record<string, unknown>) {
  return HttpResponse.json(errorBody('RATE_LIMITED', message, details), { status: 429 });
}

export function authenticate(request: Request): db.DbUser | null {
  const header = request.headers.get('Authorization');
  const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
  const session = db.findSession(token);
  if (!session) return null;
  return db.getUser(session.user_id);
}

export function requireOrgMembership(request: Request, user: db.DbUser) {
  const membershipId = request.headers.get('X-Membership-Id');
  const orgId = request.headers.get('X-Organization-Id');
  if (!membershipId && !orgId) {
    return { error: forbidden('Укажите членство в заголовке X-Membership-Id') } as const;
  }
  const membership = db.resolveActiveMembership(user.id, membershipId, orgId);
  if (membership === 'not_found') return { error: notFound() } as const;
  if (membership === 'ambiguous') {
    return {
      error: conflict('MEMBERSHIP_AMBIGUOUS', 'В организации несколько ролей: выберите членство'),
    } as const;
  }
  return { membership } as const;
}

export function validationFailed(field: string, message: string, code = 'VALIDATION_FAILED') {
  return HttpResponse.json(errorBody(code, message, { field }), { status: 422 });
}

export function missingExpectedVersion(body: unknown): Response | null {
  const value = (body as { expected_version?: unknown } | null)?.expected_version;
  if (typeof value === 'number' && Number.isInteger(value) && value >= 1) return null;
  return validationFailed('expected_version', 'Не указана версия заявки (expected_version)');
}

export function blobToArrayBuffer(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === 'function') return blob.arrayBuffer();
  if (typeof FileReader !== 'undefined') {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error ?? new Error('Не удалось прочитать файл'));
      reader.readAsArrayBuffer(blob);
    });
  }
  return new Response(blob).arrayBuffer();
}
