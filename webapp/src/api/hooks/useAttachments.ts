import { useEffect, useState } from 'react';
import { useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiPath, fetchAuthorizedBlob } from '../client';
import { attachmentsChanged } from '../invalidation';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type { Attachment } from '../types';

export function useRequestAttachments(requestId: string | undefined, enabled = true) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.requestAttachments(scope, requestId ?? ''),
    queryFn: ({ signal }) => api.get<Attachment[]>(apiPath`/requests/${requestId!}/attachments`, { signal }),
    enabled: Boolean(scope && requestId && enabled),
  });
}

export function useUploadAttachment(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (
      { file, slot, messageId }: { file: File; slot?: string; messageId?: string | null },
      idempotencyKey,
    ) => {
      const form = new FormData();
      form.append('file', file);
      if (slot) form.append('slot', slot);
      if (messageId) form.append('message_id', messageId);
      return api.post<Attachment>(apiPath`/requests/${requestId}/attachments`, form, { idempotencyKey });
    },
    onSuccess: () => attachmentsChanged(queryClient, scope, requestId),
  });
}

export function useDeleteAttachment(requestId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (attachmentId: string, idempotencyKey) =>
      api.delete<void>(apiPath`/attachments/${attachmentId}`, { idempotencyKey }),
    onSuccess: () => attachmentsChanged(queryClient, scope, requestId),
  });
}

export function useAttachmentBlobUrl(
  attachmentId: string | null | undefined,
  variant: 'safe' | 'thumb' = 'thumb',
) {
  return useAuthorizedBlobUrl(
    ['attachments', 'blob', attachmentId ?? '', variant],
    attachmentId
      ? (signal) => fetchAuthorizedBlob(apiPath`/attachments/${attachmentId}/content`, { variant }, signal)
      : null,
  );
}

export function useAuthorizedBlobUrl(
  queryKey: QueryKey,
  fetchBlob: ((signal: AbortSignal) => Promise<Blob>) | null,
): { url: string | null; isLoading: boolean; isError: boolean } {
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchBlob!(signal),
    enabled: Boolean(fetchBlob),
    staleTime: Infinity,
    gcTime: 5 * 60_000,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!query.data) {
      setUrl(null);
      return;
    }
    if (typeof URL.createObjectURL !== 'function') return;
    const objectUrl = URL.createObjectURL(query.data);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [query.data]);
  return {
    url,
    isLoading: Boolean(fetchBlob) && query.isPending,
    isError: query.isError,
  };
}
