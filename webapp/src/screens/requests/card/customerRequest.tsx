import type { ReactNode } from 'react';
import { strings } from '../../../strings/ru';
import { useRequest } from '../../../api/hooks/useRequests';
import { ApiError } from '../../../api/errors';
import type { RequestCustomer } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { EmptyState } from '../../../components/states/EmptyState';
import { NoAccessState } from '../../../components/states/NoAccessState';
import { Screen } from '../../../ui/layout/Screen';
import { RequestUnavailableScreen } from './RequestUnavailableScreen';

export function isCustomerView(data: unknown): data is RequestCustomer {
  return Boolean(data) && typeof data === 'object' && 'status' in (data as object) && 'search' in (data as object);
}

export function useCustomerRequest(id: string | undefined) {
  const query = useRequest(id);
  const request = isCustomerView(query.data) ? query.data : null;
  return { query, request };
}

export function requestFallback({
  query,
  request,
  title,
  back,
  noAccess,
}: {
  query: ReturnType<typeof useRequest>;
  request: RequestCustomer | null;
  title: ReactNode;
  back?: string;
  noAccess?: boolean;
}): ReactNode | null {
  if (noAccess) {
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
    const status = query.error instanceof ApiError ? query.error.status : null;
    if (status === 403 || status === 404) return <RequestUnavailableScreen title={title} back={back} />;
    return (
      <Screen title={title} back={back}>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Screen>
    );
  }
  if (!request) {
    return (
      <Screen title={title} back={back}>
        <EmptyState top={140} title={strings.requests.unavailableTitle} description={strings.requests.unavailable} />
      </Screen>
    );
  }
  return null;
}
