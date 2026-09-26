import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useCreateInvitation } from '../../api/hooks/useInvitations';
import { useLocations } from '../../api/hooks/useLocations';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { NoAccessState } from '../../components/states/NoAccessState';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { useSession } from '../../session/SessionContext';
import { canManageOrganization } from '../../lib/roles';
import { Banner, Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List } from '../../ui/List';
import { ChipGroup } from '../../ui/Chips';
import { TextField } from '../../ui/FormField';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows, type KeyValueRow } from '../../ui/KeyValueRows';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { shortDateTime } from '../../ui/format';
import type { InvitationIssued, Location, Role } from '../../api/types';
import { InviteCopyRow, InviteShareButton } from './InviteLinkField';

const CUSTOMER_ROLES: Role[] = ['customer_employee', 'customer_manager'];
const PROVIDER_ROLES: Role[] = ['provider_dispatcher', 'provider_admin'];

function CreatedInvitation({
  invitation,
  placesText,
}: {
  invitation: InvitationIssued;
  placesText: string | null;
}) {
  const navigate = useNavigate();
  const link = invitation.webapp_link ?? invitation.bot_link ?? null;
  const rows: KeyValueRow[] = [
    {
      label: strings.organization.role,
      value: invitation.role
        ? strings.home.roleShort[invitation.role]
        : strings.common.notSpecified,
    },
    ...(placesText ? [{ label: strings.organization.locationsAccess, value: placesText }] : []),
    ...(invitation.recipient_name
      ? [{ label: strings.organization.recipientRow, value: invitation.recipient_name }]
      : []),
    {
      label: strings.organization.accessRow,
      value: invitation.named
        ? strings.organization.accessNamed
        : strings.organization.accessOnApproval,
    },
    { label: strings.organization.inviteExpiresAt, value: shortDateTime(invitation.expires_at) },
  ];
  return (
    <Screen
      title={strings.organization.inviteTitle}
      back="/organization/staff"
      actions={
        <BottomActions>
          {link && <InviteShareButton link={link} />}
          <ActionButton kind="s" onClick={() => navigate('/organization/staff', { replace: true })}>
            {strings.organization.inviteDone}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="invitation" height={150} />
      <PageTitle
        subtitle={strings.organization.inviteCreatedText(shortDateTime(invitation.expires_at))}
      >
        {strings.organization.inviteCreated}
      </PageTitle>
      <KeyValueRows rows={rows} aria-label={strings.organization.inviteCreated} />
      <List>
        {invitation.webapp_link && (
          <InviteCopyRow
            label={strings.organization.inviteCopyWebapp}
            value={invitation.webapp_link}
          />
        )}
        {invitation.bot_link && (
          <InviteCopyRow label={strings.organization.inviteCopyBot} value={invitation.bot_link} />
        )}
      </List>
      <Note>
        {invitation.named
          ? strings.organization.inviteNamedNote
          : strings.organization.inviteSecretNote}
      </Note>
    </Screen>
  );
}

function InvitationForm({
  locations,
  isCustomerOrg,
}: {
  locations: Location[];
  isCustomerOrg: boolean;
}) {
  const createInvitation = useCreateInvitation();
  const roleOptions = isCustomerOrg ? CUSTOMER_ROLES : PROVIDER_ROLES;
  const [role, setRole] = useState<Role>(roleOptions[0]!);
  const [locationIds, setLocationIds] = useState<string[]>(() =>
    locations.length === 1 ? [locations[0]!.id] : [],
  );
  const [recipientName, setRecipientName] = useState('');
  const [recipientMaxId, setRecipientMaxId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<InvitationIssued | null>(null);

  const needsLocations = role === 'customer_employee';
  const placesText = !isCustomerOrg
    ? null
    : role === 'customer_manager'
      ? strings.organization.allLocations
      : locations
          .filter((location) => locationIds.includes(location.id))
          .map((location) => location.name)
          .join(', ');

  if (created) return <CreatedInvitation invitation={created} placesText={placesText} />;

  const canSubmit = !needsLocations || locationIds.length > 0;

  const handleCreate = async () => {
    setError(null);
    if (!canSubmit) return;
    try {
      setCreated(
        await createInvitation.mutateAsync({
          role,
          location_ids: isCustomerOrg
            ? needsLocations
              ? locationIds
              : locations.map((l) => l.id)
            : [],
          recipient_name: recipientName.trim() || null,
          recipient_max_user_id: recipientMaxId.trim() || null,
        }),
      );
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <Screen
      title={strings.organization.inviteTitle}
      actions={
        <BottomActions>
          <ActionButton
            disabled={!canSubmit}
            loading={createInvitation.isPending}
            onClick={() => void handleCreate()}
          >
            {strings.organization.createLink}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={strings.organization.inviteSubtitle}>
        {strings.organization.inviteHeading}
      </PageTitle>
      <SectionCaption id="invite-role">{strings.organization.roleCaption}</SectionCaption>
      <ChipGroup
        label={strings.organization.roleCaption}
        value={role}
        onChange={setRole}
        options={roleOptions.map((option) => ({
          value: option,
          label: strings.home.roleShort[option],
        }))}
      />
      {strings.organization.roleHint[role] && <Note>{strings.organization.roleHint[role]}</Note>}

      {needsLocations && (
        <section aria-labelledby="invite-locations">
          <SectionCaption id="invite-locations">
            {strings.organization.locationsAccess}
          </SectionCaption>
          <ChipGroup
            multiple
            label={strings.organization.locationsAccess}
            value={locationIds}
            onChange={setLocationIds}
            options={locations.map((location) => ({ value: location.id, label: location.name }))}
          />
          {locationIds.length === 0 && <Note>{strings.organization.inviteLocationsRequired}</Note>}
        </section>
      )}

      <section aria-labelledby="invite-recipient">
        <SectionCaption id="invite-recipient">{strings.organization.recipientCaption}</SectionCaption>
        <TextField
          label={strings.organization.recipientNameLabel}
          hint={strings.organization.recipientNameHint}
          value={recipientName}
          maxLength={200}
          autoComplete="off"
          onChange={setRecipientName}
        />
        <TextField
          label={strings.organization.recipientIdLabel}
          hint={strings.organization.recipientIdHint}
          value={recipientMaxId}
          maxLength={64}
          autoComplete="off"
          onChange={setRecipientMaxId}
        />
      </section>

      {error && <Banner tone="x" role="alert" title={error} />}
      <Note>{strings.organization.inviteNote}</Note>
    </Screen>
  );
}

function CustomerInvitationForm() {
  const locations = useLocations();
  if (locations.isPending) {
    return (
      <Screen title={strings.organization.inviteTitle}>
        <Skeleton lines={4} />
      </Screen>
    );
  }
  if (locations.isError) {
    return (
      <Screen title={strings.organization.inviteTitle}>
        <ErrorState error={locations.error} onRetry={() => void locations.refetch()} />
      </Screen>
    );
  }
  return <InvitationForm locations={locations.data} isCustomerOrg />;
}

export function NewInvitationScreen() {
  const { activeMembership } = useSession();
  if (!activeMembership) return null;
  if (!canManageOrganization(activeMembership.role)) {
    return (
      <Screen title={strings.organization.inviteTitle}>
        <NoAccessState />
      </Screen>
    );
  }
  return activeMembership.side === 'customer' ? (
    <CustomerInvitationForm />
  ) : (
    <InvitationForm locations={[]} isCustomerOrg={false} />
  );
}
