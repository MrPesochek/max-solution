import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { bindingsChanged } from '../invalidation';
import { queryKeys } from '../queryKeys';
import type {
  BindingDecision,
  BindingInvitation,
  BindingInvitationCreateInput,
  BindingInvitationDeclineInput,
  BindingInvitationIssued,
  BindingInvitationPreview,
  BindingItemMatch,
  BindingRequestAccepted,
  BindingRequestInput,
  ContactBindingInput,
  Page,
  ProviderBinding,
  ServiceBinding,
} from '../types';

type Binding = ServiceBinding | ProviderBinding;

export function useBindingsList(filters: { equipmentId?: string; status?: string } = {}) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.bindings(scope, filters),
    queryFn: async () =>
      (
        await api.get<Page<Binding>>('/service-bindings', {
          query: { equipment_id: filters.equipmentId, status: filters.status },
        })
      ).items,
    enabled: Boolean(scope),
  });
}

const BINDING_REQUEST_WINDOW_MS = 15 * 60_000;

interface BindingRequestAttempts {
  remaining: number;
  at: number;
}

const bindingAttemptsKey = (scope: string | null) => ['binding-request-attempts', scope] as const;

export function useRequestBinding() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: BindingRequestInput, idempotencyKey) =>
      api.post<BindingRequestAccepted>('/service-bindings/requests', input, { idempotencyKey }),
    onSuccess: (result) => {
      if (typeof result.remaining_attempts === 'number') {
        queryClient.setQueryData<BindingRequestAttempts>(bindingAttemptsKey(scope), {
          remaining: result.remaining_attempts,
          at: Date.now(),
        });
      }
      void queryClient.invalidateQueries({ queryKey: ['service-bindings', scope] });
    },
  });
}

export function useBindingRequestAttempts(): number | null {
  const scope = getActiveScope();
  const query = useQuery<BindingRequestAttempts | null>({
    queryKey: bindingAttemptsKey(scope),
    queryFn: () => null,
    enabled: false,
    staleTime: Infinity,
    gcTime: BINDING_REQUEST_WINDOW_MS,
  });
  const data = query.data;
  return data && Date.now() - data.at < BINDING_REQUEST_WINDOW_MS ? data.remaining : null;
}

export function useCreateContactBinding() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: ContactBindingInput, idempotencyKey) =>
      api.post<ServiceBinding>('/service-bindings/contacts', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['service-bindings', scope] });
    },
  });
}

export function useRespondBinding() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (
      { id, decision, reason }: { id: string; decision: BindingDecision; reason?: string },
      idempotencyKey,
    ) =>
      api.post<ProviderBinding>(
        `/service-bindings/${id}/respond`,
        { decision, reason },
        { idempotencyKey },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['service-bindings', scope] });
    },
  });
}

export function useRevokeBinding() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }, idempotencyKey) =>
      api.post<ServiceBinding>(`/service-bindings/${id}/revoke`, { reason }, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['service-bindings', scope] });
    },
  });
}

export function useBindingInvitations() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.bindingInvitations(scope),
    queryFn: async () =>
      (await api.get<Page<BindingInvitation>>('/service-binding-invitations')).items,
    enabled: Boolean(scope),
  });
}

export function useCreateBindingInvitation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (input: BindingInvitationCreateInput, idempotencyKey) =>
      api.post<BindingInvitationIssued>('/service-binding-invitations', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.bindingInvitations(scope) });
    },
  });
}

export function useRevokeBindingInvitation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (id: string, idempotencyKey) =>
      api.post<BindingInvitation>(`/service-binding-invitations/${id}/revoke`, undefined, {
        idempotencyKey,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.bindingInvitations(scope) });
    },
  });
}

export function useBindingInvitationPreview(token: string | null) {
  return useQuery({
    queryKey: queryKeys.bindingInvitationPreview(token ?? ''),
    queryFn: () =>
      api.post<BindingInvitationPreview>('/service-binding-invitations/preview', { token: token ?? '' }),
    enabled: Boolean(token),
    retry: false,
  });
}

export function useDeclineBindingInvitation() {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: BindingInvitationDeclineInput, idempotencyKey) =>
      api.post<BindingInvitationPreview>('/service-binding-invitations/decline', input, { idempotencyKey }),
    onSuccess: (result, input) => {
      queryClient.setQueryData(queryKeys.bindingInvitationPreview(input.token), result);
    },
  });
}

export function useAcceptBindingInvitation() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: async (
      { token, matches }: { token: string; matches: BindingItemMatch[] },
      idempotencyKey,
    ) =>
      (
        await api.post<{ items: ServiceBinding[] }>(
          '/service-binding-invitations/accept',
          { token, matches },
          { idempotencyKey },
        )
      ).items,
    onSuccess: () => bindingsChanged(queryClient, scope),
  });
}
