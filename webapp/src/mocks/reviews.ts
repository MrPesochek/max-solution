import { http, HttpResponse } from 'msw';
import * as db from './db';
import * as rdb from './requestsDb';
import {
  authenticate,
  badRequest,
  errorBody,
  forbidden,
  notFound,
  requireOrgMembership,
  unauthenticated,
  validationFailed,
} from './httpHelpers';
import type {
  Complaint,
  ComplaintCreateInput,
  ComplaintSubjectType,
  ModerationStatus,
  MyReview,
  ProviderReview,
  PublicReview,
  RequestReviewState,
  ReviewAppealInput,
  ReviewReplyInput,
  ReviewSubmitInput,
} from '../api/types';
import { tracked } from './mockState';

const BASE = '/app-api/v1';

let seq = 0;
function nextId(prefix: string): string {
  seq += 1;
  return `${prefix}_${seq.toString(36)}`;
}

interface DbReviewReply {
  id: string;
  reviewId: string;
  body: string;
  createdAt: string;
  updatedAt: string;
}

interface DbReview {
  id: string;
  requestId: string;
  assignmentId: string;
  customerOrgId: string;
  providerOrgId: string;
  rating: number;
  text: string | null;
  showCustomerName: boolean;
  moderationStatus: ModerationStatus;
  moderationReason: string | null;
  version: number;
  suspectedFraud: boolean;
  fraudReason: string | null;
  photoAttachmentIds: string[];
  published: { version: number; rating: number; text: string | null; publishedAt: string } | null;
  createdAt: string;
  updatedAt: string;
}

interface DbComplaint {
  id: string;
  subjectType: ComplaintSubjectType;
  filerOrgId: string;
  status: ModerationStatus;
  description: string | null;
  decisionReason: string | null;
  appealStatus: ModerationStatus | null;
  reviewId: string | null;
  createdAt: string;
  updatedAt: string;
  kind?: string | null;
  evidenceExtra?: Record<string, unknown>;
  reasonCode: string | null;
  withdrawn?: boolean;
}

const reviews = tracked(new Map<string, DbReview>());
const reviewsByRequest = tracked(new Map<string, string>());

function reviewKey(requestId: string, assignmentId: string): string {
  return `${requestId}:${assignmentId}`;
}
const replies = tracked(new Map<string, DbReviewReply>());
const complaints = tracked(new Map<string, DbComplaint>());

function now(): string {
  return new Date().toISOString();
}

function toMyReviewView(review: DbReview): MyReview {
  const reply = Array.from(replies.values()).find((r) => r.reviewId === review.id) ?? null;
  return {
    id: review.id,
    request_id: review.requestId,
    assignment_id: review.assignmentId,
    provider_organization_id: review.providerOrgId,
    rating: review.rating,
    text: review.text,
    show_customer_name: review.showCustomerName,
    moderation_status: review.moderationStatus,
    moderation_reason: review.moderationReason,
    version: review.version,
    suspected_fraud: review.suspectedFraud,
    reply: reply ? { id: reply.id, body: reply.body, created_at: reply.createdAt, updated_at: reply.updatedAt } : null,
    published: review.published
      ? { version: review.published.version, rating: review.published.rating, text: review.published.text, published_at: review.published.publishedAt }
      : null,
    photo_attachment_ids: review.photoAttachmentIds,
    created_at: review.createdAt,
    updated_at: review.updatedAt,
  };
}

function toPublicReviewView(review: DbReview): PublicReview | null {
  if (!review.published) return null;
  const reply = Array.from(replies.values()).find((r) => r.reviewId === review.id) ?? null;
  const customerOrg = db.getCurrentOrganization(review.customerOrgId);
  return {
    id: review.id,
    provider_organization_id: review.providerOrgId,
    rating: review.published.rating,
    text: review.published.text,
    author_display_name: review.showCustomerName ? (customerOrg?.name ?? review.customerOrgId) : 'Подтверждённый бизнес-клиент',
    reply: reply ? { id: reply.id, body: reply.body, created_at: reply.createdAt, updated_at: reply.updatedAt } : null,
    photo_attachment_ids: review.photoAttachmentIds,
    order_occurred_at: review.createdAt,
    published_at: review.published.publishedAt,
  };
}

