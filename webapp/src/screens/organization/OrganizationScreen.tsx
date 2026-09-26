import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { useCurrentOrganization } from '../../api/hooks/useOrganizations';
import { useLocations } from '../../api/hooks/useLocations';
import { useStaff } from '../../api/hooks/useMemberships';
import { useInvitations } from '../../api/hooks/useInvitations';
import { useBindingsList } from '../../api/hooks/useBindings';
import { ErrorState } from '../../components/states/ErrorState';
import { SectionLinks } from '../../components/layout/SectionLinks';
import {
  canManageBindings,
  canManageLocationsAndEquipment,
  canManageOrganization,
} from '../../lib/roles';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { SkeletonRows } from '../../ui/Skeleton';
import { useLayout } from '../../ui/layout/layoutContext';
import { ThemeSwitcher } from '../../ui/theme/ThemeSwitcher';
import { initials, shortDateTime } from '../../ui/format';
import type { Invitation, Location, Organization, StaffMember } from '../../api/types';
import type { Tone } from '../../ui/blocks/Blocks';
import { countLabel } from '../reviews/reputation';
import { OrganizationProfileRows } from './OrganizationProfileSection';
import { ParticipationRow } from './ParticipationSection';
import { MembershipSwitchList } from './MembershipSwitchList';
import { roleWithPlaces } from './staffLabels';
import { memberAction } from './memberAction';
import { ApproveSheet, MemberSheet, RevokeSheet } from './staffSheets';
import { PlusIcon } from '../../ui/icons';
import './organization.css';

const VERIFICATION_TONE: Record<string, Tone> = {
  verified: 'ok',
  pending: 'a',
  needs_information: 'y',
  rejected: 'x',
};

function orgSubtitle(inn: string | null | undefined, role: string): string {
  const you = strings.organization.youAre[role] ?? '';
  return [inn ? strings.organization.innLine(inn) : strings.organization.innMissing, you]
    .filter(Boolean)
    .join(' · ');
}

function LinkedCaption({
  id,
  to,
  children,
  action,
}: {
  id: string;
  to: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <SectionCaption id={id} action={action}>
      <Link className="org-caption-link" to={to}>
        {children}
      </Link>
    </SectionCaption>
  );
}

function locationSubtitle(location: Location): string {
  return typeof location.equipment_count === 'number'
    ?
      countLabel(location.equipment_count, strings.locations.equipmentForms).replace(' ', ' ')
    : location.address;
}

function LocationsSection() {
  const locations = useLocations();
  return (
    <section aria-labelledby="org-locations">
      <LinkedCaption
        id="org-locations"
        to="/locations"
        action={<Link to="/locations/new">{strings.organization.addLocation}</Link>}
      >
        {strings.ui.sections.locations}
      </LinkedCaption>
      {locations.isPending && <SkeletonRows rows={2} />}
      {locations.isError && (
        <ErrorState error={locations.error} onRetry={() => void locations.refetch()} />
      )}
      {locations.isSuccess && locations.data.length === 0 && (
        <p className="org-empty">{strings.locations.emptyText}</p>
      )}
      {locations.isSuccess && locations.data.length > 0 && (
        <List>
          {locations.data.map((location) => (
            <ListRow
              key={location.id}
              title={location.name}
              subtitle={locationSubtitle(location)}
              to={`/locations/${location.id}`}
              chevron
            />
          ))}
        </List>
      )}
    </section>
  );
}

function CustomerStaffSection() {
  const locations = useLocations();
  const names = new Map((locations.data ?? []).map((location) => [location.id, location.name]));
  return <StaffSection names={names} />;
}

const NO_NAMES = new Map<string, string>();

