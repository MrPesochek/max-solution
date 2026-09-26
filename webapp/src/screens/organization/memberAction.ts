import { canApproveMembership, canManageOrganization } from '../../lib/roles';
import type { Membership, StaffMember } from '../../api/types';

export type MemberAction = 'approve' | 'manage' | null;

export function memberAction(member: StaffMember, me: Membership): MemberAction {
  if (!canManageOrganization(me.role) || member.id === me.id) return null;
  if (member.status === 'pending') return canApproveMembership(me.role) ? 'approve' : null;
  return member.status === 'active' ? 'manage' : null;
}