function toComplaintView(c: DbComplaint): Complaint {
  return {
    id: c.id,
    subject_type: c.subjectType,
    status: (c.withdrawn ? 'withdrawn' : c.status) as ModerationStatus,
    description: c.description,
    decision_reason: c.decisionReason,
    appeal_status: c.appealStatus,
    created_at: c.createdAt,
    updated_at: c.updatedAt,
    subject_id: c.reviewId,
    review_id: c.reviewId,
    reason_code: (c.reasonCode ?? null) as Complaint['reason_code'],
  };
}

function toProviderReviewView(review: DbReview, orgId: string): ProviderReview | null {
  const base = toPublicReviewView(review);
  if (!base) return null;
  const complaint = Array.from(complaints.values())
    .filter((c) => c.reviewId === review.id && c.filerOrgId === orgId)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0];
  let requestNumber = 0;
  try {
    requestNumber = rdb.getRequestRaw(review.requestId).request_number;
  } catch {
    requestNumber = 1000 + Number.parseInt(review.id.split('_').at(-1) ?? '0', 36);
  }
  return {
    ...base,
    request_id: review.requestId,
    request_number: requestNumber,
    complaint: complaint ? { id: complaint.id, status: complaint.withdrawn ? 'withdrawn' : complaint.status } : null,
  };
}

export function listReviewsForOperator(status?: string) {
  return Array.from(reviews.values())
    .filter((r) => !status || status === 'all' || r.moderationStatus === status)
    .map((r) => ({
      review: r,
      hasReply: Array.from(replies.values()).some((reply) => reply.reviewId === r.id),
    }));
}

export function getReviewRecord(id: string): DbReview | null {
  return reviews.get(id) ?? null;
}

export function decideReviewByOperator(
  id: string,
  decision: 'published' | 'rejected' | 'removed',
  reason: string | null,
): DbReview | null {
  const review = reviews.get(id);
  if (!review) return null;
  review.moderationStatus = decision;
  review.moderationReason = reason;
  review.updatedAt = now();
  if (decision === 'published') {
    review.published = { version: review.version, rating: review.rating, text: review.text, publishedAt: now() };
  }
  if (decision === 'removed') review.published = null;
  return review;
}

export function setReviewFraudByOperator(id: string, suspected: boolean, reason: string): DbReview | null {
  const review = reviews.get(id);
  if (!review) return null;
  review.suspectedFraud = suspected;
  review.fraudReason = reason;
  review.updatedAt = now();
  return review;
}

export function listComplaintsForOperator(subjectType?: string, status?: string, kind?: string) {
  return Array.from(complaints.values()).filter(
    (c) =>
      (!subjectType || subjectType === 'all' || c.subjectType === subjectType) &&
      (!status || status === 'all' || c.status === status) &&
      (!kind || (c.kind ?? null) === kind),
  );
}

export function registerProfileAppeal(input: {
  id: string;
  filerOrgId: string;
  description: string;
  profileStatus: string;
  statusReason: string | null;
  createdAt: string;
}): void {
  complaints.set(input.id, {
    id: input.id,
    subjectType: 'provider_profile' as ComplaintSubjectType,
    filerOrgId: input.filerOrgId,
    status: 'pending',
    description: input.description,
    decisionReason: null,
    appealStatus: 'pending',
    reviewId: null,
    reasonCode: null,
    createdAt: input.createdAt,
    updatedAt: input.createdAt,
    kind: 'appeal',
    evidenceExtra: {
      profile_status_at_filing: input.profileStatus,
      status_reason_at_filing: input.statusReason,
    },
  });
}

export function getComplaintRecord(id: string): DbComplaint | null {
  return complaints.get(id) ?? null;
}

export function decideComplaintByOperator(
  id: string,
  decision: 'published' | 'rejected' | 'removed',
  reason: string | null,
): DbComplaint | null {
  const c = complaints.get(id);
  if (!c) return null;
  c.status = decision;
  c.decisionReason = reason;
  c.updatedAt = now();
  if (c.kind === 'appeal' && c.subjectType === 'provider_profile') {
    db.resolveProviderProfileAppeal(c.filerOrgId, c.id, decision, reason);
  }
  return c;
}

