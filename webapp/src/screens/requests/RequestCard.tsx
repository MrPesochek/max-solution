import { lazy, Suspense, useState } from 'react';
import { strings } from '../../strings/ru';
import { useRefreshRequest, useRequestHistory } from '../../api/hooks/useRequests';
import { useRequestOffers } from '../../api/hooks/useOffers';
import type { Role, RequestCustomer } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { canManageRequestApprovals } from '../../lib/roles';
import { useConfirm } from '../../components/useConfirm';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { Screen } from '../../ui/layout/Screen';
import { Note, Tag } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { useCardActions } from './card/RequestCardActions';
import { CancellationNotice } from './card/CancellationNotice';
import { CompletionRemarkSent, CompletionRemarkView } from './card/CompletionRemarkView';
import { PriceRows, StatusBlocks } from './card/StatusBlocks';
import { cardView, MESSAGE_STATUSES } from './card/cardModel';
import { CardSubject } from './card/CardSubject';
import { CardHistory } from './card/CardHistory';
import { CardQuestion } from './card/CardQuestion';
import { useSlotLabels } from './card/useSlotLabels';
import { useVisitDecision } from '../approvals/visit/useVisitDecision';
import { VisitDecisionActions, VisitProposalBlocks } from '../approvals/visit/VisitProposalView';
import '../../components/request/request.css';

const RequestReviewSection = lazy(() =>
  import('../reviews/RequestReviewSection').then((m) => ({ default: m.RequestReviewSection })),
);
const ComplaintButton = lazy(() =>
  import('../reviews/ComplaintButton').then((m) => ({ default: m.ComplaintButton })),
);

const EMPLOYEE_WATCH_STATUSES = new Set([
  'approval_required',
  'accepted',
  'scheduled',
  'in_progress',
  'completion_reported',
  'cancellation_pending',
]);
const TERMINAL_STATUSES = new Set(['closed', 'cancelled']);
const REVIEW_STATUSES = new Set(['completion_reported', 'closed', 'cancelled']);
const NO_SHOW_STATUSES = new Set(['scheduled', 'cancellation_pending', 'action_required', 'cancelled']);
const HISTORY_STATUSES = new Set(['action_required']);
const OFFER_STATUSES = new Set(['searching', 'awaiting_assignment_confirmation', 'action_required']);

export function RequestCard({ request, role }: { request: RequestCustomer; role: Role }) {
  const isManager = canManageRequestApprovals(role);
  const refresh = useRefreshRequest(request.id);
  const runner = useActionRunner({ onStale: refresh });
  const { confirm, dialog } = useConfirm();
  const visit = useVisitDecision(request);
  const history = useRequestHistory(request.id, HISTORY_STATUSES.has(request.status));
  const offers = useRequestOffers(OFFER_STATUSES.has(request.status) && request.search ? request.id : undefined);
  const slotLabels = useSlotLabels(request.equipment.category_id);
  const [remark, setRemark] = useState<'form' | 'sent' | null>(null);
  const [waiting, setWaiting] = useState(false);

  const visitOffer = Boolean(visit.proposal);
  const openRequest = !TERMINAL_STATUSES.has(request.status);

  const actions = useCardActions({
    request,
    isManager,
    runner,
    confirm,
    offers: offers.data,
    visitOffer,
    onRemark: () => setRemark('form'),
    onWait: () => setWaiting(true),
  });

  if (remark === 'form' && request.status === 'completion_reported') {
    return (
      <CompletionRemarkView request={request} onClose={() => setRemark(null)} onSent={() => setRemark('sent')} />
    );
  }
  if (remark === 'sent') {
    return <CompletionRemarkSent request={request} onDone={() => setRemark(null)} />;
  }

  const view = cardView({ request, isManager, history: history.data, offers: offers.data, waiting });
  const hasMessages =
    MESSAGE_STATUSES.has(request.status) || (TERMINAL_STATUSES.has(request.status) && Boolean(request.assignment));

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      actions={visitOffer && isManager ? <VisitDecisionActions decision={visit} /> : actions.bottom}
    >
      {visitOffer ? (
        <VisitProposalBlocks request={request} decision={visit} isManager={isManager} />
      ) : (
        <StatusBlocks view={view} request={request} />
      )}

      <CardQuestion request={request} />

      {!isManager && EMPLOYEE_WATCH_STATUSES.has(request.status) && !visitOffer && (
        <Note>{strings.requests.card.actionNoAccessEmployee}</Note>
      )}

      {!actions.sheetOpen && !(actions.feedbackInBottom && !(visitOffer && isManager)) && (
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      )}

      <CancellationNotice request={request} isManager={isManager} runner={runner} confirm={confirm} />

      <CardSubject request={request} canUpload={openRequest} onStale={refresh} slotLabels={slotLabels} />
      {view.prices && !visitOffer && <PriceRows request={request} isManager={isManager} />}
      {(request.photos_incomplete || request.disputed) && (
        <div className="request-chips">
          {request.photos_incomplete && <Tag tone="x">{strings.requests.card.photosIncompleteTag}</Tag>}
          {request.disputed && <Tag tone="x">{strings.requests.card.disputedTag}</Tag>}
        </div>
      )}

      <CardHistory
        requestId={request.id}
        proposals={request.visit_proposals}
        timezone={request.location.timezone}
        steps={visitOffer ? undefined : view.steps}
        defaultOpen={!visitOffer && view.historyOpen}
      />

      {/* Один вход в переписку: строка — если кнопки «Написать» нет или есть непрочитанные. */}
      {hasMessages && (!actions.messageButton || (request.unread_messages_count ?? 0) > 0) && (
        <List>
          <ListRow
            title={strings.requests.card.messagesRow}
            count={request.unread_messages_count || undefined}
            chevron
            to={`/requests/${request.id}/messages`}
          />
        </List>
      )}

      {actions.rows}

      {isManager && NO_SHOW_STATUSES.has(request.status) && request.visit_proposals.some((p) => p.status === 'approved') && (
        <Suspense fallback={null}>
          <div className="ui-pad">
            <ComplaintButton
              subjectType="no_show"
              targetId={request.id}
              label={strings.requests.card.actionComplainNoShow}
            />
          </div>
        </Suspense>
      )}

      {isManager && REVIEW_STATUSES.has(request.status) && (
        <Suspense fallback={<Skeleton lines={2} />}>
          <RequestReviewSection
            request={request}
            isManager={isManager}
            leaveInBottom={request.status === 'closed'}
          />
        </Suspense>
      )}
      {actions.overlay}
      {dialog}
    </Screen>
  );
}
