import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, apiGet, type GetResponse } from '../client';
import { POLL_INTERVAL_MS } from '../queryClient';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import { useSession } from '../../session/SessionContext';
import { canManageRequestApprovals } from '../../lib/roles';
import type { Page, PendingDecision, RequestListItem } from '../types';

type PendingApprovalItemView = GetResponse<'/requests/pending-approvals'>[number];
type PendingApprovalKind = PendingApprovalItemView['kind'];

export interface ApprovalItem {
  key: string;
  requestId: string;
  requestNumber: number;
  kind: PendingApprovalKind | 'offers';
  label: string;
  href: string;
  decision: PendingDecision | null;
  messageId?: string | null;
  threadProviderId?: string | null;
}

const APPROVAL_LABELS: Record<ApprovalItem['kind'], string> = {
  draft_approval: 'Черновик сотрудника ждёт публикации',
  completion_reported: 'Исполнитель сообщил о результате',
  visit_proposal: 'Условия выезда ждут согласования',
  repair_quote: 'Смета ремонта ждёт согласования',
  offers: 'Есть предложения исполнителей',
  cancellation_disputed: 'Исполнитель ответил на запрос отмены',
  action_required: 'Нужно решение по заявке',
  question: 'Исполнитель задал вопрос',
};

function hrefFor(item: PendingApprovalItemView): string {
  switch (item.kind) {
    case 'visit_proposal':
      return `/requests/${item.request.id}/visit-proposals/${item.object?.id ?? ''}`;
    case 'repair_quote':
      return `/requests/${item.request.id}/repair-quotes/${item.object?.id ?? ''}`;
    case 'question':
      return item.thread_provider_id
        ? `/requests/${item.request.id}/questions/${item.thread_provider_id}`
        : `/requests/${item.request.id}/messages`;
    default:
      return `/requests/${item.request.id}`;
  }
}

function useAggregatedApprovals(enabled: boolean) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.pendingApprovals(scope),
    queryFn: ({ signal }) => apiGet('/requests/pending-approvals', { signal }),
    enabled,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

function useOffersApprovals(enabled: boolean) {
  const scope = getActiveScope();

  const searchingList = useQuery({
    queryKey: queryKeys.requests(scope, { status: 'searching', approvals: true }),
    queryFn: async () =>
      (
        await api.get<Page<RequestListItem>>('/requests', {
          query: { status: 'searching', limit: 40 },
        })
      ).items,
    enabled,
    refetchInterval: POLL_INTERVAL_MS,
  });

  const items = useMemo<ApprovalItem[]>(
    () =>
      (searchingList.data ?? [])
        .filter((r) => r.pending_decision?.kind === 'offers')
        .map((r) => ({
          key: `offers:${r.id}`,
          requestId: r.id,
          requestNumber: r.request_number,
          kind: 'offers',
          label: APPROVAL_LABELS.offers,
          href: `/requests/${r.id}/offers`,
          decision: r.pending_decision ?? null,
        })),
    [searchingList.data],
  );

  return { items, isLoading: enabled && searchingList.isPending };
}

export function usePendingApprovals() {
  const { activeMembership } = useSession();
  const enabled = Boolean(activeMembership && canManageRequestApprovals(activeMembership.role));
  const customer = activeMembership?.side === 'customer';

  const aggregate = useAggregatedApprovals(Boolean(customer));
  const offers = useOffersApprovals(enabled);

  const approvals = useMemo<ApprovalItem[]>(() => {
    const fromAggregate = (aggregate.data ?? []).map((item): ApprovalItem => ({
      key: `${item.kind}:${item.object?.id ?? item.request.id}`,
      requestId: item.request.id,
      requestNumber: item.request.request_number,
      kind: item.kind,
      label: APPROVAL_LABELS[item.kind],
      href: hrefFor(item),
      decision: null,
      messageId: item.kind === 'question' ? (item.object?.id ?? null) : null,
      threadProviderId: item.thread_provider_id ?? null,
    }));
    return [...fromAggregate, ...offers.items];
  }, [aggregate.data, offers.items]);

  return {
    approvals,
    isLoading: (Boolean(customer) && aggregate.isPending) || offers.isLoading,
    isError: aggregate.isError,
    error: aggregate.error,
    refetch: aggregate.refetch,
  };
}
