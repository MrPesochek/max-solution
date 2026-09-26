import { useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useCurrentOrganization, useUpdateOrganization } from '../../api/hooks/useOrganizations';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { Skeleton } from '../../components/states/Skeleton';
import { useSession } from '../../session/SessionContext';
import { canManageOrganization } from '../../lib/roles';
import { Banner, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { PhoneField, TextField } from '../../ui/FormField';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import type { Organization, UpdateOrganizationInput } from '../../api/types';

const FORM_ID = 'organization-profile';

export function OrganizationProfileRows({ organization }: { organization: Organization }) {
  const navigate = useNavigate();
  const contact = [organization.contact_name, organization.contact_phone]
    .filter(Boolean)
    .join(', ');
  return (
    <section aria-labelledby="org-profile-caption">
      <SectionCaption id="org-profile-caption">{strings.organization.profileTitle}</SectionCaption>
      <List>
        <ListRow
          title={strings.organization.contactLabel}
          value={contact || strings.common.notSpecified}
          valueTone="secondary"
        />
        <ListRow
          title={strings.organization.emailLabel}
          value={organization.contact_email || strings.common.notSpecified}
          valueTone="secondary"
        />
        <ListRow
          title={strings.organization.profileEdit}
          action="accent"
          onClick={() => navigate('/organization/profile')}
        />
      </List>
    </section>
  );
}

function ProfileForm({ organization: current }: { organization: Organization }) {
  const [organization] = useState(current);
  const navigate = useNavigate();
  const update = useUpdateOrganization();
  const { refreshMemberships } = useSession();
  const [name, setName] = useState(organization.name);
  const [contactName, setContactName] = useState(organization.contact_name ?? '');
  const [contactPhone, setContactPhone] = useState(organization.contact_phone ?? '');
  const [contactEmail, setContactEmail] = useState(organization.contact_email ?? '');
  const [inn, setInn] = useState(organization.inn ?? '');
  const [error, setError] = useState<string | null>(null);

  const changes: UpdateOrganizationInput = {};
  if (name.trim() !== organization.name) changes.name = name.trim();
  if (contactName.trim() !== (organization.contact_name ?? ''))
    changes.contact_name = contactName.trim() || null;
  if (contactPhone.trim() !== (organization.contact_phone ?? ''))
    changes.contact_phone = contactPhone.trim() || null;
  if (contactEmail.trim() !== (organization.contact_email ?? ''))
    changes.contact_email = contactEmail.trim() || null;
  if (inn.trim() !== (organization.inn ?? '')) changes.inn = inn.trim() || null;
  const hasChanges = Object.keys(changes).length > 0;
  const innLocked = organization.details_verification_status === 'verified';
  const done = () => navigate('/organization', { replace: true });

  const handleSave = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!hasChanges || !name.trim()) return;
    try {
      await update.mutateAsync(changes);
      if (changes.name) await refreshMemberships().catch(() => undefined);
      done();
    } catch (e) {
      setError(actionErrorMessage(e, strings.organization.profileSaveError));
    }
  };

  return (
    <Screen
      title={strings.organization.profileEditTitle}
      actions={
        <BottomActions>
          <ActionButton
            type="submit"
            form={FORM_ID}
            disabled={!hasChanges || !name.trim()}
            loading={update.isPending}
          >
            {strings.common.save}
          </ActionButton>
          <ActionButton kind="s" onClick={done} disabled={update.isPending}>
            {strings.common.cancel}
          </ActionButton>
        </BottomActions>
      }
    >
      <form id={FORM_ID} onSubmit={handleSave} noValidate>
        <TextField
          id="org-profile-name"
          label={strings.orgForm.name}
          value={name}
          onChange={setName}
        />
        <TextField
          id="org-profile-contact-name"
          label={strings.organization.contactNameLabel}
          value={contactName}
          onChange={setContactName}
        />
        <PhoneField
          id="org-profile-phone"
          label={strings.orgForm.contactPhone}
          value={contactPhone}
          onChange={setContactPhone}
        />
        <TextField
          id="org-profile-email"
          type="email"
          inputMode="email"
          autoComplete="email"
          label={strings.organization.emailLabel}
          value={contactEmail}
          onChange={setContactEmail}
        />
        <TextField
          id="org-profile-inn"
          label={strings.organization.innLabel}
          inputMode="numeric"
          maxLength={12}
          value={inn}
          disabled={innLocked}
          hint={innLocked ? strings.organization.innLockedHint : undefined}
          onChange={(value) => setInn(value.replace(/\D/g, ''))}
        />
        {error && <Banner tone="x" role="alert" title={error} />}
      </form>
    </Screen>
  );
}

export function OrganizationProfileScreen() {
  const { activeMembership } = useSession();
  const organization = useCurrentOrganization();
  const frame = (body: ReactNode) => (
    <Screen title={strings.organization.profileEditTitle}>{body}</Screen>
  );

  if (!activeMembership) return null;
  if (!canManageOrganization(activeMembership.role)) return frame(<NoAccessState />);
  if (organization.isPending) return frame(<Skeleton lines={5} />);
  if (organization.isError) {
    return frame(
      <ErrorState error={organization.error} onRetry={() => void organization.refetch()} />,
    );
  }
  return <ProfileForm organization={organization.data} />;
}
