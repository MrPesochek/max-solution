import { useState } from 'react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { isProvider } from '../../lib/roles';
import { ApiError } from '../../api/errors';
import { useRefreshRequest, useRequest, useRequestHistory } from '../../api/hooks/useRequests';
import {
  isProviderView,
  useMarkEnRoute,
  useStartWork,
} from '../../api/hooks/useProviderRequests';
import type {
  RepairQuote,
  RepairQuoteStatus,
  RequestProvider,
  RequestStatus,
} from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { HistorySection } from '../../components/request/HistorySection';
import { MessagesSection } from '../../components/request/MessagesSection';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner, type ActionRunner } from '../../components/actions/useActionRunner';
import { formatAmountMinor, formatPrice } from '../../lib/money';
import { warrantyDecisionLabel } from '../../lib/status';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, Tag, TextCard, type Tone } from '../../ui/blocks/Blocks';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { SceneBanner } from '../../ui/SceneBanner';
import { Stepper } from '../../ui/Stepper';
import { List, ListRow } from '../../ui/List';
import { UnsavedInputGuard } from '../../ui/layout/unsavedGuard';
import { useSubView } from '../../ui/layout/subView';
import { visitWindowShort } from '../../ui/format';
import { IncomingAssignmentView } from './request-detail/IncomingAssignmentView';
import { VisitProposalPanel } from './request-detail/VisitProposalPanel';
import { RepairQuotePanel } from './request-detail/RepairQuotePanel';
import { WarrantyPanel } from './request-detail/WarrantyPanel';
import { FieldWorkerPanel } from './request-detail/FieldWorkerPanel';
import { WorkProgressPanel } from './request-detail/WorkProgressPanel';
import {
  CancellationActions,
  CancellationBanner,
} from './request-detail/CancellationResponsePanel';
import { WithdrawPanel } from './request-detail/WithdrawPanel';
import { RequestPhotos } from './request-detail/RequestPhotos';
import { ContactRow } from './request-detail/common';
import { equipmentTitle } from './request-detail/types';
import { useMarkReadOnOpen } from '../requests/card/useMarkReadOnOpen';
import {
  PHASE_ART,
  phaseTitle,
  workFacts,
  workPhase,
  workSteps,
} from './request-detail/workProgress';
import './components/workspace.css';

function MarkMessagesRead({ requestId }: { requestId: string }) {
  useMarkReadOnOpen(requestId);
  return null;
}

const TERMINAL_STATUSES = new Set<RequestStatus>(['closed', 'cancelled']);
const WORKING_STATUSES = new Set<RequestStatus>(['accepted', 'scheduled', 'in_progress']);
const QUOTE_TONE: Record<RepairQuoteStatus, Tone> = {
  pending: 'w',
  approved: 'ok',
  rejected: 'x',
  expired: 'w',
  superseded: 'w',
};

const SUB_VIEWS = ['visit', 'quote', 'warranty', 'fieldWorker', 'report'] as const;
type View = (typeof SUB_VIEWS)[number] | 'main';

type Panel = null | 'messages' | 'details' | 'history';

function screenLoading() {
  return (
    <Screen title={strings.ui.requestGenericTitle}>
      <Skeleton lines={6} />
    </Screen>
  );
}

