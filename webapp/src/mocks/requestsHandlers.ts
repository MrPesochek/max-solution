import { http, HttpResponse } from 'msw';
import { blobToArrayBuffer, missingExpectedVersion, requireOrgMembership, validationFailed } from './httpHelpers';
import * as db from './db';
import * as rdb from './requestsDb';
import { DomainError } from './requestsDb';
import { getCached, setCached } from './idempotency';

const BASE = '/app-api/v1';

function messagePage<T extends { id: string }>(items: T[], request: Request) {
  const url = new URL(request.url);
  if (url.searchParams.get('direction') !== 'backward') return { items, next_cursor: null };
  const limit = Number(url.searchParams.get('limit') ?? '50');
  const cursor = url.searchParams.get('cursor');
  const end = cursor ? items.findIndex((m) => m.id === cursor) : items.length;
  const upTo = end < 0 ? items.length : end;
  const start = Math.max(0, upTo - limit);
  const page = items.slice(start, upTo);
  return { items: page, next_cursor: start > 0 && page.length > 0 ? page[0]!.id : null };
}

function errorBody(code: string, message: string, details?: Record<string, unknown>) {
  return { error: { code, message, request_id: `req_${Math.random().toString(36).slice(2)}`, details: details ?? {} } };
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

function fromDomainError(error: unknown) {
  if (error instanceof DomainError) {
    return HttpResponse.json(errorBody(error.code, error.message, error.details), { status: error.status });
  }
  throw error;
}

type Membership = db.DbMembership;

function authenticate(request: Request): db.DbUser | null {
  const header = request.headers.get('Authorization');
  const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;
  const session = db.findSession(token);
  if (!session) return null;
  return db.getUser(session.user_id);
}

const VERSIONED_ACTIONS = new Set([
  'submit-to-own-service',
  'request-approval',
  'return-to-draft',
  'cancel-draft',
  'revoke-assignment',
  'publish-search',
  'select-offer',
  'approve-visit-proposal',
  'reject-visit-proposal',
  'approve-repair-quote',
  'reject-repair-quote',
  'request-cancellation',
  'withdraw-cancellation',
  'force-cancellation',
  'confirm-completion',
  'reject-completion',
  'update-details',
  'accept',
  'decline',
  'withdraw',
  'propose-visit',
  'create-repair-quote',
  'start-work',
  'mark-en-route',
  'report-completion',
  'respond-cancellation',
  'warranty-decision',
  'field-worker',
]);

async function readJsonCopy(request: Request): Promise<unknown> {
  try {
    return await request.clone().json();
  } catch {
    return null;
  }
}

const CUSTOMER_ROLES = new Set(['customer_manager', 'customer_employee']);
const MANAGER_ONLY = new Set(['customer_manager']);
const PROVIDER_ROLES = new Set(['provider_admin', 'provider_dispatcher']);

function isCustomerSide(membership: Membership): boolean {
  return CUSTOMER_ROLES.has(membership.role);
}

function withOrg(
  handler: (ctx: { request: Request; user: db.DbUser; membership: Membership }) => Promise<Response> | Response,
) {
  return async ({ request }: { request: Request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    rdb.setActingUser(user.display_name);
    try {
      return await handler({ request, user, membership: resolved.membership });
    } catch (error) {
      return fromDomainError(error);
    } finally {
      rdb.setActingUser(null);
    }
  };
}

export const requestsHandlers = [

  http.patch(`${BASE}/requests/:id`, async ({ request }) => {
    const invalid = missingExpectedVersion(await readJsonCopy(request));
    if (invalid) return invalid;
    return undefined;
  }),

  http.post(`${BASE}/requests/:id/actions/:action`, async ({ request, params }) => {
    if (!VERSIONED_ACTIONS.has(String(params.action))) return undefined;
    const body = await readJsonCopy(request);
    const invalid = missingExpectedVersion(body);
    if (invalid) return invalid;
    if (params.action === 'select-offer') {
      const offerVersion = (body as { offer_version?: unknown }).offer_version;
      if (typeof offerVersion !== 'number' || !Number.isInteger(offerVersion) || offerVersion < 1) {
        return validationFailed('offer_version', 'Не указана версия предложения (offer_version)');
      }
    }
    return undefined;
  }),

  http.get(`${BASE}/requests`, ({ request }) =>
    withOrg(({ membership }) => {
      const url = new URL(request.url);
      const activeParam = url.searchParams.get('active');
      const cursor = url.searchParams.get('cursor');
      const limit = Number(url.searchParams.get('limit') ?? '50');
      const active = activeParam === null ? undefined : activeParam === 'true';

      if (!isCustomerSide(membership)) {
        const assignmentState = url.searchParams.getAll('assignment_state');
        const page = rdb.listRequestsForProvider(membership.organization_id, {
          assignmentState: assignmentState.length ? assignmentState : undefined,
          active,
          equipmentId: url.searchParams.get('equipment_id') ?? undefined,
          cursor,
          limit,
          membershipId: membership.id,
        });
        return HttpResponse.json(page);
      }

      const status = url.searchParams.getAll('status');
      const locationId = url.searchParams.get('location_id') ?? undefined;
      const page = rdb.listRequests(membership.organization_id, {
        status: status.length ? status : undefined,
        locationId,
        equipmentId: url.searchParams.get('equipment_id') ?? undefined,
        active,
        cursor,
        limit,
        forManager: MANAGER_ONLY.has(membership.role),
        membershipId: membership.id,
      });
      return HttpResponse.json(page);
    })({ request }),
  ),

  http.post(`${BASE}/requests`, async ({ request }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as {
        equipment_id: string;
        route?: string;
        urgency?: string;
        symptom_description?: string | null;
        error_code?: string | null;
      };
      const idempotencyKey = request.headers.get('Idempotency-Key');
      const cached = getCached('requests', idempotencyKey);
      if (cached) return HttpResponse.json(cached.body, { status: cached.status });
      const created = rdb.createDraft(membership.organization_id, membership.id, {
        equipment_id: body.equipment_id,
        route: body.route ?? 'own_service',
        urgency: body.urgency ?? 'normal',
        symptom_description: body.symptom_description ?? null,
        error_code: body.error_code ?? null,
      });
      const view = rdb.toCustomerView(created);
      setCached('requests', idempotencyKey, 201, view as never);
      return HttpResponse.json(view, { status: 201 });
    })({ request }),
  ),

  http.get(`${BASE}/requests/pending-approvals`, ({ request }) =>
    withOrg(({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden('Действие доступно только стороне заказчика');
      const manager = MANAGER_ONLY.has(membership.role);
      return HttpResponse.json(
        rdb.listPendingApprovals(membership.organization_id, {
          manager,
          locationIds: manager ? null : membership.location_ids,
        }),
      );
    })({ request }),
  ),

  http.get(`${BASE}/requests/:id`, ({ request, params }) =>
    withOrg(({ membership }) => {
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, isCustomerSide(membership));
      if (!('id' in view)) return HttpResponse.json(view);
      const providerOrgId = isCustomerSide(membership) ? null : membership.organization_id;
      return HttpResponse.json({
        ...view,
        unread_messages_count: rdb.unreadMessagesCount(String(params.id), membership.id, providerOrgId),
      });
    })({ request }),
  ),

  http.patch(`${BASE}/requests/:id`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as {
        equipment_id?: string | null;
        urgency?: string | null;
        symptom_description?: string | null;
        error_code?: string | null;
        photos_incomplete?: boolean | null;
        photos_incomplete_reason?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.updateDraft(String(params.id), membership.organization_id, body);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.get(`${BASE}/requests/:id/history`, ({ request, params }) =>
    withOrg(({ membership }) =>
      HttpResponse.json({
        items: rdb.requestHistory(String(params.id), isCustomerSide(membership) ? 'customer' : 'provider'),
        next_cursor: null,
      }),
    )({ request }),
  ),

  http.get(`${BASE}/requests/:id/offers`, ({ request, params }) =>
    withOrg(() => HttpResponse.json(rdb.listOffers(String(params.id))))({ request }),
  ),

  http.get(`${BASE}/requests/:id/visit-proposals`, ({ request, params }) =>
    withOrg(() => HttpResponse.json(rdb.listVisitProposals(String(params.id))))({ request }),
  ),

  http.get(`${BASE}/requests/:id/repair-quotes`, ({ request, params }) =>
    withOrg(() => HttpResponse.json(rdb.listRepairQuotes(String(params.id))))({ request }),
  ),

  http.get(`${BASE}/requests/:id/messages`, ({ request, params }) =>
    withOrg(({ membership }) => {
      const providerOrgId = isCustomerSide(membership) ? null : membership.organization_id;
      const items = rdb.listMessages(String(params.id), providerOrgId);
      return HttpResponse.json(messagePage(items, request));
    })({ request }),
  ),

  http.get(`${BASE}/requests/:id/offers/:offerId/messages`, ({ request, params }) =>
    withOrg(({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const thread = rdb.offerThreadProviderOrgId(String(params.id), String(params.offerId), membership.organization_id);
      return HttpResponse.json(messagePage(rdb.listThreadMessages(String(params.id), thread, 'customer'), request));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/offers/:offerId/messages`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as { body: string };
      const thread = rdb.offerThreadProviderOrgId(String(params.id), String(params.offerId), membership.organization_id);
      const message = rdb.postDialogMessage(String(params.id), 'customer_membership', membership.id, thread, body.body);
      return HttpResponse.json(message, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/messages/read`, ({ request, params }) =>
    withOrg(({ membership }) => {
      const providerOrgId = isCustomerSide(membership) ? null : membership.organization_id;
      return HttpResponse.json(rdb.markMessagesRead(String(params.id), membership.id, providerOrgId));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/messages`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      const body = (await request.json()) as { body: string; thread_provider_id?: string | null };
      const authorKind = isCustomerSide(membership) ? 'customer_membership' : 'provider_membership';
      const searching = rdb.getRequestStatus(String(params.id)) === 'searching';
      const threadProviderOrgId = !searching
        ? null
        : isCustomerSide(membership)
          ? (body.thread_provider_id ?? null)
          : membership.organization_id;
      const message = rdb.postMessage(String(params.id), authorKind, membership.id, threadProviderOrgId, body.body);
      return HttpResponse.json(message, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/submit-to-own-service`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as {
        photos_incomplete?: boolean;
        photos_incomplete_reason?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.submitToOwnService(
        String(params.id),
        membership.organization_id,
        Boolean(body.photos_incomplete),
        body.photos_incomplete_reason ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/request-approval`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as { comment?: string | null; expected_version?: number | null };
      const updated = rdb.requestApproval(String(params.id), membership.organization_id, body.comment ?? null, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/return-to-draft`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { comment: string; expected_version?: number | null };
      const updated = rdb.returnToDraft(String(params.id), membership.organization_id, body.comment, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/cancel-draft`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as { reason?: string | null; expected_version?: number | null };
      const updated = rdb.cancelDraft(String(params.id), membership.organization_id, body.reason ?? null, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/revoke-assignment`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; reason?: string | null; expected_version?: number | null };
      const updated = rdb.revokePendingAssignment(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.reason ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/preview-public-card`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        published_description?: string | null;
        district_id?: string | null;
        attachment_ids?: string[];
        confirm_sensitive?: boolean;
      };
      const preview = rdb.previewPublicCard(String(params.id), membership.organization_id, {
        published_description: body.published_description ?? null,
        district_id: body.district_id ?? null,
        attachment_ids: body.attachment_ids ?? [],
        confirm_sensitive: Boolean(body.confirm_sensitive),
      });
      return HttpResponse.json(preview);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/publish-search`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        published_description?: string | null;
        district_id?: string | null;
        attachment_ids?: string[];
        confirm_sensitive?: boolean;
        expected_version?: number | null;
      };
      const updated = rdb.publishSearch(
        String(params.id),
        membership.organization_id,
        {
          published_description: body.published_description ?? null,
          district_id: body.district_id ?? null,
          attachment_ids: body.attachment_ids ?? [],
          confirm_sensitive: Boolean(body.confirm_sensitive),
        },
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/select-offer`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { offer_id: string; offer_version: number; expected_version: number };
      const updated = rdb.selectOffer(
        String(params.id),
        membership.organization_id,
        body.offer_id,
        body.offer_version,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/update-details`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden('Действие доступно только руководителю заказчика');
      const body = (await request.json()) as {
        symptom_description?: string | null;
        urgency?: string | null;
        district_id?: string | null;
        published_description?: string | null;
        expected_version: number;
      };
      const updated = rdb.updateDetails(String(params.id), membership.organization_id, body, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/approve-visit-proposal`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        proposal_id: string;
        proposal_version: number;
        comment?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.respondVisitProposal(
        String(params.id),
        membership.organization_id,
        body.proposal_id,
        body.proposal_version,
        true,
        body.comment ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/reject-visit-proposal`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        proposal_id: string;
        proposal_version: number;
        comment?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.respondVisitProposal(
        String(params.id),
        membership.organization_id,
        body.proposal_id,
        body.proposal_version,
        false,
        body.comment ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/approve-repair-quote`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        quote_id: string;
        quote_version: number;
        comment?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.respondRepairQuote(
        String(params.id),
        membership.organization_id,
        body.quote_id,
        body.quote_version,
        true,
        body.comment ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/reject-repair-quote`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        quote_id: string;
        quote_version: number;
        comment?: string | null;
        expected_version?: number | null;
      };
      const updated = rdb.respondRepairQuote(
        String(params.id),
        membership.organization_id,
        body.quote_id,
        body.quote_version,
        false,
        body.comment ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/request-cancellation`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { target: string; reason?: string | null; expected_version?: number | null };
      const updated = rdb.requestCancellation(
        String(params.id),
        membership.organization_id,
        body.target === 'change_provider' ? 'change_provider' : 'cancel_request',
        body.reason ?? null,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/withdraw-cancellation`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { cancellation_id: string; expected_version?: number | null };
      const updated = rdb.withdrawCancellation(String(params.id), membership.organization_id, body.cancellation_id, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/force-cancellation`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { cancellation_id: string; expected_version?: number | null };
      const updated = rdb.forceCancellation(String(params.id), membership.organization_id, body.cancellation_id, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/confirm-completion`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { expected_version?: number | null };
      const updated = rdb.confirmCompletion(String(params.id), membership.organization_id, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/reject-completion`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!MANAGER_ONLY.has(membership.role)) return forbidden();
      const body = (await request.json()) as { reason: string; expected_version?: number | null };
      const updated = rdb.rejectCompletion(String(params.id), membership.organization_id, body.reason, body.expected_version);
      return HttpResponse.json(rdb.toCustomerView(updated));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/create-followup`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!isCustomerSide(membership)) return forbidden();
      const body = (await request.json()) as { urgency?: string | null };
      const created = rdb.createFollowup(String(params.id), membership.organization_id, body.urgency ?? null);
      return HttpResponse.json(rdb.toCustomerView(created), { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/accept`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; expected_version?: number | null };
      const { request: updated, assignment } = rdb.acceptAssignment(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.expected_version,
      );
      const disclose = assignment.state === 'accepted';
      return HttpResponse.json(rdb.toProviderView(updated, assignment, disclose));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/decline`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; reason: string; expected_version?: number | null };
      const { request: updated, assignment } = rdb.declineAssignment(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.reason,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toProviderView(updated, assignment, false));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/withdraw`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; reason: string; expected_version?: number | null };
      const { request: updated, assignment } = rdb.withdrawAssignment(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.reason,
        body.expected_version,
      );
      return HttpResponse.json(rdb.toProviderView(updated, assignment, true));
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/propose-visit`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        visit_window_start?: string | null;
        visit_window_end?: string | null;
        amount_minor?: number | null;
        currency?: string | null;
        vat_mode?: string | null;
        zero_cost_reason?: string | null;
        scope_description?: string | null;
        comment?: string | null;
        access_requirements?: string | null;
        valid_until?: string | null;
        expected_version?: number | null;
      };
      rdb.proposeVisit(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        {
          visit_window_start: body.visit_window_start ?? null,
          visit_window_end: body.visit_window_end ?? null,
          amount_minor: body.amount_minor ?? null,
          currency: body.currency ?? null,
          vat_mode: body.vat_mode ?? null,
          zero_cost_reason: body.zero_cost_reason ?? null,
          scope_description: body.scope_description ?? null,
          comment: body.comment ?? null,
          access_requirements: body.access_requirements ?? null,
          valid_until: body.valid_until ?? null,
        },
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/create-repair-quote`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        description_of_work: string;
        items?: { title: string; amount_minor: number }[] | null;
        amount_minor?: number | null;
        currency?: string | null;
        vat_mode?: string | null;
        zero_cost_reason?: string | null;
        valid_until?: string | null;
        warranty_terms?: string | null;
        expected_version?: number | null;
      };
      rdb.createRepairQuote(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        {
          description_of_work: body.description_of_work,
          items: body.items ?? null,
          amount_minor: body.amount_minor ?? null,
          currency: body.currency ?? null,
          vat_mode: body.vat_mode ?? null,
          zero_cost_reason: body.zero_cost_reason ?? null,
          valid_until: body.valid_until ?? null,
          warranty_terms: body.warranty_terms ?? null,
        },
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/start-work`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; expected_version?: number | null };
      rdb.startWork(String(params.id), membership.organization_id, body.assignment_id, body.expected_version);
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/mark-en-route`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { assignment_id: string; expected_version?: number | null };
      rdb.markEnRoute(String(params.id), membership.organization_id, body.assignment_id, body.expected_version);
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/report-completion`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        outcome: string;
        summary: string;
        expected_version?: number | null;
      };
      rdb.reportCompletion(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.outcome,
        body.summary,
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/respond-cancellation`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        cancellation_id: string;
        decision: string;
        comment?: string | null;
        expected_version?: number | null;
      };
      rdb.respondCancellation(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.cancellation_id,
        body.decision === 'accept' ? 'accepted' : 'disputed',
        body.comment ?? null,
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/warranty-decision`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        decision: string;
        comment?: string | null;
        expected_version?: number | null;
      };
      rdb.setWarrantyDecision(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        body.decision as never,
        body.comment ?? null,
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/actions/field-worker`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        assignment_id: string;
        membership_id?: string | null;
        display_name?: string | null;
        contact_phone?: string | null;
        expected_version?: number | null;
      };
      rdb.setFieldWorker(
        String(params.id),
        membership.organization_id,
        body.assignment_id,
        {
          membership_id: body.membership_id ?? null,
          display_name: body.display_name ?? null,
          contact_phone: body.contact_phone ?? null,
        },
        body.expected_version,
      );
      const view = rdb.getRequestForActor(String(params.id), membership.organization_id, false);
      return HttpResponse.json(view);
    })({ request }),
  ),

  http.get(`${BASE}/marketplace/requests`, ({ request }) =>
    withOrg(({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const items = rdb.listMarketplaceRequests(membership.organization_id);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.get(`${BASE}/marketplace/requests/:id`, ({ request, params }) =>
    withOrg(({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const card = rdb.getMarketplaceCard(String(params.id), membership.organization_id);
      return HttpResponse.json(card);
    })({ request }),
  ),

  http.get(`${BASE}/marketplace/requests/:id/messages`, ({ request, params }) =>
    withOrg(({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const items = rdb.listThreadMessages(String(params.id), membership.organization_id);
      return HttpResponse.json(messagePage(items, request));
    })({ request }),
  ),

  http.post(`${BASE}/marketplace/requests/:id/messages`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { body: string };
      const message = rdb.postDialogMessage(
        String(params.id),
        'provider_membership',
        membership.id,
        membership.organization_id,
        body.body,
      );
      return HttpResponse.json(message, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/marketplace/requests/:id/offers`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as {
        visit_window_start?: string | null;
        visit_window_end?: string | null;
        amount_minor?: number | null;
        currency?: string | null;
        vat_mode?: string | null;
        zero_cost_reason?: string | null;
        scope_description?: string | null;
        comment?: string | null;
        access_requirements?: string | null;
        valid_until?: string | null;
      };
      const offer = rdb.submitOffer(String(params.id), membership.organization_id, {
        visit_window_start: body.visit_window_start ?? null,
        visit_window_end: body.visit_window_end ?? null,
        amount_minor: body.amount_minor ?? null,
        currency: body.currency ?? null,
        vat_mode: body.vat_mode ?? null,
        zero_cost_reason: body.zero_cost_reason ?? null,
        scope_description: body.scope_description ?? null,
        comment: body.comment ?? null,
        access_requirements: body.access_requirements ?? null,
        valid_until: body.valid_until ?? null,
      });
      return HttpResponse.json(offer, { status: 201 });
    })({ request }),
  ),

  http.post(`${BASE}/offers/:id/withdraw`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      if (!PROVIDER_ROLES.has(membership.role)) return forbidden();
      const body = (await request.json()) as { expected_version?: number | null };
      const offer = rdb.withdrawOffer(String(params.id), membership.organization_id, body.expected_version);
      return HttpResponse.json(offer);
    })({ request }),
  ),

  http.post(`${BASE}/requests/:id/attachments`, async ({ request, params }) =>
    withOrg(async ({ membership }) => {
      const formData = await request.formData();
      const file = formData.get('file');
      const slot = formData.get('slot');
      const messageId = formData.get('message_id');
      if (!(file instanceof File)) {
        return HttpResponse.json(errorBody('VALIDATION_FAILED', 'Файл не передан'), { status: 400 });
      }
      if (isCustomerSide(membership) && (slot === 'before' || slot === 'after')) {
        return validationFailed('slot', 'Фото «до» и «после» добавляет исполнитель');
      }
      const idempotencyKey = request.headers.get('Idempotency-Key');
      const cached = getCached('attachments', idempotencyKey);
      if (cached) return HttpResponse.json(cached.body, { status: cached.status });
      const category = isCustomerSide(membership) ? 'request_private' : 'request_private';
      const attachment = rdb.addAttachment({
        ownerKind: typeof messageId === 'string' && messageId ? 'message' : 'request',
        requestId: String(params.id),
        messageId: typeof messageId === 'string' && messageId ? messageId : null,
        slot: typeof slot === 'string' ? slot : null,
        visibilityClass: category,
        mimeType: file.type || 'image/jpeg',
        blob: file,
      });
      setCached('attachments', idempotencyKey, 201, attachment as never);
      return HttpResponse.json(attachment, { status: 201 });
    })({ request }),
  ),

  http.get(`${BASE}/requests/:id/attachments`, ({ request, params }) =>
    withOrg(() => HttpResponse.json(rdb.listRequestAttachments(String(params.id))))({ request }),
  ),

  http.get(`${BASE}/attachments/:id/content`, ({ request, params }) =>
    withOrg(async () => {
      const record = rdb.getAttachmentRecord(String(params.id));
      if (!record) return notFound();
      const buffer = await blobToArrayBuffer(record.blob);
      return new HttpResponse(buffer, {
        status: 200,
        headers: { 'Content-Type': record.mime_type, 'Cache-Control': 'private, no-store' },
      });
    })({ request }),
  ),

  http.delete(`${BASE}/attachments/:id`, ({ request, params }) =>
    withOrg(() => {
      rdb.deleteAttachment(String(params.id));
      return new HttpResponse(null, { status: 204 });
    })({ request }),
  ),
];
