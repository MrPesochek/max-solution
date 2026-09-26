import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type { Attachment, ProviderProfile, ProviderProfileUpdateInput } from '../types';

export function useProviderProfile() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.providerProfile(scope),
    queryFn: () => api.get<ProviderProfile>('/provider-profile'),
    enabled: Boolean(scope),
  });
}

export function useUpdateProviderProfile() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: ProviderProfileUpdateInput, idempotencyKey) =>
      api.patch<ProviderProfile>('/provider-profile', input, { idempotencyKey }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.providerProfile(scope), updated);
    },
  });
}

export function useSubmitProviderProfile() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (_: void, idempotencyKey) =>
      api.post<ProviderProfile>('/provider-profile/submit', undefined, { idempotencyKey }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.providerProfile(scope), updated);
    },
  });
}

export function useAppealProviderProfile() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: { text: string }, idempotencyKey) =>
      api.post<unknown>('/provider-profile/appeal', input, { idempotencyKey }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.providerProfile(scope) });
    },
  });
}

export function usePortfolio() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.portfolio(scope),
    queryFn: () => api.get<Attachment[]>('/provider-profile/portfolio'),
    enabled: Boolean(scope),
  });
}

export function useUploadPortfolioImage() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (file: File, idempotencyKey) => {
      const form = new FormData();
      form.append('file', file);
      return api.post<Attachment>('/provider-profile/portfolio', form, { idempotencyKey });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolio(scope) });
    },
  });
}

export function useDeletePortfolioImage() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (attachmentId: string, idempotencyKey) =>
      api.delete<void>(`/provider-profile/portfolio/${attachmentId}`, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolio(scope) });
    },
  });
}

export function useUpdatePortfolioCaption() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: { attachmentId: string; caption: string | null }, idempotencyKey) =>
      api.patch<Attachment>(
        `/provider-profile/portfolio/${input.attachmentId}`,
        { caption: input.caption },
        { idempotencyKey },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolio(scope) });
    },
  });
}

export function useSetAcceptingNewRequests() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (accepting: boolean, idempotencyKey) =>
      api.post<ProviderProfile>('/provider-profile/accepting', { accepting }, { idempotencyKey }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.providerProfile(scope), updated);
    },
  });
}