export { toComplaintView as reviewOperatorComplaintView, toMyReviewView as reviewOperatorMyReviewView };

function reviewEligibility(requestId: string): RequestReviewState['eligibility'] {
  const request = rdb.getRequestRaw(requestId);
  const assignmentId = rdb.latestAssignmentId(requestId);
  if (!request.accepted_at || !assignmentId) {
    return {
      can_submit: false,
      mode: null,
      reason_code: 'NO_ASSIGNMENT',
      reason_message: 'Отзыв доступен только по заявке с принятым назначением исполнителя',
      allow_no_show_complaint: false,
      assignment_id: null,
    };
  }
  const existing = reviewsByRequest.has(reviewKey(requestId, assignmentId));
  if (request.status === 'completion_reported' || request.status === 'closed') {
    return {
      can_submit: true,
      mode: existing ? 'edit' : 'create',
      reason_code: null,
      reason_message: null,
      allow_no_show_complaint: false,
      assignment_id: assignmentId,
    };
  }
  if (request.work_started_at) {
    return {
      can_submit: true,
      mode: existing ? 'edit' : 'needs_admission',
      reason_code: null,
      reason_message: 'Допуск отзыва решает модератор по истории взаимодействия',
      allow_no_show_complaint: false,
      assignment_id: assignmentId,
    };
  }
  return {
    can_submit: false,
    mode: null,
    reason_code: 'REVIEW_NOT_ALLOWED',
    reason_message: 'Отмена до начала работ не даёт права на отзыв о качестве ремонта',
    allow_no_show_complaint: Boolean(request.scheduled_at),
    assignment_id: assignmentId,
  };
}

