import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import { useSession } from '../../session/SessionContext';
import type {
  CreateOrganizationInput,
  CreateOrganizationResponse,
  Organization,
  ParticipationInput,
  UpdateOrganizationInput,
} from '../types';

export function useCreateOrganization() {
  return useIdempotentMutation({
    mutationFn: (input: CreateOrganizationInput, idempotencyKey) =>
      api.post<CreateOrganizationResponse>('/organizations', input, {
        withoutOrganization: true,
        idempotencyKey,
      }),
  });
}

export function useCurrentOrganization() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.organizationCurrent(scope),
    queryFn: () => api.get<Organization>('/organizations/current'),
    enabled: Boolean(scope),
  });
}

export function useUpdateOrganization() {
  const queryClient = useQueryClient();
  return useIdempotentMutation({
    mutationFn: (input: UpdateOrganizationInput, idempotencyKey) =>
      api.patch<Organization>('/organizations/current', input, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['organizations', 'current'] });
    },
  });
}

export function useAddParticipation(organizationId: string) {
  const queryClient = useQueryClient();
  const { refreshMemberships } = useSession();
  return useIdempotentMutation({
    mutationFn: async (input: ParticipationInput, idempotencyKey) => {
      const result = await api.post<CreateOrganizationResponse>(
        `/organizations/${organizationId}/participation`,
        input,
        { idempotencyKey },
      );
      try {
        await refreshMemberships();
      } catch {
      }
      return result;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['organizations', 'current'] });
    },
  });
}
