import { http, HttpResponse } from 'msw';
import * as db from './db';
import {
  decideComplaintByOperator,
  decideReviewByOperator,
  getComplaintRecord,
  listComplaintsForOperator,
  listReviewsForOperator,
  setReviewFraudByOperator,
} from './reviews';
import { notFound, validationFailed, withOperator } from './operatorHandlers';

const BASE = '/operator-api/v1';

function reviewOperatorView(entry: ReturnType<typeof listReviewsForOperator>[number]) {
  const { review, hasReply } = entry;
  const customerOrg = db.getCurrentOrganization(review.customerOrgId);
  const providerOrg = db.getCurrentOrganization(review.providerOrgId);
  return {
    id: review.id,
    request_id: review.requestId,
    customer_organization_id: review.customerOrgId,
    customer_organization_name: customerOrg?.name ?? review.customerOrgId,
    provider_organization_id: review.providerOrgId,
    provider_organization_name: providerOrg?.name ?? review.providerOrgId,
    rating: review.rating,
    text: review.text,
    show_customer_name: review.showCustomerName,
    moderation_status: review.moderationStatus,
    moderation_reason: review.moderationReason,
    suspected_fraud: review.suspectedFraud,
    version: review.version,
    has_reply: hasReply,
    fraud_signals: review.suspectedFraud && review.fraudReason ? { operator_note: review.fraudReason } : {},
    created_at: review.createdAt,
    updated_at: review.updatedAt,
  };
}

function caseOperatorView(c: NonNullable<ReturnType<typeof getComplaintRecord>>) {
  const filerOrg = db.getCurrentOrganization(c.filerOrgId);
  return {
    id: c.id,
    subject_type: c.subjectType,
    status: c.status,
    filer_organization_id: c.filerOrgId,
    filer_organization_name: filerOrg?.name ?? c.filerOrgId,
    review_id: c.reviewId,
    provider_profile_id: c.kind === 'appeal' ? (db.getProviderProfile(c.filerOrgId)?.id ?? null) : null,
    attachment_id: null,
    assignment_id: null,
    evidence: { description: c.description, ...(c.kind ? { kind: c.kind } : {}), ...c.evidenceExtra },
    decision_reason: c.decisionReason,
    appeal_status: c.appealStatus,
    created_at: c.createdAt,
    updated_at: c.updatedAt,
  };
}

export const operatorReputationHandlers = [
  http.get(`${BASE}/reviews`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const status = url.searchParams.get('status') ?? undefined;
      const items = listReviewsForOperator(status).map(reviewOperatorView);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.get(`${BASE}/reviews/:id`, ({ request, params }) =>
    withOperator(() => {
      const entry = listReviewsForOperator().find((e) => e.review.id === String(params.id));
      if (!entry) return notFound();
      return HttpResponse.json(reviewOperatorView(entry));
    })({ request }),
  ),

  http.post(`${BASE}/reviews/:id/decision`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { decision: 'published' | 'rejected' | 'removed'; reason?: string | null };
      if ((body.decision === 'rejected' || body.decision === 'removed') && !body.reason?.trim()) {
        return validationFailed('Причина обязательна для отклонения и удаления');
      }
      const updated = decideReviewByOperator(String(params.id), body.decision, body.reason?.trim() || null);
      if (!updated) return notFound();
      const entry = listReviewsForOperator().find((e) => e.review.id === updated.id)!;
      return HttpResponse.json(reviewOperatorView(entry));
    })({ request }),
  ),

  http.post(`${BASE}/reviews/:id/fraud`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { suspected: boolean; reason: string };
      if (!body.reason?.trim()) return validationFailed('Комментарий обязателен');
      const updated = setReviewFraudByOperator(String(params.id), body.suspected, body.reason.trim());
      if (!updated) return notFound();
      const entry = listReviewsForOperator().find((e) => e.review.id === updated.id)!;
      return HttpResponse.json(reviewOperatorView(entry));
    })({ request }),
  ),

  http.get(`${BASE}/moderation-cases`, ({ request }) =>
    withOperator((req) => {
      const url = new URL(req.url);
      const subjectType = url.searchParams.get('subject_type') ?? undefined;
      const status = url.searchParams.get('status') ?? undefined;
      const kind = url.searchParams.get('kind') ?? undefined;
      const items = listComplaintsForOperator(subjectType, status, kind).map(caseOperatorView);
      return HttpResponse.json({ items, next_cursor: null });
    })({ request }),
  ),

  http.get(`${BASE}/moderation-cases/:id`, ({ request, params }) =>
    withOperator(() => {
      const record = getComplaintRecord(String(params.id));
      if (!record) return notFound();
      return HttpResponse.json(caseOperatorView(record));
    })({ request }),
  ),

  http.post(`${BASE}/moderation-cases/:id/decision`, async ({ request, params }) =>
    withOperator(async (req) => {
      const body = (await req.json()) as { decision: 'published' | 'rejected' | 'removed'; reason?: string | null };
      if ((body.decision === 'rejected' || body.decision === 'removed') && !body.reason?.trim()) {
        return validationFailed('Причина обязательна для отклонения и удаления');
      }
      const updated = decideComplaintByOperator(String(params.id), body.decision, body.reason?.trim() || null);
      if (!updated) return notFound();
      return HttpResponse.json({
        id: updated.id,
        subject_type: updated.subjectType,
        status: updated.status,
        description: updated.description,
        decision_reason: updated.decisionReason,
        appeal_status: updated.appealStatus,
        created_at: updated.createdAt,
        updated_at: updated.updatedAt,
      });
    })({ request }),
  ),
];