export function ProviderRequestDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { activeMembership } = useSession();
  const query = useRequest(id);
  const refresh = useRefreshRequest(id);
  const [search] = useSearchParams();
  const initialPanel: Panel = search.get('panel') === 'messages' ? 'messages' : null;
  const runner = useActionRunner({
    onStale: refresh,
    fallbackMessage: strings.workspace.genericActionError,
  });

  if (!activeMembership || !id) return null;
  if (!isProvider(activeMembership.role)) return <Navigate to={`/requests/${id}`} replace />;

  if (query.isPending) return screenLoading();
  if (query.isError) {
    const gone = query.error instanceof ApiError && query.error.status === 404;
    return (
      <Screen title={strings.ui.requestGenericTitle}>
        {gone ? (
          <EmptyState
            title={strings.requests.title}
            description={strings.workspace.detailNotFound}
          />
        ) : (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        )}
      </Screen>
    );
  }

  const data = query.data;
  if (!isProviderView(data)) {
    return (
      <Screen title={strings.ui.requestGenericTitle}>
        <EmptyState
          title={strings.requests.title}
          description={strings.workspace.detailAssignmentEnded}
        />
      </Screen>
    );
  }

  if (data.assignment.state === 'pending')
    return (
      <IncomingAssignmentView
        request={data}
        runner={runner}
        initialAsking={initialPanel === 'messages'}
      />
    );
  return (
    <AssignmentView request={data} runner={runner} onStale={refresh} initialPanel={initialPanel} />
  );
}

function QuoteCard({ quote }: { quote: RepairQuote }) {
  const rows: KeyValueRow[] =
    quote.items.length > 0
      ? quote.items.map((item, index) => ({
          id: `${index}`,
          label: item.title,
          value: formatAmountMinor(item.amount_minor),
        }))
      : [{ id: 'work', label: quote.description_of_work, value: formatPrice(quote.price) }];
  return (
    <section className="pw-quote" aria-label={strings.workspace.quoteCardTitle}>
      <span className="pw-quote__title">
        {strings.workspace.quoteCardTitle}
        <Tag tone={QUOTE_TONE[quote.status]}>
          {quote.status === 'approved'
            ? strings.workspace.quoteApprovedTag
            : strings.workspace.quoteStatusTag[quote.status]}
        </Tag>
      </span>
      <KeyValueRows
        variant="items"
        rows={rows}
        total={{ label: strings.workspace.quoteCardTotal, value: formatPrice(quote.price) }}
      />
      {quote.status === 'pending' && (
        <p className="pw-quote__note">{strings.workspace.phaseText['quote-pending']}</p>
      )}
    </section>
  );
}

