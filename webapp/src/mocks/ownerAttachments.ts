import { http, HttpResponse } from 'msw';
import * as db from './db';
import * as rdb from './requestsDb';
import { getCached, setCached } from './idempotency';
import {
  authenticate,
  badRequest,
  errorBody,
  forbidden,
  notFound,
  requireOrgMembership,
  unauthenticated,
} from './httpHelpers';

const BASE = '/app-api/v1';
const EQUIPMENT_PHOTO_LIMIT = 20;
const CUSTOMER_ROLES = new Set(['customer_manager', 'customer_employee']);

export const ownerAttachmentsHandlers = [
  http.get(`${BASE}/equipment/:id/photos`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!db.getEquipmentItem(String(params.id), resolved.membership.organization_id))
      return notFound();
    return HttpResponse.json(rdb.listOwnedAttachments('equipment', String(params.id)));
  }),

  http.post(`${BASE}/equipment/:id/photos`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const equipmentId = String(params.id);
    if (!CUSTOMER_ROLES.has(resolved.membership.role)) return notFound();
    if (!db.getEquipmentItem(equipmentId, resolved.membership.organization_id)) return notFound();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('equipment-photos', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    if (rdb.listOwnedAttachments('equipment', equipmentId).length >= EQUIPMENT_PHOTO_LIMIT) {
      return HttpResponse.json(
        errorBody(
          'EQUIPMENT_PHOTO_LIMIT_REACHED',
          `К оборудованию уже приложено ${EQUIPMENT_PHOTO_LIMIT} фото`,
        ),
        { status: 422 },
      );
    }
    const formData = await request.formData();
    const file = formData.get('file');
    if (!(file instanceof File)) return badRequest('Файл не передан');
    const slot = formData.get('slot');

    const attachment = rdb.addAttachment({
      ownerKind: 'equipment',
      requestId: null,
      messageId: null,
      slot: typeof slot === 'string' ? slot : null,
      visibilityClass: 'request_private',
      mimeType: file.type || 'image/jpeg',
      blob: file,
      ownerOrgId: resolved.membership.organization_id,
      ownerRef: equipmentId,
    });
    setCached('equipment-photos', idempotencyKey, 201, attachment as never);
    return HttpResponse.json(attachment, { status: 201 });
  }),

  http.post(`${BASE}/verification/attachments`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const idempotencyKey = request.headers.get('Idempotency-Key');
    const cached = getCached('verification-evidence', idempotencyKey);
    if (cached) return HttpResponse.json(cached.body, { status: cached.status });

    const formData = await request.formData();
    const file = formData.get('file');
    if (!(file instanceof File)) return badRequest('Файл не передан');
    const caseId = formData.get('verification_case_id');
    const openCase = db
      .listVerificationCases(resolved.membership.organization_id)
      .filter((c) => c.decision === 'pending' || c.decision === 'needs_information')
      .find((c) => typeof caseId !== 'string' || !caseId || c.id === caseId);
    if (!openCase) return notFound();

    const attachment = rdb.addAttachment({
      ownerKind: 'verification_case',
      requestId: null,
      messageId: null,
      slot: 'evidence',
      visibilityClass: 'verification_evidence',
      mimeType: file.type || 'application/octet-stream',
      blob: file,
      ownerOrgId: resolved.membership.organization_id,
      ownerRef: openCase.id,
    });
    setCached('verification-evidence', idempotencyKey, 201, attachment as never);
    return HttpResponse.json(attachment, { status: 201 });
  }),
];
