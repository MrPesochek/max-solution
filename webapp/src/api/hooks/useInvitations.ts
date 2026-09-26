import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type {
  CreateInvitationInput,
  Invitation,
  InvitationIssued,
  InvitationPreview,
  Membership,
  Page,
} from '../types';

export function useInvitations() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.invitations(scope),
    queryFn: async () => (await api.get<Page<Invitation>>('/invitations')).items,
    enabled: Boolean(scope),
  });
}

export function useCreateInvitation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: CreateInvitationInput, idempotencyKey) =>
      api.post<InvitationIssued>('/invitations', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.invitations(scope) });
    },
  });
}

export function useRevokeInvitation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (id: string, idempotencyKey) =>
      api.post<Invitation>(`/invitations/${id}/revoke`, undefined, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.invitations(scope) });
    },
  });
}

export function useInvitationPreview(token: string | null) {
  return useQuery({
    queryKey: queryKeys.invitationPreview(token ?? ''),
    queryFn: () =>
      api.post<InvitationPreview>('/invitations/preview', { token: token ?? '' }, { withoutOrganization: true }),
    enabled: Boolean(token),
    retry: false,
  });
}

export function useAcceptInvitation() {
  return useIdempotentMutation({
    mutationFn: (token: string, idempotencyKey) =>
      api.post<Membership>(
        '/invitations/accept',
        { token },
        { withoutOrganization: true, idempotencyKey },
      ),
  });
}