export const reviewsHandlers = [
  http.get(`${BASE}/requests/:id/review`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const requestId = String(params.id);
    const eligibility = reviewEligibility(requestId);
    const assignmentId = new URL(request.url).searchParams.get('assignment_id') ?? eligibility.assignment_id;
    const reviewId = assignmentId ? reviewsByRequest.get(reviewKey(requestId, assignmentId)) : undefined;
    const review = reviewId ? reviews.get(reviewId) : null;
    const body: RequestReviewState = { review: review ? toMyReviewView(review) : null, eligibility };
    return HttpResponse.json(body);
  }),

  http.put(`${BASE}/requests/:id/review`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'customer_manager') return forbidden();

    const requestId = String(params.id);
    const eligibility = reviewEligibility(requestId);
    if (!eligibility.can_submit) return badRequest('Отзыв по этой заявке недоступен');

    const body = (await request.json()) as ReviewSubmitInput;
    if (body.rating < 1 || body.rating > 5) return badRequest('Оценка должна быть от 1 до 5');

    const assignmentId = body.assignment_id ?? eligibility.assignment_id;
    if (!assignmentId || assignmentId !== eligibility.assignment_id) return notFound();
    const providerOrgId = rdb.getAssignmentProviderOrgId(assignmentId);
    if (!providerOrgId) return notFound();

    const photoIds = body.photo_attachment_ids ?? [];
    const sensitive = photoIds.filter((id) => rdb.getAttachmentRecord(id)?.visibility_class === 'request_sensitive');
    if (sensitive.length > 0 && !body.confirm_sensitive) {
      return validationFailed(
        'confirm_sensitive',
        'Фото шильдика и документов публикуются только с явным подтверждением',
        'SENSITIVE_PHOTO_NOT_CONFIRMED',
      );
    }

    const key = reviewKey(requestId, assignmentId);
    let review = reviews.get(reviewsByRequest.get(key) ?? '');
    if (!review) {
      review = {
        id: nextId('review'),
        requestId,
        assignmentId,
        customerOrgId: resolved.membership.organization_id,
        providerOrgId,
        rating: body.rating,
        text: body.text ?? null,
        showCustomerName: body.show_customer_name,
        moderationStatus: 'pending',
        moderationReason: null,
        version: 1,
        suspectedFraud: false,
        fraudReason: null,
        photoAttachmentIds: body.photo_attachment_ids ?? [],
        published: null,
        createdAt: now(),
        updatedAt: now(),
      };
      reviews.set(review.id, review);
      reviewsByRequest.set(key, review.id);
      rdb.demoReviewRatings.set(review.requestId, review.rating);
    } else {
      review.rating = body.rating;
      rdb.demoReviewRatings.set(review.requestId, body.rating);
      review.text = body.text ?? null;
      review.showCustomerName = body.show_customer_name;
      review.photoAttachmentIds = body.photo_attachment_ids ?? [];
      review.moderationStatus = 'pending';
      review.moderationReason = null;
      review.version += 1;
      review.updatedAt = now();
    }
    return HttpResponse.json(toMyReviewView(review), { status: 201 });
  }),

  http.post(`${BASE}/reviews/:id/reply`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (resolved.membership.role !== 'provider_admin' && resolved.membership.role !== 'provider_dispatcher') return forbidden();

    const review = reviews.get(String(params.id));
    if (!review || review.providerOrgId !== resolved.membership.organization_id) return notFound();
    if (Array.from(replies.values()).some((r) => r.reviewId === review.id)) {
      return HttpResponse.json(errorBody('ALREADY_REPLIED', 'На отзыв уже дан ответ'), { status: 409 });
    }

    const body = (await request.json()) as ReviewReplyInput;
    if (!body.body.trim()) return badRequest('Введите текст ответа');
    const reply: DbReviewReply = { id: nextId('reply'), reviewId: review.id, body: body.body.trim(), createdAt: now(), updatedAt: now() };
    replies.set(reply.id, reply);
    return HttpResponse.json(reply, { status: 201 });
  }),

  http.post(`${BASE}/reviews/:id/appeal`, async ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const review = reviews.get(String(params.id));
    if (!review) return notFound();
    const orgId = resolved.membership.organization_id;
    if (orgId !== review.customerOrgId && orgId !== review.providerOrgId) return notFound();

    const body = (await request.json()) as ReviewAppealInput;
    if (!body.reason.trim()) return badRequest('Опишите причину обжалования');
    const reasonCodes = ['not_our_work', 'abuse_or_personal_data', 'customer_not_involved', 'other'];
    if (body.reason_code && !reasonCodes.includes(body.reason_code)) {
      return validationFailed('reason_code', 'Неизвестная причина');
    }

    const c: DbComplaint = {
      id: nextId('case'),
      subjectType: 'review',
      filerOrgId: orgId,
      status: 'pending',
      description: body.reason.trim(),
      decisionReason: null,
      appealStatus: 'pending',
      reviewId: review.id,
      reasonCode: body.reason_code ?? null,
      createdAt: now(),
      updatedAt: now(),
    };
    complaints.set(c.id, c);
    return HttpResponse.json(toComplaintView(c), { status: 201 });
  }),

  http.get(`${BASE}/providers/:providerId/reviews`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get('limit') ?? '10');
    const cursor = url.searchParams.get('cursor');

    const all = Array.from(reviews.values())
      .filter((r) => r.providerOrgId === String(params.providerId) && r.published)
      .sort((a, b) => (b.published?.publishedAt ?? '').localeCompare(a.published?.publishedAt ?? ''));

    const startIndex = cursor ? all.findIndex((r) => r.id === cursor) + 1 : 0;
    const page = all.slice(startIndex, startIndex + limit);
    const items = page.map(toPublicReviewView).filter((v): v is PublicReview => v !== null);
    const nextCursor = startIndex + limit < all.length ? page[page.length - 1]?.id ?? null : null;
    return HttpResponse.json({ items, next_cursor: nextCursor });
  }),

  http.post(`${BASE}/complaints`, async ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const body = (await request.json()) as ComplaintCreateInput;
    if (body.subject_type === 'no_show' && resolved.membership.role !== 'customer_manager') return forbidden();
    if (!body.description?.trim()) return badRequest('Опишите жалобу');

    if (body.subject_type === 'no_show') {
      const raw = rdb.getRequestRaw(body.target_id);
      if (!raw.scheduled_at) {
        return HttpResponse.json(
          errorBody('NO_SHOW_COMPLAINT_NOT_ALLOWED', 'Жалоба на неявку доступна только после согласованного выезда'),
          { status: 409 },
        );
      }
    }

    const c: DbComplaint = {
      id: nextId('case'),
      subjectType: body.subject_type as ComplaintSubjectType,
      filerOrgId: resolved.membership.organization_id,
      status: 'pending',
      description: body.description.trim(),
      decisionReason: null,
      appealStatus: null,
      reviewId: body.subject_type === 'review' ? body.target_id : null,
      reasonCode: null,
      createdAt: now(),
      updatedAt: now(),
    };
    complaints.set(c.id, c);
    return HttpResponse.json(toComplaintView(c), { status: 201 });
  }),

  http.get(`${BASE}/reviews/mine`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    if (!['provider_admin', 'provider_dispatcher'].includes(resolved.membership.role)) return forbidden();
    const orgId = resolved.membership.organization_id;
    const items = Array.from(reviews.values())
      .filter((r) => r.providerOrgId === orgId)
      .map((r) => toProviderReviewView(r, orgId))
      .filter((v): v is ProviderReview => v !== null);
    return HttpResponse.json({ items, next_cursor: null });
  }),

  http.post(`${BASE}/complaints/:id/withdraw`, ({ request, params }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;
    const c = complaints.get(String(params.id));
    if (!c || c.filerOrgId !== resolved.membership.organization_id) return notFound();
    if (c.withdrawn || c.status !== 'pending') {
      return HttpResponse.json(errorBody('COMPLAINT_CLOSED', 'По жалобе уже есть решение'), { status: 409 });
    }
    c.withdrawn = true;
    c.updatedAt = now();
    return HttpResponse.json(toComplaintView(c));
  }),

  http.get(`${BASE}/complaints`, ({ request }) => {
    const user = authenticate(request);
    if (!user) return unauthenticated();
    const resolved = requireOrgMembership(request, user);
    if ('error' in resolved) return resolved.error;

    const mine = Array.from(complaints.values())
      .filter((c) => c.filerOrgId === resolved.membership.organization_id)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    return HttpResponse.json({ items: mine.map(toComplaintView), next_cursor: null });
  }),
];

