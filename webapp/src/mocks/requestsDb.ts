import type {
  Assignment,
  AssignmentState,
  Attachment,
  AttachmentProcessingState,
  AttachmentVisibilityClass,
  CancellationRequest,
  CancellationStatus,
  CancellationTarget,
  Equipment,
  FieldWorker,
  MarketplaceCard,
  Offer,
  OfferState,
  PublicCardPreview,
  RepairQuote,
  RepairQuoteStatus,
  RequestCustomer,
  RequestEquipmentSnapshot,
  RequestEvent,
  RequestFormerProvider,
  RequestListItem,
  RequestLocationSnapshot,
  RequestMessage,
  RequestProvider,
  RequestPublicCard,
  RequestRoute,
  RequestStatus,
  ServiceBinding,
  Urgency,
  VisitProposal,
  VisitProposalStatus,
  WarrantyDecision,
} from '../api/types';
import type { components } from '../api/schema';
import * as db from './db';
import { tracked } from './mockState';

type Schemas = components['schemas'];
type DeliveryStatus = Schemas['DeliveryStatusView'];
type CompletionReport = Schemas['CompletionReportView'];
type RepairQuoteItem = Schemas['RepairQuoteItemView'];

let counter = 1000;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}_${counter.toString(36)}`;
}

const now = () => new Date().toISOString();

interface DbAssignment {
  id: string;
  request_id: string;
  provider_org_id: string;
  route: RequestRoute;
  state: AssignmentState;
  offer_id: string | null;
  warranty_decision: WarrantyDecision;
  warranty_decision_comment: string | null;
  field_worker: FieldWorker | null;
  decline_reason: string | null;
  revoke_reason: string | null;
  withdrawal_reason: string | null;
  expires_at: string | null;
  responded_at: string | null;
  created_at: string;
  en_route_at?: string | null;
}

interface DbOffer {
  id: string;
  request_id: string;
  provider_org_id: string;
  version: number;
  visit_window_start: string | null;
  visit_window_end: string | null;
  amount_minor: number | null;
  currency: string | null;
  vat_mode: string | null;
  zero_cost_reason: string | null;
  scope_description: string | null;
  comment: string | null;
  access_requirements: string | null;
  valid_until: string;
  state: OfferState;
  superseded_by: string | null;
  created_at: string;
}

interface DbVisitProposal {
  id: string;
  request_id: string;
  assignment_id: string;
  version: number;
  visit_window_start: string | null;
  visit_window_end: string | null;
  amount_minor: number | null;
  currency: string | null;
  vat_mode: string | null;
  zero_cost_reason: string | null;
  scope_description: string | null;
  comment: string | null;
  access_requirements: string | null;
  valid_until: string;
  status: VisitProposalStatus;
  responded_at: string | null;
  response_comment: string | null;
  created_at: string;
}

interface DbRepairQuote {
  id: string;
  request_id: string;
  assignment_id: string;
  version: number;
  description_of_work: string;
  items: RepairQuoteItem[];
  amount_minor: number | null;
  currency: string | null;
  vat_mode: string | null;
  zero_cost_reason: string | null;
  valid_until: string;
  status: RepairQuoteStatus;
  responded_at: string | null;
  response_comment: string | null;
  created_at: string;
  warranty_terms?: string | null;
}

interface DbCancellation {
  id: string;
  request_id: string;
  assignment_id: string;
  target: CancellationTarget;
  previous_status: RequestStatus;
  status: CancellationStatus;
  reason: string | null;
  provider_response: string | null;
  disputed: boolean;
  dispute_deadline_at: string | null;
  resolution_kind: string | null;
  resolved_at: string | null;
  created_at: string;
}

interface DbMessage {
  id: string;
  request_id: string;
  author_kind: string;
  author_membership_id: string | null;
  thread_provider_org_id: string | null;
  assignment_id: string | null;
  body: string;
  created_at: string;
  author_label?: string | null;
  author_integration_client_id?: string | null;
}

interface DbEvent {
  id: string;
  request_id: string;
  occurred_at: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor_kind: string;
  actor_name: string | null;
  payload: Record<string, unknown>;
}

interface DbAttachment {
  id: string;
  owner_kind: string;
  request_id: string | null;
  message_id: string | null;
  slot: string | null;
  visibility_class: AttachmentVisibilityClass;
  processing_state: AttachmentProcessingState;
  rejected_reason: string | null;
  mime_type: string;
  byte_size: number;
  pixel_width: number | null;
  pixel_height: number | null;
  created_at: string;
  blob: Blob;
  publication_state: 'pending' | 'approved' | 'rejected' | null;
  owner_org_id: string | null;
  owner_ref: string | null;
  caption?: string | null;
}

interface DbRequest {
  id: string;
  request_number: number;
  customer_org_id: string;
  author_membership_id: string;
  location_id: string;
  equipment_id: string;
  route: RequestRoute;
  status: RequestStatus;
  urgency: Urgency;
  version: number;
  symptom_description: string | null;
  error_code: string | null;
  photos_incomplete: boolean;
  photos_incomplete_reason: string | null;
  closure_kind: string | null;
  cancellation_reason: string | null;
  disputed: boolean;
  submitted_at: string | null;
  accepted_at: string | null;
  scheduled_at: string | null;
  work_started_at: string | null;
  completion_reported_at: string | null;
  closed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
  equipment_snapshot: RequestEquipmentSnapshot | null;
  location_snapshot: RequestLocationSnapshot | null;
  current_assignment_id: string | null;
  public_card: RequestPublicCard | null;
  search_expires_at: string | null;
  matched_providers: number;
  published_source_ids?: string[];
}

const requests = tracked(new Map<string, DbRequest>());
const assignments = tracked(new Map<string, DbAssignment>());
const offers = tracked(new Map<string, DbOffer>());
const visitProposals = tracked(new Map<string, DbVisitProposal>());
const repairQuotes = tracked(new Map<string, DbRepairQuote>());
const cancellations = tracked(new Map<string, DbCancellation>());
const messages = tracked(new Map<string, DbMessage>());
const events = tracked(new Map<string, DbEvent[]>());
const attachments = tracked(new Map<string, DbAttachment>());

let requestNumberSeq = 2000;

export class DomainError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export const notFoundError = () => new DomainError(404, 'NOT_FOUND', 'Объект не найден');
export const forbiddenError = (message = 'Недостаточно прав') => new DomainError(403, 'FORBIDDEN', message);
const conflict = (code: string, message: string, details: Record<string, unknown> = {}) =>
  new DomainError(409, code, message, details);
const badRequest = (message: string, code = 'BAD_REQUEST') => new DomainError(400, code, message);

function checkVersion(current: number, expected: number | null | undefined): void {
  if (expected !== null && expected !== undefined && expected !== current) {
    throw conflict('VERSION_CONFLICT', 'Данные изменились — обновите экран', { current_version: current });
  }
}

export const demoRequestsSeed = {
  boundEquipmentId: (() => {
    const list = db.listEquipment(db.demoSeed.demoCustomer.id).items;
    return list.find((e) => e.equipment_category_id === 'cat_fridge')?.id ?? null;
  })(),
  unboundEquipmentId: (() => {
    const list = db.listEquipment(db.demoSeed.demoCustomer.id).items;
    return list.find((e) => e.equipment_category_id === 'cat_coffee')?.id ?? null;
  })(),
};

function equipmentSnapshot(equipmentId: string): RequestEquipmentSnapshot {
  const item = db.listEquipment(db.demoSeed.demoCustomer.id).items.find((e) => e.id === equipmentId);
  const categories = db.getEquipmentCategories().items;
  const category = categories.find((c) => c.id === item?.equipment_category_id);
  return {
    id: item?.id ?? equipmentId,
    category_id: item?.equipment_category_id ?? null,
    category_name: category?.name ?? null,
    brand: item?.brand ?? null,
    model: item?.model ?? null,
    serial_number: item?.serial_number ?? null,
    notes: item?.notes ?? null,
  };
}

function locationSnapshot(locationId: string): RequestLocationSnapshot {
  const location = db.getLocation(locationId, db.demoSeed.demoCustomer.id);
  return {
    id: location?.id ?? locationId,
    name: location?.name ?? null,
    city_id: location?.city_id ?? null,
    district_id: location?.district_id ?? null,
    address: location?.address ?? null,
    timezone: location?.timezone ?? null,
    contact_name: location?.contact_name ?? null,
    contact_phone: location?.contact_phone ?? null,
  };
}

function priceView(
  amountMinor: number | null,
  currency: string | null,
  vatMode: string | null,
  zeroCostReason: string | null,
) {
  return {
    amount_minor: amountMinor,
    currency,
    vat_mode: vatMode,
    zero_cost_reason: zeroCostReason,
    is_known: amountMinor !== null && amountMinor !== undefined,
  };
}

let actingUserName: string | null = null;

export function setActingUser(name: string | null): void {
  actingUserName = name;
}

function pushEvent(
  requestId: string,
  eventType: string,
  fromStatus: string | null,
  toStatus: string | null,
  actorKind: string,
  payload: Record<string, unknown> = {},
): void {
  const list = events.get(requestId) ?? [];
  list.push({
    id: nextId('evt'),
    request_id: requestId,
    occurred_at: now(),
    event_type: eventType,
    from_status: fromStatus,
    to_status: toStatus,
    actor_kind: actorKind,
    actor_name: actorKind.endsWith('_membership') ? actingUserName : null,
    payload,
  });
  events.set(requestId, list);
}

function touch(request: DbRequest): void {
  request.version += 1;
  request.updated_at = now();
}

const SEARCH_OPEN_STATUSES = new Set<RequestStatus>(['searching', 'awaiting_assignment_confirmation']);

function transition(
  request: DbRequest,
  eventType: string,
  toStatus: RequestStatus | null,
  actorKind: string,
  payload: Record<string, unknown> = {},
): void {
  const from = request.status;
  if (toStatus) request.status = toStatus;
  if (toStatus && request.public_card?.status === 'open' && !SEARCH_OPEN_STATUSES.has(toStatus)) {
    request.public_card = { ...request.public_card, status: 'closed', published_attachment_ids: [] };
    request.search_expires_at = null;
  }
  touch(request);
  pushEvent(request.id, eventType, from, toStatus ?? from, actorKind, payload);
}

function attachmentsFor(requestId: string): Attachment[] {
  return Array.from(attachments.values())
    .filter((a) => a.request_id === requestId)
    .map(toAttachmentView);
}

export function toAttachmentView(a: DbAttachment): Attachment {
  return {
    id: a.id,
    owner_kind: a.owner_kind,
    request_id: a.request_id,
    message_id: a.message_id,
    slot: a.slot,
    visibility_class: a.visibility_class,
    processing_state: a.processing_state,
    publication_state: a.publication_state,
    rejected_reason: a.rejected_reason,
    mime_type: a.mime_type,
    byte_size: a.byte_size,
    pixel_width: a.pixel_width,
    pixel_height: a.pixel_height,
    created_at: a.created_at,
    caption: a.owner_kind === 'provider_profile' ? (a.caption ?? null) : null,
  };
}

export function setPortfolioCaption(id: string, organizationId: string, caption: string | null): Attachment | null {
  const a = attachments.get(id);
  if (!a || a.owner_kind !== 'provider_profile' || a.owner_org_id !== organizationId) return null;
  const text = caption?.trim() || null;
  if (a.caption !== text) {
    a.caption = text;
    a.publication_state = 'pending';
    db.unpublishGalleryItem(a.id);
  }
  return toAttachmentView(a);
}

function disclosesContacts(a: DbAssignment): boolean {
  return a.state === 'accepted' || a.state === 'completed' || (a.state === 'pending' && a.route === 'own_service');
}

function assignmentView(a: DbAssignment, forCustomer = false): Assignment {
  return {
    id: a.id,
    request_id: a.request_id,
    provider_organization_id: a.provider_org_id,
    provider_display_name: db.getCurrentOrganization(a.provider_org_id)?.name ?? null,
    provider_contact_phone: forCustomer && disclosesContacts(a) ? db.getOrganizationPhone(a.provider_org_id) : null,
    route: a.route,
    state: a.state,
    warranty_decision: a.warranty_decision,
    warranty_decision_comment: a.warranty_decision_comment,
    field_worker: a.field_worker,
    decline_reason: a.decline_reason,
    revoke_reason: a.revoke_reason,
    withdrawal_reason: a.withdrawal_reason,
    expires_at: a.expires_at,
    responded_at: a.responded_at,
    created_at: a.created_at,
    en_route_at: a.en_route_at ?? null,
    provider: forCustomer ? providerRatingSummary(a.provider_org_id) : null,
    reminder_at: forCustomer ? reminderAt(a) : null,
  };
}

function providerRatingSummary(providerOrgId: string) {
  const summary = db.getOfferProviderSummary(providerOrgId);
  if (!summary) return null;
  return { ...summary, reviews_count: summary.reviews_count };
}

function reminderAt(a: DbAssignment): string | null {
  const request = requests.get(a.request_id);
  if (!request || a.route !== 'own_service' || a.state !== 'pending' || request.status !== 'awaiting_provider') {
    return null;
  }
  const seconds = request.urgency === 'critical' ? 30 * 60 : 2 * 3600;
  return new Date(Date.parse(a.created_at) + seconds * 1000).toISOString();
}

function offerView(o: DbOffer): Offer {
  return {
    id: o.id,
    request_id: o.request_id,
    provider_organization_id: o.provider_org_id,
    version: o.version,
    visit_window_start: o.visit_window_start,
    visit_window_end: o.visit_window_end,
    price: priceView(o.amount_minor, o.currency, o.vat_mode, o.zero_cost_reason),
    scope_description: o.scope_description,
    comment: o.comment,
    access_requirements: o.access_requirements,
    valid_until: o.valid_until,
    state: o.state,
    created_at: o.created_at,
    provider: db.getOfferProviderSummary(o.provider_org_id),
  };
}

function visitProposalView(p: DbVisitProposal): VisitProposal {
  return {
    id: p.id,
    assignment_id: p.assignment_id,
    version: p.version,
    visit_window_start: p.visit_window_start,
    visit_window_end: p.visit_window_end,
    price: priceView(p.amount_minor, p.currency, p.vat_mode, p.zero_cost_reason),
    scope_description: p.scope_description,
    comment: p.comment,
    access_requirements: p.access_requirements,
    valid_until: p.valid_until,
    status: p.status,
    responded_at: p.responded_at,
    response_comment: p.response_comment,
    created_at: p.created_at,
  };
}

function repairQuoteView(q: DbRepairQuote): RepairQuote {
  return {
    id: q.id,
    assignment_id: q.assignment_id,
    version: q.version,
    description_of_work: q.description_of_work,
    price: priceView(q.amount_minor, q.currency, q.vat_mode, q.zero_cost_reason),
    items: q.items,
    valid_until: q.valid_until,
    status: q.status,
    responded_at: q.responded_at,
    response_comment: q.response_comment,
    created_at: q.created_at,
    warranty_terms: q.warranty_terms ?? null,
  };
}

function cancellationView(c: DbCancellation): CancellationRequest {
  return {
    id: c.id,
    assignment_id: c.assignment_id,
    target: c.target,
    previous_status: c.previous_status,
    status: c.status,
    reason: c.reason,
    provider_response: c.provider_response,
    disputed: c.disputed,
    dispute_deadline_at: c.dispute_deadline_at,
    resolution_kind: c.resolution_kind,
    resolved_at: c.resolved_at,
    created_at: c.created_at,
  };
}

export function messageView(m: DbMessage, viewerSide: 'customer' | 'provider' = 'customer'): RequestMessage {
  const afterAssignment = m.assignment_id !== null;
  let displayName: string | null = null;
  let organization: string | null = null;
  let label: string | null = null;
  if (m.author_kind === 'integration_client') {
    organization = m.author_integration_client_id ? db.integrationClientOrgName(m.author_integration_client_id) : null;
    displayName = organization ? `CRM ${organization}` : null;
    label = viewerSide === 'provider' || afterAssignment ? (m.author_label ?? null) : null;
  } else if (m.author_membership_id) {
    const author = db.membershipAuthor(m.author_membership_id);
    const authorSide = m.author_kind === 'customer_membership' ? 'customer' : 'provider';
    if (author && authorSide === viewerSide) {
      displayName = author.name;
      organization = author.organization;
    } else if (author && viewerSide === 'customer') {
      displayName = afterAssignment ? author.name : null;
      organization = author.organization;
    } else if (author && afterAssignment) {
      displayName = author.name;
      organization = author.organization;
    }
  }
  return {
    id: m.id,
    request_id: m.request_id,
    author_kind: m.author_kind,
    author_membership_id: m.author_membership_id,
    thread_provider_id: m.thread_provider_org_id,
    body: m.body,
    created_at: m.created_at,
    author_display_name: displayName,
    author_organization_name: organization,
    author_label: label,
    delivery: viewerSide === 'customer' ? messageDelivery(m) : null,
  };
}

function messageDelivery(m: DbMessage): DeliveryStatus | null {
  if (m.author_kind !== 'customer_membership') return null;
  const request = requests.get(m.request_id);
  const assignment = request ? currentAssignment(request) : null;
  const providerOrgId = m.thread_provider_org_id ?? assignment?.provider_org_id ?? null;
  if (!providerOrgId || !db.hasActiveApiKey(providerOrgId)) return null;
  return { state: 'delivered', channel: 'crm', delivered_at: m.created_at, last_attempt_at: m.created_at, next_attempt_at: null };
}

function actorDisplayName(e: DbEvent, viewerSide: 'customer' | 'provider'): string | null {
  const request = requests.get(e.request_id);
  const assignment = request ? currentAssignment(request) : null;
  const providerName = assignment ? db.getOrganizationName(assignment.provider_org_id) : null;
  if (e.actor_kind === 'integration_client') return providerName ? `CRM ${providerName}` : null;
  if (e.actor_kind === 'operator') return 'Оператор платформы';
  if (e.actor_kind === 'customer_membership') {
    if (viewerSide === 'customer') return e.actor_name;
    return request && assignment && disclosesContacts(assignment) ? db.getOrganizationName(request.customer_org_id) : null;
  }
  if (e.actor_kind === 'provider_membership') {
    return viewerSide === 'provider' ? e.actor_name : providerName;
  }
  return null;
}

function eventView(e: DbEvent, viewerSide: 'customer' | 'provider' = 'customer'): RequestEvent {
  return {
    id: e.id,
    occurred_at: e.occurred_at,
    event_type: e.event_type,
    from_status: e.from_status,
    to_status: e.to_status,
    actor_kind: e.actor_kind,
    actor_display_name: actorDisplayName(e, viewerSide),
    payload: e.payload,
  };
}

const deliveryOverrides = tracked(new Map<string, DeliveryStatus>());

export function setDeliveryOverride(requestId: string, delivery: DeliveryStatus | null): void {
  if (delivery) deliveryOverrides.set(requestId, delivery);
  else deliveryOverrides.delete(requestId);
}

function deliveryView(assignment: DbAssignment | null): DeliveryStatus | null {
  if (!assignment || !['pending', 'accepted', 'completed'].includes(assignment.state)) return null;
  const override = deliveryOverrides.get(assignment.request_id);
  if (override) return override;
  if (!db.hasActiveApiKey(assignment.provider_org_id)) return { state: 'none', channel: 'app' };
  return {
    state: 'delivered',
    channel: 'crm',
    delivered_at: assignment.created_at,
    last_attempt_at: assignment.created_at,
    next_attempt_at: null,
  };
}

const REPORT_SLOTS = new Set(['before', 'after']);

function completionReportView(request: DbRequest, assignment: DbAssignment | null): CompletionReport | null {
  if (!assignment) return null;
  const reported = (events.get(request.id) ?? [])
    .filter((e) => e.event_type === 'request.completion_reported' && e.payload.assignment_id === assignment.id)
    .at(-1);
  if (!reported) return null;
  const photos = attachmentsFor(request.id).filter((a) => a.slot && REPORT_SLOTS.has(a.slot));
  return {
    outcome: typeof reported.payload.outcome === 'string' ? reported.payload.outcome : null,
    summary: typeof reported.payload.summary === 'string' ? reported.payload.summary : null,
    reported_at: reported.occurred_at,
    photos_before: photos.filter((a) => a.slot === 'before'),
    photos_after: photos.filter((a) => a.slot === 'after'),
  };
}

function currentAssignment(request: DbRequest): DbAssignment | null {
  return request.current_assignment_id ? (assignments.get(request.current_assignment_id) ?? null) : null;
}

function expireVisitProposalsIfDue(requestId: string): void {
  const nowMs = Date.now();
  for (const p of visitProposals.values()) {
    if (p.request_id === requestId && p.status === 'pending' && new Date(p.valid_until).getTime() <= nowMs) {
      p.status = 'expired';
    }
  }
}

function expireRepairQuotesIfDue(requestId: string): void {
  const nowMs = Date.now();
  for (const q of repairQuotes.values()) {
    if (q.request_id === requestId && q.status === 'pending' && new Date(q.valid_until).getTime() <= nowMs) {
      q.status = 'expired';
    }
  }
}

function expireOffersIfDue(requestId: string): void {
  const nowMs = Date.now();
  for (const o of offers.values()) {
    if (o.request_id === requestId && o.state === 'active' && new Date(o.valid_until).getTime() <= nowMs) {
      o.state = 'expired';
    }
  }
}

export function toCustomerView(request: DbRequest): RequestCustomer {
  expireVisitProposalsIfDue(request.id);
  expireRepairQuotesIfDue(request.id);
  expireOffersIfDue(request.id);
  const assignment = currentAssignment(request);
  const proposals = Array.from(visitProposals.values()).filter((p) => p.request_id === request.id);
  const quotes = Array.from(repairQuotes.values()).filter((q) => q.request_id === request.id);
  const cancellation = assignment
    ? Array.from(cancellations.values())
        .filter((c) => c.assignment_id === assignment.id)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    : undefined;
  return {
    id: request.id,
    request_number: request.request_number,
    status: request.status,
    route: request.route,
    urgency: request.urgency,
    version: request.version,
    symptom_description: request.symptom_description,
    error_code: request.error_code,
    equipment: request.equipment_snapshot ?? equipmentSnapshot(request.equipment_id),
    location: request.location_snapshot ?? locationSnapshot(request.location_id),
    photos_incomplete: request.photos_incomplete,
    photos_incomplete_reason: request.photos_incomplete_reason,
    closure_kind: request.closure_kind,
    cancellation_reason: request.cancellation_reason,
    disputed: request.disputed,
    submitted_at: request.submitted_at,
    accepted_at: request.accepted_at,
    scheduled_at: request.scheduled_at,
    work_started_at: request.work_started_at,
    completion_reported_at: request.completion_reported_at,
    closed_at: request.closed_at,
    cancelled_at: request.cancelled_at,
    created_at: request.created_at,
    assignment: assignment ? assignmentView(assignment, true) : null,
    visit_proposals: proposals.map(visitProposalView),
    repair_quotes: quotes.map(repairQuoteView),
    cancellation: cancellation ? cancellationView(cancellation) : null,
    attachments: attachmentsFor(request.id),
    equipment_category_name: (request.equipment_snapshot ?? equipmentSnapshot(request.equipment_id)).category_name ?? null,
    approver_name: request.status === 'approval_required' ? db.firstManagerName(request.customer_org_id) : null,
    unread_messages_count: null,
    delivery: deliveryView(assignment),
    completion_report: completionReportView(request, assignment),
    search: request.public_card
      ? {
          published: request.public_card.status === 'open',
          matched_providers: request.matched_providers,
          search_expires_at: request.public_card.status === 'open' ? request.search_expires_at : null,
          public_card: request.public_card,
          published_source_attachment_ids: request.published_source_ids ?? [],
        }
      : null,
  };
}

export function toProviderView(request: DbRequest, assignment: DbAssignment, disclose: boolean): RequestProvider {
  const proposals = Array.from(visitProposals.values()).filter((p) => p.request_id === request.id);
  const quotes = Array.from(repairQuotes.values()).filter((q) => q.request_id === request.id);
  const cancellation = Array.from(cancellations.values())
    .filter((c) => c.assignment_id === assignment.id)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  let equipment = request.equipment_snapshot ?? equipmentSnapshot(request.equipment_id);
  let location = request.location_snapshot ?? locationSnapshot(request.location_id);
  if (!disclose) {
    equipment = { ...equipment, serial_number: null, notes: null };
    location = { ...location, name: null, address: null, contact_name: null, contact_phone: null };
  }
  return {
    id: request.id,
    request_number: request.request_number,
    status: request.status,
    route: request.route,
    urgency: request.urgency,
    version: request.version,
    symptom_description: request.symptom_description,
    error_code: request.error_code,
    equipment,
    location,
    contacts_disclosed: disclose,
    photos_incomplete: request.photos_incomplete,
    photos_incomplete_reason: request.photos_incomplete_reason,
    submitted_at: request.submitted_at,
    created_at: request.created_at,
    assignment: assignmentView(assignment),
    visit_proposals: proposals.map(visitProposalView),
    repair_quotes: quotes.map(repairQuoteView),
    cancellation: cancellation ? cancellationView(cancellation) : null,
    attachments: attachmentsFor(request.id),
    equipment_category_name: equipment.category_name ?? null,
    unread_messages_count: null,
    completion_report: completionReportView(request, assignment),
    customer_org_name: disclose ? db.getOrganizationName(request.customer_org_id) : null,
  };
}

function pendingDecision(request: DbRequest) {
  const nowIso = now();
  const proposal = Array.from(visitProposals.values()).find(
    (p) => p.request_id === request.id && p.status === 'pending' && p.valid_until > nowIso,
  );
  if (proposal) {
    return {
      kind: 'visit_proposal' as const,
      amount_minor: proposal.amount_minor,
      currency: proposal.currency,
      respond_by: proposal.valid_until,
      offers_count: null,
    };
  }
  const quote = Array.from(repairQuotes.values()).find(
    (q) => q.request_id === request.id && q.status === 'pending' && q.valid_until > nowIso,
  );
  if (quote) {
    return {
      kind: 'repair_quote' as const,
      amount_minor: quote.amount_minor,
      currency: quote.currency,
      respond_by: quote.valid_until,
      offers_count: null,
    };
  }
  if (request.status === 'searching') {
    const active = Array.from(offers.values()).filter(
      (o) => o.request_id === request.id && o.state === 'active' && o.valid_until > nowIso,
    );
    if (active.length) {
      const priced = active.filter((o) => o.amount_minor !== null);
      const cheapest = priced.sort((a, b) => (a.amount_minor ?? 0) - (b.amount_minor ?? 0))[0];
      return {
        kind: 'offers' as const,
        amount_minor: cheapest?.amount_minor ?? null,
        currency: cheapest?.currency ?? null,
        respond_by: active.map((o) => o.valid_until).sort()[0] ?? null,
        offers_count: active.length,
      };
    }
  }
  const disputed = Array.from(cancellations.values()).find(
    (c) => c.request_id === request.id && c.status === 'disputed',
  );
  if (disputed) {
    return {
      kind: 'cancellation_disputed' as const,
      amount_minor: null,
      currency: null,
      respond_by: disputed.dispute_deadline_at ?? null,
      offers_count: null,
    };
  }
  const byStatus = ({ approval_required: 'approval', completion_reported: 'completion_reported', action_required: 'action_required' } as const)[
    request.status as 'approval_required' | 'completion_reported' | 'action_required'
  ];
  return byStatus
    ? { kind: byStatus, amount_minor: null, currency: null, respond_by: null, offers_count: null }
    : null;
}

export function toListItem(
  request: DbRequest,
  forManager = false,
  forProviderOrgId: string | null = null,
  membershipId: string | null = null,
): RequestListItem {
  const assignment = currentAssignment(request);
  const location = db.getLocation(request.location_id, request.customer_org_id);
  const snapshot = request.equipment_snapshot ?? equipmentSnapshot(request.equipment_id);
  const title = [snapshot.brand, snapshot.model].filter(Boolean).join(' ') || null;
  const disclosed = !forProviderOrgId || (assignment !== null && disclosesContacts(assignment));
  return {
    id: request.id,
    request_number: request.request_number,
    status: request.status,
    route: request.route,
    urgency: request.urgency,
    version: request.version,
    location_id: request.location_id,
    location_name: disclosed ? (location?.name ?? null) : null,
    equipment_title: title,
    symptom_description: request.symptom_description,
    assignment_id: assignment?.id ?? null,
    assignment_state: assignment?.state ?? null,
    provider_organization_id: assignment?.provider_org_id ?? null,
    updated_at: request.updated_at,
    created_at: request.created_at,
    equipment_id: request.equipment_id,
    equipment_category_name: snapshot.category_name ?? null,
    equipment_brand: snapshot.brand ?? null,
    equipment_model: snapshot.model ?? null,
    pending_decision: forManager ? pendingDecision(request) : null,
    customer_org_name: forProviderOrgId && disclosed ? db.getOrganizationName(request.customer_org_id) : null,
    contract_number:
      forProviderOrgId && disclosed
        ? db.confirmedContractNumber(request.equipment_id, request.customer_org_id, forProviderOrgId)
        : null,
    ...listItemExtras(request, assignment, forProviderOrgId, membershipId),
  };
}

function listItemExtras(
  request: DbRequest,
  assignment: DbAssignment | null,
  forProviderOrgId: string | null,
  membershipId: string | null,
) {
  const approved = assignment
    ? Array.from(visitProposals.values())
        .filter((p) => p.assignment_id === assignment.id && p.status === 'approved')
        .sort((a, b) => b.version - a.version)[0]
    : undefined;
  const workerVisible =
    assignment !== null && (forProviderOrgId !== null || assignment.state === 'accepted' || assignment.state === 'completed');
  const visible = visibleMessages(request.id, forProviderOrgId);
  const location = request.location_snapshot ?? locationSnapshot(request.location_id);
  return {
    visit_window_start: approved?.visit_window_start ?? null,
    visit_window_end: approved?.visit_window_end ?? null,
    timezone: location.timezone ?? null,
    en_route_at: assignment?.en_route_at ?? null,
    field_worker_name: workerVisible ? (assignment?.field_worker?.display_name ?? null) : null,
    unread_messages_count: membershipId
      ? unreadMessagesCount(request.id, membershipId, forProviderOrgId)
      : visible.filter((m) => (m.author_kind === 'customer_membership') === (forProviderOrgId !== null)).length,
    last_message_at: visible.at(-1)?.created_at ?? null,
    my_review_rating: forProviderOrgId ? null : (demoReviewRatings.get(request.id) ?? null),
    closed_at: request.closed_at,
    cancelled_at: request.cancelled_at,
  };
}

export const demoReviewRatings = tracked(new Map<string, number>());

const ACTIVE_STATUSES: RequestStatus[] = [
  'draft',
  'approval_required',
  'awaiting_provider',
  'searching',
  'awaiting_assignment_confirmation',
  'accepted',
  'scheduled',
  'in_progress',
  'completion_reported',
  'action_required',
  'cancellation_pending',
];

export function listRequests(
  customerOrgId: string,
  filters: {
    status?: string[];
    locationId?: string;
    equipmentId?: string;
    active?: boolean;
    assignmentState?: string[];
    cursor?: string | null;
    limit: number;
    forManager?: boolean;
    membershipId?: string;
  },
): { items: RequestListItem[]; next_cursor: string | null } {
  let items = Array.from(requests.values()).filter((r) => r.customer_org_id === customerOrgId);
  if (filters.status?.length) items = items.filter((r) => filters.status!.includes(r.status));
  if (filters.locationId) items = items.filter((r) => r.location_id === filters.locationId);
  if (filters.equipmentId) items = items.filter((r) => r.equipment_id === filters.equipmentId);
  if (filters.active !== undefined) {
    items = items.filter((r) => ACTIVE_STATUSES.includes(r.status) === filters.active);
  }
  if (filters.assignmentState?.length) {
    items = items.filter((r) => {
      const assignment = currentAssignment(r);
      return assignment ? filters.assignmentState!.includes(assignment.state) : false;
    });
  }
  items = items.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const startIndex = filters.cursor ? items.findIndex((r) => r.id === filters.cursor) + 1 : 0;
  const page = items.slice(startIndex, startIndex + filters.limit);
  const nextCursor = startIndex + filters.limit < items.length ? (page[page.length - 1]?.id ?? null) : null;
  return {
    items: page.map((r) => toListItem(r, filters.forManager ?? false, null, filters.membershipId ?? null)),
    next_cursor: nextCursor,
  };
}

const PENDING_REQUEST_STATUS_KIND: Record<string, string> = {
  approval_required: 'draft_approval',
  completion_reported: 'completion_reported',
  action_required: 'action_required',
};

export interface PendingApprovalItemView {
  kind: string;
  request: { id: string; request_number: number; status: string; version: number };
  object?: { id: string; version: number | null } | null;
  due_at: string | null;
  amount_minor?: number | null;
  currency?: string | null;
  thread_provider_id?: string | null;
}

const TERMINAL_STATUSES: RequestStatus[] = ['closed', 'cancelled'];

function unansweredQuestions(orgRequests: DbRequest[]): PendingApprovalItemView[] {
  const items: PendingApprovalItemView[] = [];
  for (const r of orgRequests) {
    if (TERMINAL_STATUSES.includes(r.status)) continue;
    const lastByThread = new Map<string | null, DbMessage>();
    for (const m of visibleMessages(r.id, null)) lastByThread.set(m.thread_provider_org_id, m);
    for (const [thread, last] of lastByThread) {
      if (last.author_kind === 'customer_membership') continue;
      if (thread !== null && r.status !== 'searching') continue;
      items.push({
        kind: 'question',
        request: { id: r.id, request_number: r.request_number, status: r.status, version: r.version },
        object: { id: last.id, version: null },
        due_at: null,
        thread_provider_id: thread,
      });
    }
  }
  return items;
}

export function listPendingApprovals(
  customerOrgId: string,
  options: { manager: boolean; locationIds: string[] | null } = { manager: true, locationIds: null },
): PendingApprovalItemView[] {
  const orgRequests = Array.from(requests.values()).filter(
    (r) =>
      r.customer_org_id === customerOrgId &&
      (options.locationIds === null || options.locationIds.includes(r.location_id)),
  );
  const items: PendingApprovalItemView[] = unansweredQuestions(orgRequests);
  if (!options.manager) return items;
  const requestRef = (r: DbRequest) => ({ id: r.id, request_number: r.request_number, status: r.status, version: r.version });

  for (const r of orgRequests) {
    const kind = PENDING_REQUEST_STATUS_KIND[r.status];
    if (kind) items.push({ kind, request: requestRef(r), object: null, due_at: null });
  }

  const nowIso = now();
  for (const proposal of visitProposals.values()) {
    const request = requests.get(proposal.request_id);
    if (!request || request.customer_org_id !== customerOrgId) continue;
    if (proposal.status !== 'pending' || proposal.valid_until <= nowIso) continue;
    items.push({
      kind: 'visit_proposal',
      request: requestRef(request),
      object: { id: proposal.id, version: proposal.version },
      due_at: proposal.valid_until,
      amount_minor: proposal.amount_minor,
      currency: proposal.currency,
    });
  }
  for (const quote of repairQuotes.values()) {
    const request = requests.get(quote.request_id);
    if (!request || request.customer_org_id !== customerOrgId) continue;
    if (quote.status !== 'pending' || quote.valid_until <= nowIso) continue;
    items.push({
      kind: 'repair_quote',
      request: requestRef(request),
      object: { id: quote.id, version: quote.version },
      due_at: quote.valid_until,
      amount_minor: quote.amount_minor,
      currency: quote.currency,
    });
  }
  for (const cancellation of cancellations.values()) {
    const request = requests.get(cancellation.request_id);
    if (!request || request.customer_org_id !== customerOrgId) continue;
    if (cancellation.status !== 'disputed') continue;
    items.push({ kind: 'cancellation_disputed', request: requestRef(request), object: null, due_at: null });
  }

  return items;
}

export function getRequestForActor(
  requestId: string,
  actorOrgId: string,
  actorOrgIsCustomer: boolean,
): RequestCustomer | RequestProvider | RequestFormerProvider {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();

  if (actorOrgIsCustomer) {
    if (request.customer_org_id !== actorOrgId) throw notFoundError();
    return toCustomerView(request);
  }

  const assignment = currentAssignment(request);
  if (assignment && assignment.provider_org_id === actorOrgId) {
    const disclose = assignment.state === 'accepted' || request.status === 'awaiting_provider';
    return toProviderView(request, assignment, disclose);
  }
  const former = Array.from(assignments.values())
    .filter((a) => a.request_id === requestId && a.provider_org_id === actorOrgId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (former) return { request_id: requestId, assignment: assignmentView(former) };
  throw notFoundError();
}

export function latestAssignmentId(requestId: string): string | null {
  const request = requests.get(requestId);
  if (request?.current_assignment_id) return request.current_assignment_id;
  const list = Array.from(assignments.values()).filter((a) => a.request_id === requestId);
  return list.length ? list[list.length - 1]!.id : null;
}

export function getAssignmentProviderOrgId(assignmentId: string | null): string | null {
  if (!assignmentId) return null;
  return assignments.get(assignmentId)?.provider_org_id ?? null;
}

export function getRequestRaw(requestId: string): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  return request;
}

export function createDraft(
  customerOrgId: string,
  authorMembershipId: string,
  input: { equipment_id: string; route: string; urgency: string; symptom_description: string | null; error_code: string | null },
): DbRequest {
  const equipment = db.getEquipmentItem(input.equipment_id, customerOrgId);
  if (!equipment) throw notFoundError();
  requestNumberSeq += 1;
  const record: DbRequest = {
    id: nextId('req'),
    request_number: requestNumberSeq,
    customer_org_id: customerOrgId,
    author_membership_id: authorMembershipId,
    location_id: equipment.location_id,
    equipment_id: equipment.id,
    route: input.route === 'marketplace' ? 'marketplace' : 'own_service',
    status: 'draft',
    urgency: (input.urgency as Urgency) || 'normal',
    version: 1,
    symptom_description: input.symptom_description,
    error_code: input.error_code,
    photos_incomplete: false,
    photos_incomplete_reason: null,
    closure_kind: null,
    cancellation_reason: null,
    disputed: false,
    submitted_at: null,
    accepted_at: null,
    scheduled_at: null,
    work_started_at: null,
    completion_reported_at: null,
    closed_at: null,
    cancelled_at: null,
    created_at: now(),
    updated_at: now(),
    equipment_snapshot: null,
    location_snapshot: null,
    current_assignment_id: null,
    public_card: null,
    search_expires_at: null,
    matched_providers: 0,
  };
  requests.set(record.id, record);
  pushEvent(record.id, 'request.created', null, 'draft', 'customer_membership');
  return record;
}

export function updateDraft(
  requestId: string,
  customerOrgId: string,
  input: {
    equipment_id?: string | null;
    urgency?: string | null;
    symptom_description?: string | null;
    error_code?: string | null;
    photos_incomplete?: boolean | null;
    photos_incomplete_reason?: string | null;
    expected_version?: number | null;
  },
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (!['draft', 'approval_required'].includes(request.status)) {
    throw conflict('INVALID_TRANSITION', 'Заявку уже нельзя редактировать как черновик');
  }
  checkVersion(request.version, input.expected_version);
  if (input.equipment_id) {
    const equipment = db.getEquipmentItem(input.equipment_id, customerOrgId);
    if (!equipment) throw notFoundError();
    request.equipment_id = equipment.id;
    request.location_id = equipment.location_id;
  }
  if (input.urgency) request.urgency = input.urgency as Urgency;
  if (input.symptom_description !== undefined && input.symptom_description !== null) {
    request.symptom_description = input.symptom_description;
  }
  if (input.error_code !== undefined && input.error_code !== null) request.error_code = input.error_code;
  if (typeof input.photos_incomplete === 'boolean') request.photos_incomplete = input.photos_incomplete;
  if (input.photos_incomplete_reason !== undefined) {
    request.photos_incomplete_reason = input.photos_incomplete_reason?.trim() || null;
  }
  if (!request.photos_incomplete) request.photos_incomplete_reason = null;
  transition(request, 'request.updated', null, 'customer_membership');
  return request;
}

export function cancelDraft(
  requestId: string,
  customerOrgId: string,
  reason: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (!['draft', 'approval_required'].includes(request.status)) {
    throw conflict('INVALID_TRANSITION', 'Заявка уже отправлена: используйте запрос отмены');
  }
  checkVersion(request.version, expectedVersion);
  request.cancellation_reason = reason;
  transition(request, 'request.cancelled', 'cancelled', 'customer_membership', { reason });
  return request;
}

export function requestApproval(
  requestId: string,
  customerOrgId: string,
  comment: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (request.route !== 'marketplace') {
    throw conflict('INVALID_ROUTE', 'Согласование руководителя нужно для внешней заявки');
  }
  checkVersion(request.version, expectedVersion);
  transition(request, 'request.approval_requested', 'approval_required', 'customer_membership', { comment });
  return request;
}

export function returnToDraft(
  requestId: string,
  customerOrgId: string,
  comment: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  transition(request, 'request.returned_to_draft', 'draft', 'customer_membership', { comment });
  return request;
}

function confirmedBindingFor(equipmentId: string, customerOrgId: string): ServiceBinding | null {
  const page = db.listBindings(customerOrgId, 'customer', { equipmentId, status: 'confirmed' });
  const first = page.items[0];
  return first && 'provider' in first ? (first as ServiceBinding) : null;
}

function ensureProviderBindingOrThrow(requestRecord: DbRequest): { providerOrgId: string } {
  const binding = confirmedBindingFor(requestRecord.equipment_id, requestRecord.customer_org_id);
  if (!binding || !binding.provider.organization_id) {
    throw conflict('SERVICE_BINDING_REQUIRED', 'Для оборудования нет подтверждённой привязки своего сервиса');
  }
  return { providerOrgId: binding.provider.organization_id };
}

export function submitToOwnService(
  requestId: string,
  customerOrgId: string,
  photosIncomplete: boolean,
  photosIncompleteReason: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (photosIncomplete && !photosIncompleteReason) {
    throw badRequest('Укажите причину отсутствия фото', 'VALIDATION_FAILED');
  }
  checkVersion(request.version, expectedVersion);
  if (currentAssignment(request)) {
    throw conflict('ASSIGNMENT_ALREADY_ACTIVE', 'По заявке уже есть активное назначение');
  }
  const { providerOrgId } = ensureProviderBindingOrThrow(request);

  fixSnapshots(request);
  request.route = 'own_service';
  request.photos_incomplete = photosIncomplete;
  request.photos_incomplete_reason = photosIncompleteReason;

  const assignment: DbAssignment = {
    id: nextId('asg'),
    request_id: request.id,
    provider_org_id: providerOrgId,
    route: 'own_service',
    state: 'pending',
    offer_id: null,
    warranty_decision: 'not_stated',
    warranty_decision_comment: null,
    field_worker: null,
    decline_reason: null,
    revoke_reason: null,
    withdrawal_reason: null,
    expires_at: null,
    responded_at: null,
    created_at: now(),
  };
  assignments.set(assignment.id, assignment);
  request.current_assignment_id = assignment.id;
  request.submitted_at = now();
  transition(request, 'request.submitted', 'awaiting_provider', 'customer_membership', {
    assignment_id: assignment.id,
  });
  return request;
}

function fixSnapshots(request: DbRequest): void {
  if (!request.equipment_snapshot) request.equipment_snapshot = equipmentSnapshot(request.equipment_id);
  if (!request.location_snapshot) request.location_snapshot = locationSnapshot(request.location_id);
}

export function revokePendingAssignment(
  requestId: string,
  customerOrgId: string,
  assignmentId: string,
  reason: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = assignments.get(assignmentId);
  if (!assignment || assignment.request_id !== requestId) throw notFoundError();
  if (assignment.state !== 'pending') {
    throw conflict('ASSIGNMENT_NOT_PENDING', 'Назначение уже не ожидает ответа');
  }
  assignment.state = 'revoked';
  assignment.revoke_reason = reason;
  if (request.current_assignment_id === assignmentId) request.current_assignment_id = null;
  transition(request, 'assignment.revoked', 'action_required', 'customer_membership', {
    assignment_id: assignmentId,
    reason,
  });
  return request;
}

const WITHHELD_FIELDS = [
  'location.address',
  'location.name',
  'location.contact_name',
  'location.contact_phone',
  'equipment.serial_number',
  'equipment.notes',
  'warranty_documents',
  'service_history',
];

function countMatchingProviders(categoryId: string | null | undefined): number {
  if (categoryId === 'cat_coffee') return 0;
  return 2;
}

export function previewPublicCard(
  requestId: string,
  customerOrgId: string,
  input: { published_description: string | null; district_id: string | null; attachment_ids: string[]; confirm_sensitive: boolean },
): PublicCardPreview {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  const snapshot = request.equipment_snapshot ?? equipmentSnapshot(request.equipment_id);
  const location = request.location_snapshot ?? locationSnapshot(request.location_id);
  const existing = request.public_card;
  const districtId = input.district_id ?? existing?.district_id ?? location.district_id;
  const card: RequestPublicCard = {
    request_id: request.id,
    request_number: request.request_number,
    equipment_category_id: snapshot.category_id ?? '',
    equipment_category_name: snapshot.category_name,
    brand: snapshot.brand,
    model: snapshot.model,
    city_id: location.city_id ?? '',
    district_id: districtId,
    ...db.cityAndDistrictNames(location.city_id, districtId),
    urgency: request.urgency,
    published_description:
      input.published_description || existing?.published_description || request.symptom_description,
    published_attachment_ids: input.attachment_ids,
    status: 'open',
    published_at: now(),
    search_expires_at: null,
  };
  const binding = confirmedBindingFor(request.equipment_id, customerOrgId);
  return {
    public_card: card,
    withheld_fields: WITHHELD_FIELDS,
    matched_providers: countMatchingProviders(snapshot.category_id),
    existing_binding: binding
      ? {
          service_binding_id: binding.id,
          provider_organization_id: binding.provider.organization_id,
          provider_name: binding.provider.name,
          status: binding.status,
        }
      : null,
  };
}

export function publishSearch(
  requestId: string,
  customerOrgId: string,
  input: { published_description: string | null; district_id: string | null; attachment_ids: string[]; confirm_sensitive: boolean },
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  fixSnapshots(request);
  const preview = previewPublicCard(requestId, customerOrgId, input);
  request.matched_providers = preview.matched_providers;
  if (preview.matched_providers === 0) {
    request.public_card = { ...preview.public_card, status: 'closed', published_attachment_ids: [] };
    request.published_source_ids = [];
    request.search_expires_at = null;
    request.submitted_at = request.submitted_at ?? now();
    transition(request, 'SearchFoundNoProviders', 'action_required', 'customer_membership', {
      matched_providers: 0,
    });
    return request;
  }
  request.route = 'marketplace';
  request.public_card = preview.public_card;
  request.published_source_ids = [...input.attachment_ids];
  request.search_expires_at = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
  request.submitted_at = request.submitted_at ?? now();
  transition(request, 'request.published', 'searching', 'customer_membership', {
    matched_providers: preview.matched_providers,
  });
  return request;
}

export function listMarketplaceRequests(providerOrgId: string): Schemas['MarketplaceListItemView'][] {
  return Array.from(requests.values())
    .filter((r) => r.status === 'searching' && r.public_card)
    .map((r) => {
      const thread = visibleMessages(r.id, providerOrgId).filter((m) => m.thread_provider_org_id === providerOrgId);
      const last = thread.at(-1);
      return {
        ...r.public_card!,
        offers_count: Array.from(offers.values()).filter((o) => o.request_id === r.id && o.state === 'active').length,
        has_open_question: last !== undefined && last.author_kind !== 'customer_membership',
        has_clarification: last?.author_kind === 'customer_membership',
      };
    });
}

export function getMarketplaceCard(requestId: string, providerOrgId: string): MarketplaceCard {
  const request = requests.get(requestId);
  if (!request || !request.public_card || request.status !== 'searching') throw notFoundError();
  const myOffers = Array.from(offers.values())
    .filter((o) => o.request_id === requestId && o.provider_org_id === providerOrgId)
    .map(offerView);
  return { card: request.public_card, my_offers: myOffers };
}

export function submitOffer(
  requestId: string,
  providerOrgId: string,
  input: {
    visit_window_start: string | null;
    visit_window_end: string | null;
    amount_minor: number | null;
    currency: string | null;
    vat_mode: string | null;
    zero_cost_reason: string | null;
    scope_description: string | null;
    comment: string | null;
    access_requirements: string | null;
    valid_until: string | null;
  },
): Offer {
  const request = requests.get(requestId);
  if (!request || request.status !== 'searching') throw notFoundError();
  const previous = Array.from(offers.values()).filter(
    (o) => o.request_id === requestId && o.provider_org_id === providerOrgId,
  );
  const offer: DbOffer = {
    id: nextId('off'),
    request_id: requestId,
    provider_org_id: providerOrgId,
    version: previous.reduce((max, o) => Math.max(max, o.version), 0) + 1,
    visit_window_start: input.visit_window_start,
    visit_window_end: input.visit_window_end,
    amount_minor: input.amount_minor,
    currency: input.amount_minor !== null ? (input.currency ?? 'RUB') : null,
    vat_mode: input.vat_mode,
    zero_cost_reason: input.zero_cost_reason,
    scope_description: input.scope_description,
    comment: input.comment,
    access_requirements: input.access_requirements,
    valid_until: input.valid_until ?? new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    state: 'active',
    superseded_by: null,
    created_at: now(),
  };
  for (const row of previous) {
    if (row.state !== 'active') continue;
    row.state = 'closed';
    row.superseded_by = offer.id;
  }
  offers.set(offer.id, offer);
  pushEvent(requestId, 'offer.submitted', null, null, 'provider_membership', { offer_id: offer.id });
  return offerView(offer);
}

export function withdrawOffer(offerId: string, providerOrgId: string, expectedVersion: number | null | undefined): Offer {
  const offer = offers.get(offerId);
  if (!offer || offer.provider_org_id !== providerOrgId) throw notFoundError();
  const request = requests.get(offer.request_id);
  if (request) checkVersion(request.version, expectedVersion);
  if (offer.state !== 'active') throw conflict('OFFER_NOT_ACTIVE', 'Предложение уже неактивно', { state: offer.state });
  offer.state = 'withdrawn';
  if (request) transition(request, 'offer.withdrawn', null, 'provider_membership', { offer_id: offerId });
  return offerView(offer);
}

export function listOffers(requestId: string): Offer[] {
  return Array.from(offers.values())
    .filter((o) => o.request_id === requestId)
    .map((o) => {
      if (o.state === 'active' && new Date(o.valid_until).getTime() <= Date.now()) o.state = 'expired';
      return offerView(o);
    });
}

function confirmSeconds(urgency: Urgency): number {
  return urgency === 'critical' ? 30 * 60 : 2 * 60 * 60;
}

export function selectOffer(
  requestId: string,
  customerOrgId: string,
  offerId: string,
  offerVersion: number,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const offer = offers.get(offerId);
  if (!offer || offer.request_id !== requestId) throw notFoundError();
  if (offer.version !== offerVersion) {
    throw conflict('OFFER_NOT_CURRENT', 'Условия предложения изменились, откройте актуальную версию', {
      offer_version: offer.version,
    });
  }
  if (offer.superseded_by) throw conflict('OFFER_NOT_CURRENT', 'Исполнитель обновил предложение');
  if (offer.state === 'active' && new Date(offer.valid_until).getTime() <= Date.now()) {
    offer.state = 'expired';
    throw conflict('OFFER_EXPIRED', 'Срок предложения истёк');
  }
  if (offer.state !== 'active') throw conflict('OFFER_NOT_ACTIVE', 'Предложение недоступно для выбора');
  if (currentAssignment(request)) {
    throw conflict('ASSIGNMENT_ALREADY_ACTIVE', 'По заявке уже есть активное назначение');
  }
  offer.state = 'selected';
  const assignment: DbAssignment = {
    id: nextId('asg'),
    request_id: requestId,
    provider_org_id: offer.provider_org_id,
    route: 'marketplace',
    state: 'pending',
    offer_id: offer.id,
    warranty_decision: 'not_stated',
    warranty_decision_comment: null,
    field_worker: null,
    decline_reason: null,
    revoke_reason: null,
    withdrawal_reason: null,
    expires_at: new Date(Date.now() + confirmSeconds(request.urgency) * 1000).toISOString(),
    responded_at: null,
    created_at: now(),
  };
  assignments.set(assignment.id, assignment);
  request.current_assignment_id = assignment.id;
  transition(request, 'offer.selected', 'awaiting_assignment_confirmation', 'customer_membership', {
    offer_id: offerId,
    assignment_id: assignment.id,
  });
  return request;
}

const DETAIL_FIELDS = ['symptom_description', 'urgency', 'district_id', 'published_description'] as const;

export function updateDetails(
  requestId: string,
  customerOrgId: string,
  input: {
    symptom_description?: string | null;
    urgency?: string | null;
    district_id?: string | null;
    published_description?: string | null;
  },
  expectedVersion: number,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  if (request.status !== 'action_required') {
    throw conflict('INVALID_TRANSITION', 'Изменить условия можно только в заявке, которой нужно решение');
  }
  const card = request.public_card;
  if (!card && (input.district_id !== undefined || input.published_description !== undefined)) {
    throw new DomainError(422, 'VALIDATION_FAILED', 'Район и описание карточки меняются только у публиковавшейся заявки', {
      field: input.district_id !== undefined ? 'district_id' : 'published_description',
    });
  }
  if (input.urgency !== undefined && input.urgency !== null && !['critical', 'urgent', 'normal'].includes(input.urgency)) {
    throw new DomainError(422, 'VALIDATION_FAILED', 'Неизвестная срочность', { field: 'urgency' });
  }
  const changes: Record<string, { from: unknown; to: unknown }> = {};
  const current: Record<(typeof DETAIL_FIELDS)[number], unknown> = {
    symptom_description: request.symptom_description,
    urgency: request.urgency,
    district_id: card?.district_id ?? null,
    published_description: card?.published_description ?? null,
  };
  for (const field of DETAIL_FIELDS) {
    const next = input[field];
    if (next === undefined || next === current[field]) continue;
    changes[field] = { from: current[field], to: next };
  }
  if ('symptom_description' in changes) request.symptom_description = input.symptom_description ?? null;
  if ('urgency' in changes && input.urgency) request.urgency = input.urgency as Urgency;
  if (card) {
    request.public_card = {
      ...card,
      urgency: request.urgency,
      district_id: 'district_id' in changes ? (input.district_id ?? null) : card.district_id,
      published_description:
        'published_description' in changes ? (input.published_description ?? null) : card.published_description,
    };
  }
  transition(request, 'RequestDetailsUpdated', null, 'customer_membership', {
    changed_fields: Object.keys(changes),
    changes,
  });
  return request;
}

function requireAssignment(requestId: string, assignmentId: string, providerOrgId: string): DbAssignment {
  const assignment = assignments.get(assignmentId);
  if (!assignment || assignment.request_id !== requestId || assignment.provider_org_id !== providerOrgId) {
    throw notFoundError();
  }
  return assignment;
}

export function acceptAssignment(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  expectedVersion: number | null | undefined,
): { request: DbRequest; assignment: DbAssignment } {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  if (assignment.state === 'pending' && assignment.expires_at && new Date(assignment.expires_at).getTime() <= Date.now()) {
    throw conflict('ASSIGNMENT_EXPIRED', 'Срок подтверждения назначения истёк');
  }
  if (assignment.state !== 'pending') {
    throw conflict('ASSIGNMENT_NOT_ACTIVE', 'Назначение уже не ожидает ответа');
  }
  assignment.state = 'accepted';
  assignment.responded_at = now();
  if (request.status === 'awaiting_assignment_confirmation') {
    request.accepted_at = now();
    transition(request, 'assignment.confirmed', 'accepted', 'provider_membership', { assignment_id: assignmentId });
  } else {
    request.accepted_at = now();
    transition(request, 'request.accepted', 'accepted', 'provider_membership', { assignment_id: assignmentId });
  }
  return { request, assignment };
}

export function declineAssignment(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  reason: string,
  expectedVersion: number | null | undefined,
): { request: DbRequest; assignment: DbAssignment } {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  if (assignment.state !== 'pending') throw conflict('ASSIGNMENT_NOT_ACTIVE', 'Назначение уже не ожидает ответа');
  assignment.state = 'declined';
  assignment.decline_reason = reason;
  assignment.responded_at = now();
  if (request.current_assignment_id === assignmentId) request.current_assignment_id = null;
  transition(request, 'request.declined', 'action_required', 'provider_membership', {
    assignment_id: assignmentId,
    reason,
  });
  return { request, assignment };
}

export function withdrawAssignment(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  reason: string,
  expectedVersion: number | null | undefined,
): { request: DbRequest; assignment: DbAssignment } {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  if (!['accepted', 'scheduled'].includes(request.status)) {
    throw conflict('INVALID_TRANSITION', 'Отказ доступен только после принятия и до начала работ');
  }
  assignment.state = 'withdrawn';
  assignment.withdrawal_reason = reason;
  if (request.current_assignment_id === assignmentId) request.current_assignment_id = null;
  transition(request, 'assignment.withdrawn', 'action_required', 'provider_membership', {
    assignment_id: assignmentId,
    reason,
  });
  return { request, assignment };
}

export function setWarrantyDecision(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  decision: WarrantyDecision,
  comment: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  assignment.warranty_decision = decision;
  assignment.warranty_decision_comment = comment;
  pushEvent(requestId, 'assignment.warranty_decision', null, null, 'provider_membership', {
    assignment_id: assignmentId,
    decision,
  });
  touch(request);
  return request;
}

export function setFieldWorker(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  input: { membership_id: string | null; display_name: string | null; contact_phone: string | null },
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  if (input.membership_id) {
    const staff = db.listStaff(providerOrgId, 'provider').items.find((s) => s.id === input.membership_id);
    assignment.field_worker = {
      membership_id: input.membership_id,
      display_name: staff?.user.display_name ?? input.display_name,
      contact_phone: input.contact_phone,
      stated_by_company: false,
    };
  } else {
    assignment.field_worker = {
      membership_id: null,
      display_name: input.display_name,
      contact_phone: input.contact_phone,
      stated_by_company: true,
    };
  }
  pushEvent(requestId, 'assignment.field_worker_set', null, null, 'provider_membership', {
    assignment_id: assignmentId,
  });
  touch(request);
  return request;
}

export function listRequestsForProvider(
  providerOrgId: string,
  filters: {
    assignmentState?: string[];
    active?: boolean;
    equipmentId?: string;
    cursor?: string | null;
    limit: number;
    membershipId?: string;
  },
): { items: RequestListItem[]; next_cursor: string | null } {
  let items = Array.from(requests.values()).filter((r) => {
    const assignment = currentAssignment(r);
    return assignment?.provider_org_id === providerOrgId;
  });
  if (filters.equipmentId) items = items.filter((r) => r.equipment_id === filters.equipmentId);
  if (filters.assignmentState?.length) {
    items = items.filter((r) => {
      const assignment = currentAssignment(r);
      return assignment ? filters.assignmentState!.includes(assignment.state) : false;
    });
  }
  if (filters.active !== undefined) {
    items = items.filter((r) => ACTIVE_STATUSES.includes(r.status) === filters.active);
  }
  items = items.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const startIndex = filters.cursor ? items.findIndex((r) => r.id === filters.cursor) + 1 : 0;
  const page = items.slice(startIndex, startIndex + filters.limit);
  const nextCursor = startIndex + filters.limit < items.length ? (page[page.length - 1]?.id ?? null) : null;
  return {
    items: page.map((r) => toListItem(r, false, providerOrgId, filters.membershipId ?? null)),
    next_cursor: nextCursor,
  };
}

function nextVersionFor(map: Map<string, { request_id: string; assignment_id: string; version: number }>, requestId: string, assignmentId: string): number {
  const existing = Array.from(map.values()).filter((v) => v.request_id === requestId && v.assignment_id === assignmentId);
  return existing.length ? Math.max(...existing.map((v) => v.version)) + 1 : 1;
}

export function proposeVisit(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  input: {
    visit_window_start: string | null;
    visit_window_end: string | null;
    amount_minor: number | null;
    currency: string | null;
    vat_mode: string | null;
    zero_cost_reason: string | null;
    scope_description: string | null;
    comment: string | null;
    access_requirements: string | null;
    valid_until: string | null;
  },
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  requireAssignment(requestId, assignmentId, providerOrgId);
  for (const p of visitProposals.values()) {
    if (p.request_id === requestId && p.assignment_id === assignmentId && p.status === 'pending') {
      p.status = 'superseded';
    }
  }
  const version = nextVersionFor(visitProposals as unknown as Map<string, { request_id: string; assignment_id: string; version: number }>, requestId, assignmentId);
  const proposal: DbVisitProposal = {
    id: nextId('vp'),
    request_id: requestId,
    assignment_id: assignmentId,
    version,
    visit_window_start: input.visit_window_start,
    visit_window_end: input.visit_window_end,
    amount_minor: input.amount_minor,
    currency: input.amount_minor !== null ? (input.currency ?? 'RUB') : null,
    vat_mode: input.vat_mode,
    zero_cost_reason: input.zero_cost_reason,
    scope_description: input.scope_description,
    comment: input.comment,
    access_requirements: input.access_requirements,
    valid_until: input.valid_until ?? new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
    status: 'pending',
    responded_at: null,
    response_comment: null,
    created_at: now(),
  };
  visitProposals.set(proposal.id, proposal);
  if (request.status === 'scheduled') {
    transition(request, 'visit_proposal.proposed', 'accepted', 'provider_membership', { proposal_id: proposal.id });
  } else {
    transition(request, 'visit_proposal.proposed', null, 'provider_membership', { proposal_id: proposal.id });
  }
  return request;
}

export function respondVisitProposal(
  requestId: string,
  customerOrgId: string,
  proposalId: string,
  proposalVersion: number,
  approve: boolean,
  comment: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const proposal = visitProposals.get(proposalId);
  if (!proposal || proposal.request_id !== requestId) throw notFoundError();
  expireVisitProposalsIfDue(requestId);
  if (proposal.version !== proposalVersion) {
    throw conflict('PROPOSAL_NOT_CURRENT', 'Условия изменились, откройте актуальную версию', {
      proposal_version: proposal.version,
    });
  }
  if (proposal.status === 'expired') throw conflict('PROPOSAL_EXPIRED', 'Срок предложения истёк');
  if (proposal.status === 'superseded') {
    throw conflict('PROPOSAL_NOT_CURRENT', 'Есть более новая версия условий', { proposal_version: proposal.version });
  }
  if (proposal.status !== 'pending') throw conflict('PROPOSAL_NOT_PENDING', 'Ответ по этой версии уже дан');
  if (approve && proposal.amount_minor === null) {
    throw conflict('PRICE_UNKNOWN', 'Стоимость выезда не указана — согласовать нельзя');
  }
  proposal.status = approve ? 'approved' : 'rejected';
  proposal.responded_at = now();
  proposal.response_comment = comment;
  const toStatus = approve && request.status === 'accepted' ? 'scheduled' : null;
  if (toStatus === 'scheduled') request.scheduled_at = now();
  transition(request, approve ? 'visit_proposal.approved' : 'visit_proposal.rejected', toStatus, 'customer_membership', {
    proposal_id: proposalId,
  });
  return request;
}

export function createRepairQuote(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  input: {
    description_of_work: string;
    items?: RepairQuoteItem[] | null;
    amount_minor: number | null;
    currency: string | null;
    vat_mode: string | null;
    zero_cost_reason: string | null;
    valid_until: string | null;
    warranty_terms?: string | null;
  },
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  requireAssignment(requestId, assignmentId, providerOrgId);
  if (!['accepted', 'scheduled', 'in_progress'].includes(request.status)) {
    throw conflict('INVALID_TRANSITION', 'Смету ремонта можно отправить после согласования выезда');
  }
  const items = input.items ?? [];
  let amountMinor = input.amount_minor;
  if (items.length) {
    const total = items.reduce((sum, item) => sum + item.amount_minor, 0);
    if (amountMinor !== null && amountMinor !== total) {
      throw new DomainError(422, 'QUOTE_ITEMS_SUM_MISMATCH', 'Сумма сметы не совпадает с суммой позиций', {
        field: 'amount_minor',
        items_total_minor: total,
      });
    }
    amountMinor = total;
  }
  for (const q of repairQuotes.values()) {
    if (q.request_id === requestId && q.assignment_id === assignmentId && q.status === 'pending') {
      q.status = 'superseded';
    }
  }
  const version = nextVersionFor(repairQuotes as unknown as Map<string, { request_id: string; assignment_id: string; version: number }>, requestId, assignmentId);
  const quote: DbRepairQuote = {
    id: nextId('rq'),
    request_id: requestId,
    assignment_id: assignmentId,
    version,
    description_of_work: input.description_of_work,
    warranty_terms: input.warranty_terms?.trim() || null,
    items,
    amount_minor: amountMinor,
    currency: amountMinor !== null ? (input.currency ?? 'RUB') : null,
    vat_mode: input.vat_mode,
    zero_cost_reason: input.zero_cost_reason,
    valid_until: input.valid_until ?? new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString(),
    status: 'pending',
    responded_at: null,
    response_comment: null,
    created_at: now(),
  };
  repairQuotes.set(quote.id, quote);
  transition(request, 'repair_quote.proposed', null, 'provider_membership', { quote_id: quote.id });
  return request;
}

export function respondRepairQuote(
  requestId: string,
  customerOrgId: string,
  quoteId: string,
  quoteVersion: number,
  approve: boolean,
  comment: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const quote = repairQuotes.get(quoteId);
  if (!quote || quote.request_id !== requestId) throw notFoundError();
  expireRepairQuotesIfDue(requestId);
  if (quote.version !== quoteVersion) {
    throw conflict('QUOTE_NOT_CURRENT', 'Смета изменилась, откройте актуальную версию', { quote_version: quote.version });
  }
  if (quote.status === 'expired') throw conflict('QUOTE_EXPIRED', 'Срок сметы истёк');
  if (quote.status === 'superseded') {
    throw conflict('QUOTE_NOT_CURRENT', 'Есть более новая версия сметы', { quote_version: quote.version });
  }
  if (quote.status !== 'pending') throw conflict('QUOTE_NOT_PENDING', 'Ответ по этой версии уже дан');
  quote.status = approve ? 'approved' : 'rejected';
  quote.responded_at = now();
  quote.response_comment = comment;
  transition(request, approve ? 'repair_quote.approved' : 'repair_quote.rejected', null, 'customer_membership', {
    quote_id: quoteId,
  });
  return request;
}

export function startWork(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  requireAssignment(requestId, assignmentId, providerOrgId);
  if (request.status !== 'scheduled') {
    throw conflict('INVALID_TRANSITION', 'Начать работу можно после согласования выезда');
  }
  request.work_started_at = now();
  transition(request, 'request.work_started', 'in_progress', 'provider_membership', { assignment_id: assignmentId });
  return request;
}

export function markEnRoute(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = requireAssignment(requestId, assignmentId, providerOrgId);
  if (request.status !== 'scheduled' || assignment.state !== 'accepted') {
    throw conflict('INVALID_TRANSITION', 'Отметить выезд можно после согласования выезда');
  }
  if (assignment.en_route_at) throw conflict('ALREADY_EN_ROUTE', 'Выезд уже отмечен');
  assignment.en_route_at = now();
  pushEvent(requestId, 'FieldWorkerEnRoute', request.status, null, 'provider_membership', { assignment_id: assignmentId });
  touch(request);
  return request;
}

export function withEquipmentSummary(item: Equipment, customerOrgId: string, locationIds: string[] | null): Equipment {
  const category = db.categoryById(item.equipment_category_id);
  const active = Array.from(requests.values())
    .filter(
      (r) =>
        r.equipment_id === item.id &&
        r.customer_org_id === customerOrgId &&
        r.status !== 'closed' &&
        r.status !== 'cancelled' &&
        (locationIds === null || locationIds.includes(r.location_id)),
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const nameplate = Array.from(attachments.values()).some(
    (a) => a.owner_ref === item.id && a.slot === 'nameplate' && a.processing_state === 'ready',
  );
  return {
    ...item,
    category_code: category?.code ?? null,
    category_name: category?.name ?? null,
    location_name: db.locationName(item.location_id),
    binding: db.equipmentBindingSummary(item.id, customerOrgId),
    active_request: active ? { id: active.id, request_number: active.request_number, status: active.status } : null,
    has_nameplate_photo: nameplate,
  };
}

export function reportCompletion(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  outcome: string,
  summary: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  requireAssignment(requestId, assignmentId, providerOrgId);
  if (request.status !== 'in_progress') {
    throw conflict('INVALID_TRANSITION', 'Сообщить о результате можно во время работы');
  }
  request.completion_reported_at = now();
  transition(request, 'request.completion_reported', 'completion_reported', 'provider_membership', {
    assignment_id: assignmentId,
    outcome,
    summary,
  });
  return request;
}

export function confirmCompletion(requestId: string, customerOrgId: string, expectedVersion: number | null | undefined): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (request.status !== 'completion_reported') {
    throw conflict('INVALID_TRANSITION', 'Подтвердить результат можно после сообщения исполнителя');
  }
  checkVersion(request.version, expectedVersion);
  const assignment = currentAssignment(request);
  if (assignment) assignment.state = 'completed';
  request.closed_at = now();
  request.closure_kind = 'customer_confirmed';
  transition(request, 'request.closed', 'closed', 'customer_membership');
  return request;
}

export function rejectCompletion(
  requestId: string,
  customerOrgId: string,
  reason: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  if (request.status !== 'completion_reported') {
    throw conflict('INVALID_TRANSITION', 'Вернуть в работу можно после сообщения исполнителя');
  }
  checkVersion(request.version, expectedVersion);
  request.completion_reported_at = null;
  transition(request, 'request.completion_rejected', 'in_progress', 'customer_membership', { reason });
  return request;
}

const DISPUTE_TIMEOUT_MS = 72 * 60 * 60 * 1000;

export function requestCancellation(
  requestId: string,
  customerOrgId: string,
  target: CancellationTarget,
  reason: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const assignment = currentAssignment(request);

  if (!assignment || assignment.state === 'pending') {
    if (assignment) {
      assignment.state = 'revoked';
      request.current_assignment_id = null;
    }
    request.cancellation_reason = reason;
    const toStatus = target === 'change_provider' ? 'action_required' : 'cancelled';
    if (toStatus === 'cancelled') request.cancelled_at = now();
    const eventType = toStatus === 'cancelled' ? 'request.cancelled' : 'SearchStopped';
    transition(request, eventType, toStatus, 'customer_membership', {
      target,
      reason,
      assignment_id: assignment?.id ?? null,
    });
    return request;
  }

  const open = Array.from(cancellations.values()).some(
    (c) => c.request_id === requestId && ['pending', 'disputed'].includes(c.status),
  );
  if (open) throw conflict('CANCELLATION_ALREADY_OPEN', 'Запрос отмены уже открыт');

  const cancellation: DbCancellation = {
    id: nextId('canc'),
    request_id: requestId,
    assignment_id: assignment.id,
    target,
    previous_status: request.status,
    status: 'pending',
    reason,
    provider_response: null,
    disputed: false,
    dispute_deadline_at: new Date(Date.now() + DISPUTE_TIMEOUT_MS).toISOString(),
    resolution_kind: null,
    resolved_at: null,
    created_at: now(),
  };
  cancellations.set(cancellation.id, cancellation);
  transition(request, 'cancellation.requested', 'cancellation_pending', 'customer_membership', {
    cancellation_id: cancellation.id,
    target,
  });
  return request;
}

export function withdrawCancellation(
  requestId: string,
  customerOrgId: string,
  cancellationId: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const cancellation = cancellations.get(cancellationId);
  if (!cancellation || cancellation.request_id !== requestId) throw notFoundError();
  if (!['pending', 'disputed'].includes(cancellation.status)) {
    throw conflict('CANCELLATION_NOT_PENDING', 'Запрос отмены уже закрыт');
  }
  cancellation.status = 'withdrawn';
  cancellation.resolved_at = now();
  transition(request, 'cancellation.withdrawn', cancellation.previous_status, 'customer_membership', {
    cancellation_id: cancellationId,
  });
  return request;
}

export function forceCancellation(
  requestId: string,
  customerOrgId: string,
  cancellationId: string,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request || request.customer_org_id !== customerOrgId) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  const cancellation = cancellations.get(cancellationId);
  if (!cancellation || cancellation.request_id !== requestId) throw notFoundError();
  if (!['pending', 'disputed'].includes(cancellation.status)) {
    throw conflict('CANCELLATION_NOT_PENDING', 'Запрос отмены уже закрыт');
  }
  const providerSilent = cancellation.status === 'pending';
  const deadline = cancellation.dispute_deadline_at;
  if (!deadline || new Date(deadline).getTime() > Date.now()) {
    throw conflict('DISPUTE_PERIOD_ACTIVE', 'Срок ожидания ответа исполнителя ещё не истёк');
  }
  cancellation.status = 'force_closed';
  cancellation.disputed = !providerSilent;
  cancellation.resolution_kind = 'customer_unilateral';
  cancellation.resolved_at = now();
  const assignment = assignments.get(cancellation.assignment_id);
  if (assignment) assignment.state = 'revoked';
  request.disputed = true;
  if (request.current_assignment_id === cancellation.assignment_id) request.current_assignment_id = null;
  const toStatus = cancellation.target === 'change_provider' ? 'action_required' : 'cancelled';
  if (toStatus === 'cancelled') request.cancelled_at = now();
  transition(request, 'cancellation.force_closed', toStatus, 'customer_membership', { cancellation_id: cancellationId });
  return request;
}

export function expireCancellationDeadline(requestId: string): void {
  for (const c of cancellations.values()) {
    if (c.request_id === requestId && ['pending', 'disputed'].includes(c.status)) {
      c.dispute_deadline_at = new Date(Date.now() - 60_000).toISOString();
    }
  }
}

export function respondCancellation(
  requestId: string,
  providerOrgId: string,
  assignmentId: string,
  cancellationId: string,
  decision: 'accepted' | 'disputed',
  comment: string | null,
  expectedVersion: number | null | undefined,
): DbRequest {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  checkVersion(request.version, expectedVersion);
  requireAssignment(requestId, assignmentId, providerOrgId);
  const cancellation = cancellations.get(cancellationId);
  if (!cancellation || cancellation.request_id !== requestId) throw notFoundError();
  if (cancellation.status !== 'pending') throw conflict('CANCELLATION_NOT_PENDING', 'Запрос отмены уже закрыт');

  cancellation.provider_response = comment;
  if (decision === 'accepted') {
    cancellation.status = 'accepted';
    cancellation.resolution_kind = 'provider_confirmed';
    cancellation.resolved_at = now();
    const assignment = assignments.get(assignmentId);
    if (assignment) assignment.state = 'revoked';
    if (request.current_assignment_id === assignmentId) request.current_assignment_id = null;
    const toStatus = cancellation.target === 'change_provider' ? 'action_required' : 'cancelled';
    if (toStatus === 'cancelled') request.cancelled_at = now();
    transition(request, 'cancellation.accepted', toStatus, 'provider_membership', { cancellation_id: cancellationId });
  } else {
    cancellation.status = 'disputed';
    cancellation.disputed = true;
    cancellation.dispute_deadline_at = new Date(Date.now() + DISPUTE_TIMEOUT_MS).toISOString();
    transition(request, 'cancellation.disputed', cancellation.previous_status, 'provider_membership', {
      cancellation_id: cancellationId,
      comment,
    });
  }
  return request;
}

export function createFollowup(requestId: string, customerOrgId: string, urgency: string | null): DbRequest {
  const source = requests.get(requestId);
  if (!source || source.customer_org_id !== customerOrgId) throw notFoundError();
  return createDraft(customerOrgId, source.author_membership_id, {
    equipment_id: source.equipment_id,
    route: 'own_service',
    urgency: urgency ?? source.urgency,
    symptom_description: null,
    error_code: null,
  });
}

export function requestHistory(requestId: string, viewerSide: 'customer' | 'provider' = 'customer'): RequestEvent[] {
  return (events.get(requestId) ?? [])
    .map((e) => eventView(e, viewerSide))
    .sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
}

export function offerThreadProviderOrgId(requestId: string, offerId: string, customerOrgId: string): string {
  const request = requests.get(requestId);
  const offer = offers.get(offerId);
  if (!request || request.customer_org_id !== customerOrgId || !offer || offer.request_id !== requestId) {
    throw notFoundError();
  }
  return offer.provider_org_id;
}

export function listThreadMessages(
  requestId: string,
  providerOrgId: string,
  viewerSide: 'customer' | 'provider' = 'provider',
): RequestMessage[] {
  if (!requests.has(requestId)) throw notFoundError();
  return visibleMessages(requestId, providerOrgId)
    .filter((m) => m.thread_provider_org_id === providerOrgId)
    .map((m) => messageView(m, viewerSide));
}

export function getRequestStatus(requestId: string): RequestStatus | null {
  return requests.get(requestId)?.status ?? null;
}

export function postDialogMessage(
  requestId: string,
  authorKind: string,
  authorMembershipId: string,
  threadProviderOrgId: string,
  body: string,
): RequestMessage {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  if (request.status !== 'searching') {
    throw conflict('OFFER_DIALOG_CLOSED', 'Диалог по отклику закрыт: исполнитель уже выбран или поиск завершён');
  }
  return postMessage(requestId, authorKind, authorMembershipId, threadProviderOrgId, body);
}

export function listMessages(requestId: string, forProviderOrgId: string | null): RequestMessage[] {
  return visibleMessages(requestId, forProviderOrgId).map((m) =>
    messageView(m, forProviderOrgId === null ? 'customer' : 'provider'),
  );
}

const messageReads = tracked(new Map<string, string>());

function visibleMessages(requestId: string, forProviderOrgId: string | null): DbMessage[] {
  const request = requests.get(requestId);
  const assignment = request ? currentAssignment(request) : null;
  const ownAssignmentId = assignment && assignment.provider_org_id === forProviderOrgId ? assignment.id : null;
  return Array.from(messages.values())
    .filter((m) => m.request_id === requestId)
    .filter(
      (m) =>
        forProviderOrgId === null ||
        m.thread_provider_org_id === forProviderOrgId ||
        (m.thread_provider_org_id === null && ownAssignmentId !== null && m.assignment_id === ownAssignmentId),
    )
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
}

export function unreadMessagesCount(requestId: string, membershipId: string, forProviderOrgId: string | null): number {
  const lastRead = messageReads.get(`${requestId}:${membershipId}`);
  const visible = visibleMessages(requestId, forProviderOrgId);
  const lastIndex = lastRead ? visible.findIndex((m) => m.id === lastRead) : -1;
  return visible.slice(lastIndex + 1).filter((m) => m.author_membership_id !== membershipId).length;
}

export function markMessagesRead(requestId: string, membershipId: string, forProviderOrgId: string | null) {
  if (!requests.has(requestId)) throw notFoundError();
  const visible = visibleMessages(requestId, forProviderOrgId);
  const last = visible[visible.length - 1];
  if (last) messageReads.set(`${requestId}:${membershipId}`, last.id);
  return {
    request_id: requestId,
    last_read_message_id: messageReads.get(`${requestId}:${membershipId}`) ?? null,
    unread_messages_count: unreadMessagesCount(requestId, membershipId, forProviderOrgId),
  };
}

export function postMessage(
  requestId: string,
  authorKind: string,
  authorMembershipId: string | null,
  threadProviderOrgId: string | null,
  body: string,
  integrationClientId?: string,
): RequestMessage {
  const request = requests.get(requestId);
  if (!request) throw notFoundError();
  const assignment = currentAssignment(request);
  const clientId =
    authorKind === 'integration_client'
      ? (integrationClientId ?? (assignment ? db.activeApiKeyId(assignment.provider_org_id) : null))
      : null;
  const message: DbMessage = {
    id: nextId('msg'),
    request_id: requestId,
    author_kind: authorKind,
    author_membership_id: authorMembershipId,
    thread_provider_org_id: threadProviderOrgId,
    assignment_id:
      threadProviderOrgId === null && assignment && ['pending', 'accepted', 'completed'].includes(assignment.state)
        ? assignment.id
        : null,
    body,
    created_at: now(),
    author_integration_client_id: clientId,
  };
  messages.set(message.id, message);
  return messageView(message, authorKind === 'customer_membership' ? 'customer' : 'provider');
}

export function listVisitProposals(requestId: string): VisitProposal[] {
  expireVisitProposalsIfDue(requestId);
  return Array.from(visitProposals.values())
    .filter((p) => p.request_id === requestId)
    .map(visitProposalView);
}

export function listRepairQuotes(requestId: string): RepairQuote[] {
  expireRepairQuotesIfDue(requestId);
  return Array.from(repairQuotes.values())
    .filter((q) => q.request_id === requestId)
    .map(repairQuoteView);
}

export function addAttachment(params: {
  ownerKind: string;
  requestId: string | null;
  messageId: string | null;
  slot: string | null;
  visibilityClass: AttachmentVisibilityClass;
  mimeType: string;
  blob: Blob;
  needsModeration?: boolean;
  ownerOrgId?: string | null;
  ownerRef?: string | null;
}): Attachment {
  const record: DbAttachment = {
    id: nextId('att'),
    owner_kind: params.ownerKind,
    request_id: params.requestId,
    message_id: params.messageId,
    slot: params.slot,
    visibility_class: params.visibilityClass,
    processing_state: 'ready',
    rejected_reason: null,
    mime_type: params.mimeType,
    byte_size: params.blob.size,
    pixel_width: null,
    pixel_height: null,
    created_at: now(),
    blob: params.blob,
    publication_state: params.needsModeration ? 'pending' : null,
    owner_org_id: params.ownerOrgId ?? null,
    owner_ref: params.ownerRef ?? null,
  };
  attachments.set(record.id, record);
  return toAttachmentView(record);
}

export function listOwnedAttachments(ownerKind: string, ownerRef: string): Attachment[] {
  return Array.from(attachments.values())
    .filter((a) => a.owner_kind === ownerKind && a.owner_ref === ownerRef)
    .map(toAttachmentView);
}

export function listPortfolio(organizationId: string): Attachment[] {
  return Array.from(attachments.values())
    .filter((a) => a.owner_kind === 'provider_profile' && a.owner_org_id === organizationId)
    .map(toAttachmentView);
}

export function listAttachmentModerationQueue(status: string): Attachment[] {
  return Array.from(attachments.values())
    .filter((a) => a.publication_state !== null)
    .filter((a) => status === 'all' || a.publication_state === status)
    .map(toAttachmentView);
}

export function approveModeratedAttachment(id: string): Attachment | null {
  const record = attachments.get(id);
  if (!record) return null;
  record.publication_state = 'approved';
  if (record.owner_kind === 'provider_profile' && record.owner_org_id) {
    db.publishGalleryItem(record.owner_org_id, record.id, record.caption ?? null);
  }
  return toAttachmentView(record);
}

export function rejectModeratedAttachment(id: string, reason: string): Attachment | null {
  const record = attachments.get(id);
  if (!record) return null;
  record.publication_state = 'rejected';
  record.rejected_reason = reason;
  db.unpublishGalleryItem(record.id);
  return toAttachmentView(record);
}

export function getAttachmentRecord(id: string): DbAttachment | null {
  return attachments.get(id) ?? null;
}

export function deleteAttachment(id: string): void {
  if (!attachments.has(id)) throw notFoundError();
  attachments.delete(id);
  db.unpublishGalleryItem(id);
}

export function listRequestAttachments(requestId: string): Attachment[] {
  return attachmentsFor(requestId);
}
