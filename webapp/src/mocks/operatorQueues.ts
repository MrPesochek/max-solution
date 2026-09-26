import { http, HttpResponse } from 'msw';
import { blobToArrayBuffer } from './httpHelpers';
import * as db from './db';
import * as rdb from './requestsDb';
import { notFound, validationFailed, withOperator } from './operatorHandlers';
import type { WarrantyAuthorizationCreateInput } from './db';

const BASE = '/operator-api/v1';

export const operatorQueuesHandlers = [
  http.get(`${BASE}/warranty-authorizations`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const providerOrgId = url.searchParams.get('provider_organization_id') ?? undefined;
      const items = db.listAllWarrantyAuthorizations(providerOrgId);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.post(`${BASE}/warranty-authorizations`, async ({ request }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as WarrantyAuthorizationCreateInput & { source?: string; reason?: string };
      if (!body.source?.trim()) return validationFailed('Источник проверки обязателен');
      if (!body.reason?.trim()) return validationFailed('Основание выдачи обязательно');
      if (!body.provider_organization_id?.trim()) return validationFailed('Укажите исполнителя');
      const created = db.createWarrantyAuthorization(body);
      return HttpResponse.json(created, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/warranty-authorizations/:id/revoke`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { reason?: string };
      if (!body.reason?.trim()) return validationFailed('Причина отзыва обязательна');
      const updated = db.revokeWarrantyAuthorization(String(params.id));
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.get(`${BASE}/service-bindings`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const status = url.searchParams.get('status') ?? undefined;
      const items = db.listAllBindingsForOperator(status);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.post(`${BASE}/service-bindings/:id/revoke`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { reason?: string };
      if (!body.reason?.trim()) return validationFailed('Причина отзыва обязательна');
      const updated = db.operatorRevokeBinding(String(params.id), body.reason.trim());
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.get(`${BASE}/attachments`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const status = url.searchParams.get('status') ?? 'pending';
      const items = rdb.listAttachmentModerationQueue(status);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.post(`${BASE}/attachments/:id/approve`, ({ request, params }) =>
    withOperator(() => {
      const updated = rdb.approveModeratedAttachment(String(params.id));
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.post(`${BASE}/attachments/:id/reject`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { reason?: string };
      if (!body.reason?.trim()) return validationFailed('Причина отклонения обязательна');
      const updated = rdb.rejectModeratedAttachment(String(params.id), body.reason.trim());
      if (!updated) return notFound();
      return HttpResponse.json(updated);
    })({ request }),
  ),

  http.get(`${BASE}/attachments/:id/content`, ({ request, params }) =>
    withOperator(async () => {
      const record = rdb.getAttachmentRecord(String(params.id));
      if (!record) return notFound();
      const buffer = await blobToArrayBuffer(record.blob);
      return new HttpResponse(buffer, { status: 200, headers: { 'Content-Type': record.mime_type, 'Cache-Control': 'private, no-store' } });
    })({ request }),
  ),
];