function StaffSection({ names }: { names: Map<string, string> }) {
  const { activeMembership } = useSession();
  const staff = useStaff();
  const invitations = useInvitations();
  const [approving, setApproving] = useState<StaffMember | null>(null);
  const [managing, setManaging] = useState<StaffMember | null>(null);
  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const me = activeMembership!;
  const activeInvitations = (invitations.data ?? []).filter((item) => item.state === 'active');

  return (
    <section aria-labelledby="org-staff">
      <LinkedCaption id="org-staff" to="/organization/staff">
        {strings.organization.staffTitle}
      </LinkedCaption>
      {staff.isPending && <SkeletonRows rows={3} />}
      {staff.isError && <ErrorState error={staff.error} onRetry={() => void staff.refetch()} />}
      {staff.isSuccess && (
        <List>
          {staff.data.map((member) => {
            const pending = member.status === 'pending';
            const action = memberAction(member, me);
            return (
              <ListRow
                key={member.id}
                title={member.user.display_name}
                subtitle={roleWithPlaces(member.role, member.location_ids, names)}
                icon={initials(member.user.display_name)}
                gradient={pending ? 'n' : 'o'}
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
          {activeInvitations.map((invitation) => (
            <ListRow
              key={invitation.id}
              title={strings.organization.invitationSent}
              subtitle={strings.organization.invitationWaiting(
                roleWithPlaces(invitation.role, invitation.location_ids, names),
                shortDateTime(invitation.expires_at),
              )}
              icon="?"
              gradient="n"
              value={strings.common.revoke}
              valueTone="secondary"
              aria-label={`${strings.common.revoke}: ${roleWithPlaces(invitation.role, invitation.location_ids, names)}`}
              onClick={() => setRevoking(invitation)}
            />
          ))}
        </List>
      )}
      <ApproveSheet member={approving} onClose={() => setApproving(null)} />
      <MemberSheet
        member={managing}
        subtitle={
          managing ? roleWithPlaces(managing.role, managing.location_ids, names) : undefined
        }
        onClose={() => setManaging(null)}
      />
      <RevokeSheet invitation={revoking} onClose={() => setRevoking(null)} />
    </section>
  );
}

function BindingsRow() {
  const bindings = useBindingsList();
  return (
    <ListRow
      title={strings.ui.sections.bindings}
      value={bindings.data?.filter((binding) => binding.status === 'confirmed').length}
      valueTone="secondary"
      to="/bindings"
      chevron
    />
  );
}

function VerificationRows({
  organization,
  isCustomerOrg,
}: {
  organization: Organization;
  isCustomerOrg: boolean;
}) {
  const details = organization.details_verification_status ?? 'unverified';
  const representative = organization.representative_verification_status ?? 'unverified';
  return (
    <section aria-labelledby="org-verification">
      <SectionCaption id="org-verification">
        {strings.organization.verificationCaption}
      </SectionCaption>
      <List>
        <ListRow
          title={strings.organization.requisitesTitle}
          tag={{
            label:
              strings.organization.requisitesTag[details] ??
              strings.organization.requisitesTag.unverified!,
            tone: VERIFICATION_TONE[details] ?? 'w',
          }}
        />
        <ListRow
          title={strings.organization.representativeTitle}
          subtitle={strings.organization.representativeHint}
          tag={{
            label:
              strings.organization.representativeTag[representative] ??
              strings.organization.representativeTag.unverified!,
            tone: VERIFICATION_TONE[representative] ?? 'w',
          }}
          to={isCustomerOrg ? undefined : '/provider/verification'}
          chevron={!isCustomerOrg}
        />
      </List>
    </section>
  );
}

function SwitchRows() {
  const layout = useLayout();
  return (
    <>
      <List>
        <ListRow
          title={strings.header.switchOrganization}
          action="accent"
          onClick={layout.switchOrganization}
        />
      </List>
      <MembershipSwitchList />
    </>
  );
}

export function OrganizationScreen() {
  const { activeMembership } = useSession();
  const canManage = activeMembership ? canManageOrganization(activeMembership.role) : false;
  const organization = useCurrentOrganization();

  if (!activeMembership) return null;
  const role = activeMembership.role;
  const isCustomerOrg = activeMembership.side === 'customer';

  const footer = (
    <>
      <SectionLinks />
      <ThemeSwitcher />
    </>
  );

  if (!canManage) {
    return (
      <Screen title={strings.organization.title}>
        <PageTitle size="m" subtitle={strings.roles[role]}>
          {activeMembership.organization.name}
        </PageTitle>
        <SwitchRows />
        {footer}
      </Screen>
    );
  }

  const org = organization.data;

  return (
    <Screen
      title={strings.organization.title}
      actions={
        <BottomActions>
          <ActionButton to="/organization/invite">
            <PlusIcon className="org-plus" />
            {strings.organization.inviteButton}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle size="m" subtitle={org ? orgSubtitle(org.inn, role) : undefined}>
        {org?.name ?? activeMembership.organization.name}
      </PageTitle>
      {organization.isError && (
        <ErrorState error={organization.error} onRetry={() => void organization.refetch()} />
      )}

      {isCustomerOrg && canManageLocationsAndEquipment(role) && <LocationsSection />}
      {isCustomerOrg ? <CustomerStaffSection /> : <StaffSection names={NO_NAMES} />}

      {org && <VerificationRows organization={org} isCustomerOrg={isCustomerOrg} />}

      {organization.isPending ? (
        <SkeletonRows rows={2} />
      ) : (
        org && <OrganizationProfileRows organization={org} />
      )}

      {isCustomerOrg && (
        <section aria-labelledby="org-more">
          <SectionCaption id="org-more">{strings.organization.otherCaption}</SectionCaption>
          <List>
            {canManageBindings(role) && <BindingsRow />}
            <ListRow title={strings.ui.sections.complaints} to="/complaints" chevron />
          </List>
        </section>
      )}
      {org && <ParticipationRow organization={org} />}
      <SwitchRows />

      {footer}
    </Screen>
  );
}
