import { useState } from 'react';
import { strings } from '../../../strings/ru';
import {
  useApproveVisitProposal,
  useRefreshRequest,
  useRejectVisitProposal,
} from '../../../api/hooks/useRequests';
import { ApiError } from '../../../api/errors';
import type { RequestCustomer } from '../../../api/types';
import { useCountdown } from '../../../lib/datetime';
import { useActionRunner, type ActionRunner } from '../../../components/actions/useActionRunner';

const STALE_CODES = new Set([
  'PROPOSAL_NOT_CURRENT',
  'PROPOSAL_EXPIRED',
  'PROPOSAL_NOT_PENDING',
  'VERSION_CONFLICT',
]);

type Proposal = RequestCustomer['visit_proposals'][number];

export interface VisitDecision {
  proposal: Proposal | undefined;
  anchor: Proposal | undefined;
  previous: Proposal | undefined;
  stale: boolean;
  countdown: { expired: boolean; label: string };
  pending: boolean;
  runner: ActionRunner;
  approve: (comment?: string | null) => Promise<boolean>;
  reject: (comment: string | null) => Promise<boolean>;
}

export function useVisitDecision(request: RequestCustomer | null, anchorId?: string): VisitDecision {
  const requestId = request?.id ?? '';
  const approve = useApproveVisitProposal(requestId);
  const reject = useRejectVisitProposal(requestId);
  const refresh = useRefreshRequest(request?.id);
  const runner = useActionRunner({
    onStale: refresh,
    staleCodes: STALE_CODES,
    fallbackMessage: strings.approvals.approveError,
  });
  const [seenVersion, setSeenVersion] = useState<number | null>(null);

  const proposals = request?.visit_proposals ?? [];
  const anchor = anchorId
    ? proposals.find((p) => p.id === anchorId)
    : proposals.find((p) => p.status === 'pending');
  const proposal: Proposal | undefined = anchor
    ? proposals
        .filter((p) => p.assignment_id === anchor.assignment_id)
        .sort((a, b) => b.version - a.version)[0]
    : undefined;
  const countdown = useCountdown(proposal?.valid_until);

  const stale = runner.feedback?.kind === 'stale';
  const previous =
    stale && proposal && seenVersion !== null && seenVersion < proposal.version
      ? proposals.find(
          (p) => p.assignment_id === proposal.assignment_id && p.version === seenVersion,
        )
      : undefined;

  const decide = async (approveDecision: boolean, comment: string | null) => {
    if (!request || !proposal) return false;
    setSeenVersion(proposal.version);
    const mutation = approveDecision ? approve : reject;
    const done = await runner.run(
      approveDecision ? 'approve' : 'reject',
      async () => {
        await mutation.mutateAsync({
          proposal_id: proposal.id,
          proposal_version: proposal.version,
          comment: comment?.trim() || null,
          expected_version: request.version,
        });
        return true;
      },
      {
        mapError: (e) =>
          e instanceof ApiError && e.code === 'PRICE_UNKNOWN'
            ? strings.approvals.priceUnknownNotice
            : null,
      },
    );
    return Boolean(done);
  };

  return {
    proposal,
    anchor,
    previous,
    stale,
    countdown,
    pending: proposal?.status === 'pending' && !countdown.expired,
    runner,
    approve: (comment: string | null = null) => decide(true, comment),
    reject: (comment: string | null) => decide(false, comment),
  };
}
