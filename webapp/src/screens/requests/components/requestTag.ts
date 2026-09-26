import { strings } from '../../../strings/ru';
import type { RequestStatus } from '../../../api/types';
import type { ApprovalItem } from '../../../api/hooks/useApprovals';
import type { Tone } from '../../../ui/blocks/Blocks';

export interface RowTag {
  label: string;
  tone: Tone;
}

const TONES: Record<RequestStatus, Tone> = {
  draft: 'y',
  approval_required: 'w',
  awaiting_provider: 'w',
  searching: 'w',
  awaiting_assignment_confirmation: 'w',
  accepted: 'w',
  scheduled: 'ok',
  in_progress: 'w',
  completion_reported: 'w',
  action_required: 'w',
  cancellation_pending: 'w',
  closed: 'ok',
  cancelled: 'x',
};

const MANAGER_DECISION: Partial<Record<RequestStatus, keyof typeof strings.requests.tag>> = {
  approval_required: 'approval_required_manager',
  completion_reported: 'completion_reported_manager',
  action_required: 'action_required_manager',
};

export function requestRowTag(
  status: RequestStatus,
  options: { isManager: boolean; approval?: ApprovalItem } = { isManager: false },
): RowTag {
  if (options.isManager && options.approval) {
    const kind = options.approval.kind;
    return { label: strings.home.approvalTag[kind], tone: 'a' };
  }
  const managerKey = options.isManager ? MANAGER_DECISION[status] : undefined;
  if (managerKey) return { label: strings.requests.tag[managerKey], tone: 'a' };
  return { label: strings.requests.tag[status], tone: TONES[status] };
}
