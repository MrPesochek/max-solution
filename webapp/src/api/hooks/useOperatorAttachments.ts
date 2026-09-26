import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { apiPath, fetchOperatorAuthorizedBlob, operatorApi } from '../client';
import { POLL_INTERVAL_MS } from '../queryClient';
import { queryKeys } from '../queryKeys';
import { useAuthorizedBlobUrl } from './useAttachments';
import type { OperatorAttachment, OperatorPage, RevokeInput } from '../operatorTypes';

const listKey = queryKeys.operatorAttachments;

export function useOperatorAttachmentQueue(status: string) {
  return useQuery({
    queryKey: listKey(status),
    queryFn: async () =>
      (
        await operatorApi.get<OperatorPage<OperatorAttachment>>('/attachments', {
          query: { status, limit: 50 },
        })
      ).items,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useApproveOperatorAttachment(id: string, status: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (_: void, idempotencyKey) =>
      operatorApi.post(apiPath`/attachments/${id}/approve`, undefined, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: listKey(status) }),
  });
}

export function useRejectOperatorAttachment(id: string, status: string) {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: RevokeInput, idempotencyKey) =>
      operatorApi.post(apiPath`/attachments/${id}/reject`, input, { idempotencyKey }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: listKey(status) }),
  });
}

export function useOperatorAttachmentBlobUrl(attachmentId: string | null | undefined) {
  return useAuthorizedBlobUrl(
    ['operator', 'attachment-blob', attachmentId ?? ''],
    attachmentId
      ? (signal) =>
          fetchOperatorAuthorizedBlob(apiPath`/attachments/${attachmentId}/content`, { variant: 'safe' }, signal)
      : null,
  );
}
