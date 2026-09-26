import { http, HttpResponse } from 'msw';
import * as db from './db';
import * as rdb from './requestsDb';
import { authenticate, badRequest, forbidden, notFound, requireOrgMembership, unauthenticated } from './httpHelpers';

const BASE = '/app-api/v1';

export function seedPendingPortfolioAttachment(organizationId: string = db.demoSeed.demoActiveProvider.id) {
  return rdb.addAttachment({
    ownerKind: 'provider_profile',
    requestId: null,
    messageId: null,
    slot: 'portfolio',
    visibilityClass: 'profile_public',
    mimeType: 'image/png',
    blob: new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }),
    needsModeration: true,
    ownerOrgId: organizationId,
  });
}

export const portfolioHandlers = [
  http.post(`${BASE}/provider-profile/portfolio`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const existing = rdb.listPortfolio(resolved.membership.organization_id);
    if (existing.length >= db.PORTFOLIO_MAX_IMAGES) {
      return badRequest('В галерее уже достигнут лимит изображений');
    }

    const formData = await request.formData();
    const file = formData.get('file');
    if (!(file instanceof File)) return badRequest('Файл не передан');

    const attachment = rdb.addAttachment({
      ownerKind: 'provider_profile',
      requestId: null,
      messageId: null,
      slot: 'portfolio',
      visibilityClass: 'profile_public',
      mimeType: file.type || 'image/jpeg',
      blob: file,
      needsModeration: true,
      ownerOrgId: resolved.membership.organization_id,
    });
    return HttpResponse.json(attachment, { status: 201 });
  }),

  http.get(`${BASE}/provider-profile/portfolio`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    return HttpResponse.json(rdb.listPortfolio(resolved.membership.organization_id));
  }),

  http.patch(`${BASE}/provider-profile/portfolio/:id`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();
    const body = (await request.json()) as { caption?: string | null };
    if ((body.caption ?? '').length > 200) {
      return HttpResponse.json(
        { error: { code: 'VALIDATION_FAILED', message: 'Подпись — не длиннее 200 символов', request_id: 'mock' } },
        { status: 422 },
      );
    }
    const updated = rdb.setPortfolioCaption(String(params.id), resolved.membership.organization_id, body.caption ?? null);
    if (!updated) return notFound();
    return HttpResponse.json(updated);
  }),

  http.delete(`${BASE}/provider-profile/portfolio/:id`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin') return forbidden();

    const own = rdb.listPortfolio(resolved.membership.organization_id).find((a) => a.id === String(params.id));
    if (!own) return notFound();
    rdb.deleteAttachment(String(params.id));
    return HttpResponse.json({ id: String(params.id), deleted: true });
  }),
];
