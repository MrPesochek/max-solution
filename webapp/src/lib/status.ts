import { strings } from '../strings/ru';
import type {
  AssignmentState,
  CancellationStatus,
  OfferState,
  RepairQuoteStatus,
  RequestStatus,
  Urgency,
  VisitProposalStatus,
  WarrantyDecision,
} from '../api/types';

const ACTIVE_STATUSES = new Set<RequestStatus>([
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
]);

export function isActiveRequestStatus(status: RequestStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function requestStatusLabel(status: RequestStatus): string {
  return strings.requests.status[status];
}

export function requestStatusWhatNext(status: RequestStatus): string {
  return strings.requests.statusWhatNext[status];
}

export function urgencyLabel(urgency: Urgency): string {
  return strings.requests.urgency[urgency];
}

export function assignmentStateLabel(state: AssignmentState): string {
  return strings.requests.assignmentState[state];
}

export function warrantyDecisionLabel(decision: WarrantyDecision): string {
  return strings.requests.card.warrantyDecision[decision];
}

export function visitProposalStatusLabel(status: VisitProposalStatus): string {
  switch (status) {
    case 'pending':
      return 'Ждёт решения';
    case 'approved':
      return 'Согласовано';
    case 'rejected':
      return 'Отклонено';
    case 'expired':
      return 'Срок истёк';
    case 'superseded':
      return 'Заменено новой версией';
  }
}

export function repairQuoteStatusLabel(status: RepairQuoteStatus): string {
  return visitProposalStatusLabel(status);
}

export function cancellationStatusLabel(status: CancellationStatus): string {
  switch (status) {
    case 'pending':
      return 'Ждём ответа исполнителя';
    case 'accepted':
      return 'Исполнитель согласился';
    case 'disputed':
      return 'Исполнитель не согласен';
    case 'withdrawn':
      return 'Запрос отозван';
    case 'force_closed':
      return 'Прекращено в одностороннем порядке';
  }
}

export function offerStateLabel(state: OfferState): string {
  switch (state) {
    case 'active':
      return 'Действует';
    case 'selected':
      return 'Выбрано';
    case 'expired':
      return 'Срок истёк';
    case 'withdrawn':
      return 'Отозвано исполнителем';
    case 'closed':
      return 'Закрыто';
  }
}
