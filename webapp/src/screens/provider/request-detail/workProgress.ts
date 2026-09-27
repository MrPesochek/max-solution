import { strings } from '../../../strings/ru';
import type { RepairQuote, RequestEvent, RequestProvider, VisitProposal } from '../../../api/types';
import type { StepItem } from '../../../ui/Stepper';
import type { IllustrationName } from '../../../ui/illustrations';
import { formatTime } from '../../../lib/datetime';

export type WorkPhase =
  | 'propose-visit'
  | 'visit-pending'
  | 'scheduled'
  | 'diagnostics'
  | 'quote-pending'
  | 'repair'
  | 'completion'
  | 'decision'
  | 'cancellation'
  | 'closed'
  | 'cancelled';

export interface WorkFacts {
  approvedVisit?: VisitProposal;
  pendingVisit?: VisitProposal;
  latestQuote?: RepairQuote;
  pendingQuote?: RepairQuote;
  approvedQuote?: RepairQuote;
  enRouteAt: string | null;
}

export function workFacts(request: RequestProvider): WorkFacts {
  const visits = request.visit_proposals;
  const quotes = request.repair_quotes;
  return {
    approvedVisit: visits.find((v) => v.status === 'approved'),
    pendingVisit: visits.find((v) => v.status === 'pending'),
    latestQuote: quotes[quotes.length - 1],
    pendingQuote: quotes.find((q) => q.status === 'pending'),
    approvedQuote: [...quotes].reverse().find((q) => q.status === 'approved'),
    enRouteAt: request.assignment.en_route_at ?? null,
  };
}

export function workPhase(request: RequestProvider, facts: WorkFacts): WorkPhase {
  if (request.cancellation?.status === 'pending') return 'cancellation';
  switch (request.status) {
    case 'accepted':
      return facts.pendingVisit ? 'visit-pending' : 'propose-visit';
    case 'scheduled':
      return facts.approvedVisit
        ? 'scheduled'
        : facts.pendingVisit
          ? 'visit-pending'
          : 'propose-visit';
    case 'in_progress':
      if (facts.pendingQuote) return 'quote-pending';
      return facts.latestQuote?.status === 'approved' ? 'repair' : 'diagnostics';
    case 'completion_reported':
      return 'completion';
    case 'action_required':
      return 'decision';
    case 'cancellation_pending':
      return 'cancellation';
    case 'closed':
      return 'closed';
    case 'cancelled':
      return 'cancelled';
    default:
      return 'propose-visit';
  }
}

export const PHASE_ART: Record<WorkPhase, IllustrationName> = {
  'propose-visit': 'status-travel',
  'visit-pending': 'status-waiting',
  scheduled: 'status-travel',
  diagnostics: 'status-diagnostics',
  'quote-pending': 'status-price',
  repair: 'status-repair',
  completion: 'status-done',
  decision: 'status-dispute',
  cancellation: 'status-cancel',
  closed: 'status-done',
  cancelled: 'status-cancel',
};

export function phaseTitle(phase: WorkPhase, facts: WorkFacts): string {
  const titles = strings.workspace.phaseTitle;
  if (phase === 'scheduled' && facts.enRouteAt) return titles.enRoute ?? '';
  return titles[phase] ?? '';
}

const REACHED_WORK = new Set(['in_progress', 'completion_reported', 'closed', 'action_required']);
const REPORTED = new Set(['completion_reported', 'closed']);

export function workSteps(
  request: RequestProvider,
  facts: WorkFacts,
  history: RequestEvent[] | undefined,
): StepItem[] {
  const tz = request.location.timezone;
  const time = (iso: string | null | undefined) => (iso ? formatTime(iso, tz) : undefined);
  const w = strings.workspace.workSteps;
  const onSite = history?.find((e) => e.to_status === 'in_progress')?.occurred_at;
  const reported = REPORTED.has(request.status) || Boolean(request.completion_report);
  const diagnosed = Boolean(facts.latestQuote) || reported;

  const onSiteDone = REACHED_WORK.has(request.status);
  const departed = Boolean(facts.enRouteAt) || onSiteDone;

  const raw: { id: string; label: string; done: boolean; at?: string | null }[] = [
    facts.approvedVisit || departed
      ? { id: 'en-route', label: w.enRoute, done: departed, at: facts.enRouteAt }
      : { id: 'visit', label: w.visitAgreed, done: false },
    { id: 'on-site', label: w.onSite, done: onSiteDone, at: onSite },
    { id: 'diagnostics', label: w.diagnostics, done: diagnosed, at: facts.latestQuote?.created_at },
    {
      id: 'quote',
      label: w.quoteAgreed,
      done: Boolean(facts.approvedQuote),
      at: facts.approvedQuote?.responded_at,
    },
    { id: 'done', label: w.completed, done: reported, at: request.completion_report?.reported_at },
  ];
  const steps = raw.filter((step) => !(step.id === 'quote' && reported && !facts.approvedQuote));
  const stopped = request.status === 'cancelled';
  const currentIndex = stopped ? -1 : steps.findIndex((step) => !step.done);

  return steps.map((step, index) => ({
    id: step.id,
    label: step.label,
    time: step.done ? time(step.at) : undefined,
    state: step.done ? 'done' : index === currentIndex ? 'current' : 'todo',
  }));
}
