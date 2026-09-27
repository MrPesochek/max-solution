import type { ReactNode } from 'react';
import { strings } from '../../strings/ru';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { Screen } from '../../ui/layout/Screen';
import { PageTitle } from '../../ui/blocks/Blocks';

interface QueueQuery {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
}

export function OperatorScreen({
  title,
  subtitle,
  query,
  empty,
  emptyTitle,
  actions,
  toolbar,
  overlay,
  tabPanel,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  query?: QueueQuery;
  empty?: boolean;
  emptyTitle?: string;
  actions?: ReactNode;
  toolbar?: ReactNode;
  overlay?: ReactNode;
  tabPanel?: { idPrefix: string; tab: string };
  children?: ReactNode;
}) {
  let body: ReactNode = children;
  if (query?.isPending) body = <Skeleton lines={4} />;
  else if (query?.isError)
    body = <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  else if (empty)
    body = <EmptyState title={emptyTitle ?? strings.operator.queueEmpty} icon="✓" tone="ok" />;

  return (
    <Screen title={strings.operator.navLabel} actions={actions}>
      <PageTitle subtitle={subtitle}>{title}</PageTitle>
      {toolbar}
      {tabPanel ? (
        <div
          id={`${tabPanel.idPrefix}-panel`}
          role="tabpanel"
          aria-labelledby={`${tabPanel.idPrefix}-${tabPanel.tab}`}
        >
          {body}
        </div>
      ) : (
        body
      )}
      {overlay}
    </Screen>
  );
}
