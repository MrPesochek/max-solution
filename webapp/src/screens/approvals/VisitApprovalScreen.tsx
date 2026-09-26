import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRequest } from '../../api/hooks/useRequests';
import type { RequestCustomer } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StatusHero } from '../../ui/StatusHero';
import { useVisitDecision } from './visit/useVisitDecision';
import { VisitDecisionActions, VisitProposalBlocks } from './visit/VisitProposalView';

function isCustomerView(data: unknown): data is RequestCustomer {
  return Boolean(data) && typeof data === 'object' && 'status' in (data as object) && 'search' in (data as object);
}

export function VisitApprovalScreen() {
  const { id, proposalId } = useParams<{ id: string; proposalId: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const query = useRequest(id);
  const request = isCustomerView(query.data) ? query.data : null;
  const decision = useVisitDecision(request, proposalId);
  const [showCurrent, setShowCurrent] = useState(false);

  const title = request ? strings.ui.requestTitle(request.request_number) : strings.approvals.visitTitle;
  const back = id ? `/requests/${id}` : undefined;

  if (!activeMembership || !id || !proposalId) return null;
  if (!canManageRequestApprovals(activeMembership.role)) {
    return (
      <Screen title={title} back={back}>
        <NoAccessState />
      </Screen>
    );
  }
  if (query.isPending) {
    return (
      <Screen title={title} back={back}>
        <Skeleton lines={6} />
      </Screen>
    );
  }
  if (query.isError) {
    return (
      <Screen title={title} back={back}>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }
  if (!request || !decision.proposal || !decision.anchor) {
    return (
      <Screen title={title} back={back}>
        <EmptyState
          title={strings.approvals.visitTitle}
          description={request ? strings.approvals.visitNotFound : strings.requests.unavailable}
        />
      </Screen>
    );
  }

  const outdatedLink =
    decision.anchor.id !== decision.proposal.id && !decision.stale && !showCurrent;
  if (outdatedLink) {
    return (
      <Screen
        title={title}
        back={back}
        actions={
          <BottomActions>
            <ActionButton onClick={() => setShowCurrent(true)}>
              {strings.approvals.showNewTerms}
            </ActionButton>
          </BottomActions>
        }
      >
        <StatusHero illustration="status-waiting" top={40} title={strings.approvals.staleLinkTitle}>
          {strings.approvals.staleLinkText(decision.anchor.version, decision.proposal.version)}
        </StatusHero>
      </Screen>
    );
  }

  return (
    <Screen
      title={title}
      back={back}
      actions={
        <VisitDecisionActions
          decision={decision}
          onDone={() => navigate(`/requests/${id}`, { replace: true })}
        />
      }
    >
      <VisitProposalBlocks request={request} decision={decision} isManager />
    </Screen>
  );
}
