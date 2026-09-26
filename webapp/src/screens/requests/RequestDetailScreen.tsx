import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRequest } from '../../api/hooks/useRequests';
import { useSession } from '../../session/SessionContext';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { ApiError } from '../../api/errors';
import type { RequestCustomer } from '../../api/types';
import { RequestWizard } from './RequestWizard';
import { RequestSentScreen } from './wizard/RequestSentScreen';
import { RequestCard } from './RequestCard';
import { DraftCard } from './card/DraftCard';
import { RequestUnavailableScreen } from './card/RequestUnavailableScreen';

export interface RequestNavigationState {
  sent?: boolean;
  wizard?: boolean;
  step?: number;
}
import { isCustomer } from '../../lib/roles';
import { Screen } from '../../ui/layout/Screen';

export function RequestDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { activeMembership } = useSession();
  const query = useRequest(id);
  const navigate = useNavigate();
  const navigationState = useLocation().state as RequestNavigationState | null;

  if (!activeMembership || !id) return null;

  if (!isCustomer(activeMembership.role)) return <Navigate to={`/provider/requests/${id}`} replace />;

  const title = strings.ui.requestGenericTitle;
  if (query.isPending) {
    return (
      <Screen title={title}>
        <Skeleton lines={6} />
      </Screen>
    );
  }

  if (query.isError) {
    const status = query.error instanceof ApiError ? query.error.status : null;
    if (status === 403 || status === 404) return <RequestUnavailableScreen title={title} />;
    return (
      <Screen title={title}>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }

  const data = query.data;
  if (!('status' in data)) {
    return (
      <Screen title={title}>
        <EmptyState top={140} title={strings.requests.unavailableTitle} description={strings.requests.unavailable} />
      </Screen>
    );
  }
  const request = data as RequestCustomer;

  if (request.status === 'draft') {
    if (navigationState?.wizard) {
      return <RequestWizard request={request} initialStep={navigationState.step} />;
    }
    return (
      <DraftCard
        request={request}
        onContinue={(step) =>
          navigate(`/requests/${request.id}`, { replace: true, state: { wizard: true, step } })
        }
      />
    );
  }
  if (navigationState?.sent) {
    return <RequestSentScreen request={request} />;
  }
  return <RequestCard request={request} role={activeMembership.role} />;
}
