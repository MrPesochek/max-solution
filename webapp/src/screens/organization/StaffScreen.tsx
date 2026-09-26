import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useStaff } from '../../api/hooks/useMemberships';
import { useInvitations } from '../../api/hooks/useInvitations';
import { useLocations } from '../../api/hooks/useLocations';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { useSession } from '../../session/SessionContext';
import { canManageOrganization } from '../../lib/roles';
import { Note, SectionCaption, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { initials, shortDateTime } from '../../ui/format';
import type { Invitation, StaffMember } from '../../api/types';
import { organizationGradient } from '../onboarding/membershipRow';
import { roleWithPlaces } from './staffLabels';
import { memberAction } from './memberAction';
import { ApproveSheet, MemberSheet, RevokeSheet } from './staffSheets';

const INVITE_TONE: Record<string, Tone> = { active: 'w', used: 'ok', revoked: 'x', expired: 'w' };

function InvitationsSection({ names }: { names: Map<string, string> }) {
  const invitations = useInvitations();
  const [revoking, setRevoking] = useState<Invitation | null>(null);

  return (
    <section aria-labelledby="staff-invitations">
      <SectionCaption id="staff-invitations">
        {strings.organization.invitationsCaption}
      </SectionCaption>
      {invitations.isPending && <Skeleton lines={2} />}
      {invitations.isError && (
        <ErrorState error={invitations.error} onRetry={() => void invitations.refetch()} />
      )}
      {invitations.isSuccess && invitations.data.length === 0 && (
        <Note>{strings.organization.noInvitations}</Note>
      )}
      {invitations.isSuccess && invitations.data.length > 0 && (
        <List>
          {invitations.data.map((invitation) => {
            const active = invitation.state === 'active';
            return (
              <ListRow
                key={invitation.id}
                title={roleWithPlaces(invitation.role, invitation.location_ids, names)}
                subtitle={
                  invitation.recipient_name
                    ? `${invitation.recipient_name} · ${strings.organization.inviteExpires(shortDateTime(invitation.expires_at))}`
                    : strings.organization.inviteExpires(shortDateTime(invitation.expires_at))
                }
                icon="?"
                gradient="n"
                tag={{
                  label: strings.organization.inviteTag[invitation.state] ?? invitation.state,
                  tone: INVITE_TONE[invitation.state] ?? 'w',
                }}
                chevron={active}
                onClick={active ? () => setRevoking(invitation) : undefined}
              />
            );
          })}
        </List>
      )}
      <RevokeSheet invitation={revoking} onClose={() => setRevoking(null)} />
    </section>
  );
}

function StaffContent({ names }: { names: Map<string, string> }) {
  const { activeMembership } = useSession();
  const staff = useStaff();
  const [approving, setApproving] = useState<StaffMember | null>(null);
  const [managing, setManaging] = useState<StaffMember | null>(null);
  const me = activeMembership!;
  const canInvite = canManageOrganization(me.role);

  return (
    <Screen
      title={strings.organization.staffTitle}
      actions={
        canInvite ? (
          <BottomActions>
            <ActionButton to="/organization/invite">
              {strings.organization.inviteButton}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      {staff.isPending && <Skeleton lines={4} />}
      {staff.isError && <ErrorState error={staff.error} onRetry={() => void staff.refetch()} />}
      {staff.isSuccess && staff.data.length === 0 && (
        <EmptyState title={strings.organization.noStaff} />
      )}
      {staff.isSuccess && staff.data.length > 0 && (
        <List>
          {staff.data.map((member) => {
            const pending = member.status === 'pending';
            const action = memberAction(member, me);
            return (
              <ListRow
                key={member.id}
                title={member.user.display_name}
                subtitle={
                  pending && member.accepted_at
                    ? `${roleWithPlaces(member.role, member.location_ids, names)} · ${strings.organization.memberPendingSince(shortDateTime(member.accepted_at))}`
                    : roleWithPlaces(member.role, member.location_ids, names)
                }
                icon={initials(member.user.display_name)}
                gradient={organizationGradient(member.user.id)}
                tag={
                  pending ? { label: strings.organization.memberPendingTag, tone: 'y' } : undefined
                }
                onClick={
                  action === 'approve'
                    ? () => setApproving(member)
                    : action === 'manage'
                      ? () => setManaging(member)
                      : undefined
                }
                chevron={action !== null}
              />
            );
          })}
        </List>
      )}

      {canInvite && <InvitationsSection names={names} />}
      <ApproveSheet member={approving} onClose={() => setApproving(null)} />
      <MemberSheet
        member={managing}
        subtitle={
          managing ? roleWithPlaces(managing.role, managing.location_ids, names) : undefined
        }
        onClose={() => setManaging(null)}
      />
    </Screen>
  );
}

function CustomerStaff() {
  const locations = useLocations();
  const names = new Map((locations.data ?? []).map((location) => [location.id, location.name]));
  return <StaffContent names={names} />;
}

const NO_NAMES = new Map<string, string>();

export function StaffScreen() {
  const { activeMembership } = useSession();
  if (!activeMembership) return null;
  if (!canManageOrganization(activeMembership.role)) {
    return (
      <Screen title={strings.organization.staffTitle}>
        <NoAccessState />
      </Screen>
    );
  }
  return activeMembership.side === 'customer' ? (
    <CustomerStaff />
  ) : (
    <StaffContent names={NO_NAMES} />
  );
}