function AssignmentView({
  request,
  runner,
  onStale,
  initialPanel,
}: {
  request: RequestProvider;
  runner: ActionRunner;
  onStale: () => unknown;
  initialPanel: Panel;
}) {
  const [view, setView] = useSubView(SUB_VIEWS, { clear: ['panel'] });
  const [panel, setPanel] = useState<Panel>(initialPanel);
  const startWork = useStartWork(request.id);
  const markEnRoute = useMarkEnRoute(request.id);
  const facts = workFacts(request);
  const reachedWork = ['in_progress', 'completion_reported', 'closed'].includes(request.status);
  const history = useRequestHistory(request.id, reachedWork);

  const go = (next: View) => {
    runner.clearFeedback();
    setView(next);
  };
  const back = () => go('main');
  const subProps = { request, runner, onDone: back };

  if (view === 'visit')
    return (
      <UnsavedInputGuard>
        <VisitProposalPanel {...subProps} />
      </UnsavedInputGuard>
    );
  if (view === 'quote')
    return (
      <UnsavedInputGuard>
        <RepairQuotePanel {...subProps} />
      </UnsavedInputGuard>
    );
  if (view === 'warranty')
    return (
      <UnsavedInputGuard>
        <WarrantyPanel {...subProps} />
      </UnsavedInputGuard>
    );
  if (view === 'fieldWorker')
    return (
      <UnsavedInputGuard>
        <FieldWorkerPanel {...subProps} />
      </UnsavedInputGuard>
    );
  if (view === 'report')
    return (
      <UnsavedInputGuard>
        <WorkProgressPanel {...subProps} onStale={onStale} />
      </UnsavedInputGuard>
    );

  const w = strings.workspace;
  const tz = request.location.timezone;
  const phase = workPhase(request, facts);
  const open = !TERMINAL_STATUSES.has(request.status);
  const working = WORKING_STATUSES.has(request.status);
  const canWithdraw = ['accepted', 'scheduled'].includes(request.status);
  const { approvedVisit, pendingVisit, latestQuote, pendingQuote } = facts;
  const shownVisit = pendingVisit ?? approvedVisit ?? request.visit_proposals.at(-1);
  const canStartWork = request.status === 'scheduled' && Boolean(approvedVisit);
  const canMarkEnRoute = canStartWork && !facts.enRouteAt;
  const canReport = request.status === 'in_progress';
  const cancellationPending = request.cancellation?.status === 'pending';
  const fieldWorker = request.assignment.field_worker;
  const hasContact =
    request.contacts_disclosed &&
    Boolean(request.location.contact_phone || request.location.contact_name);
  const hasFacts = Boolean(shownVisit || approvedVisit || hasContact);

  const primary: 'visit' | 'enRoute' | 'startWork' | 'quote' | 'report' | null = cancellationPending
    ? null
    : phase === 'propose-visit' && working
      ? 'visit'
      : canMarkEnRoute
        ? 'enRoute'
        : canStartWork
          ? 'startWork'
          : phase === 'diagnostics'
            ? 'quote'
            : phase === 'repair'
              ? 'report'
              : null;

  const toggle = (next: Exclude<Panel, null>) =>
    setPanel((current) => (current === next ? null : next));

  const runStartWork = () =>
    void runner.run('startWork', () =>
      startWork.mutateAsync({
        assignment_id: request.assignment.id,
        expected_version: request.version,
      }),
    );

  const runMarkEnRoute = () =>
    void runner.run('enRoute', async () => {
      try {
        await markEnRoute.mutateAsync({
          assignment_id: request.assignment.id,
          expected_version: request.version,
        });
      } catch (error) {
        if (error instanceof ApiError && error.code === 'ALREADY_EN_ROUTE') {
          await onStale();
          return;
        }
        throw error;
      }
    });

  let actions;
  if (cancellationPending) {
    actions = <CancellationActions request={request} runner={runner} />;
  } else if (primary) {
    const label = {
      visit: w.actionProposeVisit,
      enRoute: w.actionEnRoute,
      startWork: w.actionOnSite,
      quote: w.actionRepairQuote,
      report: w.actionWorkDone,
    }[primary];
    actions = (
      <BottomActions>
        <ActionButton
          loading={runner.isRunning(primary)}
          disabled={runner.busy}
          onClick={() =>
            primary === 'startWork'
              ? runStartWork()
              : primary === 'enRoute'
                ? runMarkEnRoute()
                : go(primary)
          }
        >
          {label}
        </ActionButton>
      </BottomActions>
    );
  }

  const phaseText =
    phase === 'diagnostics' && latestQuote?.status === 'rejected'
      ? w.quoteRejectedText(latestQuote.response_comment)
      : phase === 'quote-pending'
        ? undefined
        : w.phaseText[phase];

  return (
    <Screen
      title={w.detailHeader(
        request.customer_org_name,
        strings.ui.requestTitle(request.request_number),
      )}
      actions={actions}
    >
      <SceneBanner name={PHASE_ART[phase]} height={140} width={175} />
      <PageTitle
        subtitle={w.rowSubtitle(
          equipmentTitle(request),
          request.contacts_disclosed ? request.location.address : null,
        )}
      >
        {phaseTitle(phase, facts)}
      </PageTitle>
      {phaseText && <Note>{phaseText}</Note>}

      <CancellationBanner request={request} />
      <ActionFeedback feedback={runner.feedback} />

      <Stepper aria-label={w.workStepsLabel} steps={workSteps(request, facts, history.data)} />

      {latestQuote && latestQuote.status !== 'superseded' && <QuoteCard quote={latestQuote} />}

      {hasFacts && (
        <List>
          {shownVisit && (
            <ListRow
              title={w.visitRow}
              value={visitWindowShort(
                shownVisit.visit_window_start,
                shownVisit.visit_window_end,
                tz,
              )}
              tag={
                shownVisit.status === 'approved'
                  ? undefined
                  : { label: w.visitProposalNotApproved, tone: 'w' }
              }
            />
          )}
          {approvedVisit && (
            <ListRow title={w.agreedRow} value={formatPrice(approvedVisit.price)} />
          )}
          <ContactRow request={request} />
        </List>
      )}
      {!request.contacts_disclosed && <Note>{w.incomingHiddenContacts}</Note>}

      <List>
        {primary === 'enRoute' && (
          <ListRow
            title={w.actionOnSite}
            action="accent"
            disabled={runner.busy}
            onClick={runStartWork}
          />
        )}
        {working && primary !== 'visit' && (
          <ListRow
            title={
              approvedVisit
                ? w.actionChangeTime
                : pendingVisit
                  ? w.actionChangeVisit
                  : w.actionProposeVisit
            }
            action="accent"
            disabled={runner.busy}
            onClick={() => go('visit')}
          />
        )}
        {working && primary !== 'quote' && (
          <ListRow
            title={w.actionRepairQuote}
            subtitle={pendingQuote ? w.quotePendingHint : undefined}
            action="accent"
            disabled={runner.busy || Boolean(pendingQuote)}
            onClick={() => go('quote')}
          />
        )}
        {canReport && primary !== 'report' && (
          <ListRow
            title={w.reportScreenTitle}
            action="accent"
            disabled={runner.busy}
            onClick={() => go('report')}
          />
        )}
        <ListRow
          title={w.messagesRow}
          count={request.unread_messages_count || undefined}
          chevron
          expanded={panel === 'messages'}
          onClick={() => toggle('messages')}
        />
      </List>
      {panel === 'messages' && (
        <div className="ui-pad">
          <MarkMessagesRead requestId={request.id} />
          <MessagesSection
            requestId={request.id}
            assignmentId={request.assignment.id}
            ownAuthorKind="provider_membership"
            allowPhotos={open}
            attachments={request.attachments}
            embedded
          />
        </div>
      )}
      {request.status === 'scheduled' && !canStartWork && (
        <Note>{w.actionStartWorkDisabledNotice}</Note>
      )}
      {(request.status === 'scheduled' || request.status === 'in_progress') && (
        <Note>{w.changeTermsNote}</Note>
      )}

      <List>
        <ListRow
          title={w.fieldWorkerTitle}
          subtitle={fieldWorker?.stated_by_company ? w.fieldWorkerStatedByCompany : undefined}
          value={fieldWorker?.display_name ?? w.fieldWorkerNone}
          valueTone={fieldWorker ? undefined : 'secondary'}
          chevron={open}
          onClick={open ? () => go('fieldWorker') : undefined}
        />
        <ListRow
          title={w.warrantyRow}
          value={warrantyDecisionLabel(request.assignment.warranty_decision)}
          chevron={open}
          onClick={open ? () => go('warranty') : undefined}
        />
        <ListRow
          title={w.detailsRow}
          chevron
          expanded={panel === 'details'}
          onClick={() => toggle('details')}
        />
        <ListRow
          title={strings.requests.card.historyRow}
          chevron
          expanded={panel === 'history'}
          onClick={() => toggle('history')}
        />
      </List>
      {panel === 'details' && (
        <>
          <List>
            <ListRow
              title={w.cardCategoryLabel}
              value={request.equipment.category_name ?? strings.common.notSpecified}
            />
            {request.equipment.serial_number && (
              <ListRow title={w.serialLabel} value={request.equipment.serial_number} />
            )}
            {request.error_code && (
              <ListRow title={strings.requests.card.errorCodeTitle} value={request.error_code} />
            )}
          </List>
          {request.symptom_description && <TextCard>{request.symptom_description}</TextCard>}
          <RequestPhotos request={request} canUpload={open} onStale={onStale} />
        </>
      )}
      {panel === 'history' && (
        <div className="ui-pad">
          <HistorySection requestId={request.id} embedded />
        </div>
      )}

      {canWithdraw && <WithdrawPanel request={request} runner={runner} />}
    </Screen>
  );
}
