import type { ReactNode } from 'react';
import { strings } from '../../strings/ru';
import { useOperatorAccess } from '../../api/hooks/useOperatorAccess';
import { Skeleton } from '../states/Skeleton';
import { NoAccessState } from '../states/NoAccessState';
import { ErrorState } from '../states/ErrorState';

export function RequireOperator({ children }: { children: ReactNode }) {
  const access = useOperatorAccess();
  if (access.isLoading) return <Skeleton lines={4} />;
  if (access.networkError) return <ErrorState error={access.error} onRetry={access.retry} />;
  if (!access.hasAccess) return <NoAccessState description={strings.operator.accessDeniedDescription} />;
  return <>{children}</>;
}