const seedPublished: DbReview = {
  id: nextId('review'),
  requestId: 'seed-request-demo-1',
  assignmentId: 'seed-assignment-demo-1',
  customerOrgId: db.demoSeed.demoCustomer.id,
  providerOrgId: db.demoSeed.demoActiveProvider.id,
  rating: 5,
  text: 'Приехали в тот же день, аккуратно поменяли компрессор. Рекомендуем.',
  showCustomerName: false,
  moderationStatus: 'published',
  moderationReason: null,
  version: 1,
  suspectedFraud: false,
  fraudReason: null,
  photoAttachmentIds: [],
  published: { version: 1, rating: 5, text: 'Приехали в тот же день, аккуратно поменяли компрессор. Рекомендуем.', publishedAt: now() },
  createdAt: now(),
  updatedAt: now(),
};
reviews.set(seedPublished.id, seedPublished);
reviewsByRequest.set(reviewKey(seedPublished.requestId, seedPublished.assignmentId), seedPublished.id);
replies.set(nextId('reply'), {
  id: nextId('reply'),
  reviewId: seedPublished.id,
  body: 'Спасибо за отзыв! Рады, что всё прошло гладко.',
  createdAt: now(),
  updatedAt: now(),
});

const seedPending: DbReview = {
  id: nextId('review'),
  requestId: 'seed-request-demo-2',
  assignmentId: 'seed-assignment-demo-2',
  customerOrgId: db.demoSeed.demoCustomer.id,
  providerOrgId: db.demoSeed.demoActiveProvider.id,
  rating: 2,
  text: 'Мастер задержался на два часа без предупреждения.',
  showCustomerName: true,
  moderationStatus: 'pending',
  moderationReason: null,
  version: 1,
  suspectedFraud: false,
  fraudReason: null,
  photoAttachmentIds: [],
  published: null,
  createdAt: now(),
  updatedAt: now(),
};
reviews.set(seedPending.id, seedPending);
reviewsByRequest.set(reviewKey(seedPending.requestId, seedPending.assignmentId), seedPending.id);
