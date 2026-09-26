import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type {
  AccessRequestInput,
  AccessRequestSent,
  Membership,
  Page,
  StaffMember,
} from '../types';

export function useStaff() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.memberships(scope),
    queryFn: async () =>
      (await api.get<Page<StaffMember>>('/memberships')).items.filter(
        (member) => member.status !== 'revoked',
      ),
    enabled: Boolean(scope),
  });
}

export function useApproveMembership() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (membershipId: string, idempotencyKey) =>
      api.post<Membership>(`/memberships/${membershipId}/approve`, undefined, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.memberships(scope) });
    },
  });
}

export function useRevokeMembership() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (membershipId: string, idempotencyKey) =>
      api.post<Membership>(`/memberships/${membershipId}/revoke`, undefined, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.memberships(scope) });
    },
  });
}

export function useSetMembershipLocations(membershipId: string) {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (locationIds: string[], idempotencyKey) =>
      api.put<Membership>(
        `/memberships/${membershipId}/locations`,
        { location_ids: locationIds },
        { idempotencyKey },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.memberships(scope) });
    },
  });
}

export function useRequestAccess() {
  return useIdempotentMutation({
    mutationFn: (input: AccessRequestInput, idempotencyKey) =>
      api.post<AccessRequestSent>('/memberships/me/access-requests', input, { idempotencyKey }),
  });
}
