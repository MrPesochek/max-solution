import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type { Attachment, VerificationCase, VerificationInformationInput } from '../types';

export function useVerificationCases() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.verificationCases(scope),
    queryFn: () => api.get<VerificationCase[]>('/verification'),
    enabled: Boolean(scope),
  });
}

export function useSubmitVerificationInformation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: VerificationInformationInput, idempotencyKey) =>
      api.post('/verification', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.verificationCases(scope) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.providerProfile(scope) });
    },
  });
}

export function useUploadVerificationEvidence() {
  return useIdempotentMutation({
    mutationFn: (
      { file, verificationCaseId }: { file: File; verificationCaseId: string | null },
      idempotencyKey,
    ) => {
      const form = new FormData();
      form.append('file', file);
      if (verificationCaseId) form.append('verification_case_id', verificationCaseId);
      return api.post<Attachment>('/verification/attachments', form, { idempotencyKey });
    },
  });
}
