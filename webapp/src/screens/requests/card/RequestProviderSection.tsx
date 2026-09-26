import { strings } from '../../../strings/ru';
import type { RequestCustomer } from '../../../api/types';
import { formatVisitWindow } from '../../../lib/datetime';
import { assignmentStateLabel, warrantyDecisionLabel } from '../../../lib/status';
import { Note } from '../../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../../ui/KeyValueRows';

const VISIT_STATUSES = new Set(['scheduled', 'in_progress', 'completion_reported']);

export function RequestProviderSection({ request }: { request: RequestCustomer }) {
  const c = strings.requests.card;
  const assignment = request.assignment;
  if (!assignment) return <Note>{c.providerUnknown}</Note>;
  const approvedVisit = request.visit_proposals.find((p) => p.status === 'approved');
  const warranty = assignment.warranty_decision !== 'not_stated';

  const rows: KeyValueRow[] = [
    { label: c.providerTitle, value: assignment.provider_display_name?.trim() || strings.offers.providerFallback },
    { label: c.assignmentStatusLabel, value: assignmentStateLabel(assignment.state) },
  ];
  if (assignment.field_worker) {
    rows.push({
      label: c.fieldWorkerTitle,
      value: assignment.field_worker.display_name ?? strings.common.notSpecified,
      hint: assignment.field_worker.stated_by_company ? c.fieldWorkerStatedByCompany : undefined,
    });
  }
  if (VISIT_STATUSES.has(request.status)) {
    rows.push({
      label: c.visitWindowTitle,
      value: formatVisitWindow(
        approvedVisit?.visit_window_start,
        approvedVisit?.visit_window_end,
        request.location.timezone,
      ),
    });
  }
  if (warranty) {
    rows.push({
      label: c.warrantyTitle,
      value: warrantyDecisionLabel(assignment.warranty_decision),
      hint: c.warrantyStatedByProvider,
    });
  }

  return <KeyValueRows rows={rows} aria-label={c.providerTitle} />;
}
