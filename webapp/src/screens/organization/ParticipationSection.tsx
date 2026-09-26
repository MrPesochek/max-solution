import { useState, type FormEvent, type ReactNode } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { useAddParticipation, useCurrentOrganization } from '../../api/hooks/useOrganizations';
import { useCities } from '../../api/hooks/useDirectories';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { Skeleton } from '../../components/states/Skeleton';
import { canManageOrganization } from '../../lib/roles';
import { Banner, Note, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { SelectField, TextAreaField, TextField } from '../../ui/FormField';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import type { Organization, OrganizationKind, ProviderKind } from '../../api/types';

const FORM_ID = 'participation';

function missingKind(org: Organization): OrganizationKind | null {
  if (!org.kinds.includes('provider')) return 'provider';
  if (!org.kinds.includes('customer')) return 'customer';
  return null;
}

export function ParticipationRow({ organization }: { organization: Organization }) {
  const navigate = useNavigate();
  const missing = missingKind(organization);
  if (!missing) return null;
  return (
    <List>
      <ListRow
        title={strings.organization.participationTitle[missing]}
        action="accent"
        onClick={() => navigate('/organization/participation')}
      />
    </List>
  );
}

function ParticipationForm({
  organization,
  kind,
}: {
  organization: Organization;
  kind: OrganizationKind;
}) {
  const navigate = useNavigate();
  const { activateMembership } = useSession();
  const cities = useCities();
  const addParticipation = useAddParticipation(organization.id);

  const [providerKind, setProviderKind] = useState<ProviderKind>('company');
  const [locationName, setLocationName] = useState('');
  const [cityId, setCityId] = useState('');
  const [districtId, setDistrictId] = useState('');
  const [address, setAddress] = useState('');
  const [error, setError] = useState<string | null>(null);

  const isCustomer = kind === 'customer';
  const selectedCity = cities.data?.find((c) => c.id === cityId);
  const canSubmit = !isCustomer || Boolean(locationName.trim() && cityId && address.trim());
  const title = strings.organization.participationTitle[kind];

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!canSubmit) return;
    try {
      const result = await addParticipation.mutateAsync(
        isCustomer
          ? {
              kind,
              first_location: {
                name: locationName.trim(),
                city_id: cityId,
                district_id: districtId || null,
                address: address.trim(),
              },
            }
          : { kind, provider_kind: providerKind },
      );
      activateMembership(result.membership);
      navigate('/', { replace: true });
    } catch (e) {
      setError(actionErrorMessage(e, strings.organization.participationError));
    }
  };

  return (
    <Screen
      title={title}
      subtitle={organization.name}
      actions={
        <BottomActions>
          <ActionButton
            type="submit"
            form={FORM_ID}
            disabled={!canSubmit}
            loading={addParticipation.isPending}
          >
            {title}
          </ActionButton>
        </BottomActions>
      }
    >
      <Note>
        {isCustomer
          ? strings.organization.participationCustomerHint
          : strings.organization.participationProviderHint}
      </Note>
      <form id={FORM_ID} onSubmit={handleSubmit} noValidate>
        {!isCustomer && (
          <SelectField
            id="participation-provider-kind"
            label={strings.organization.participationProviderKind}
            value={providerKind}
            onChange={(value) => setProviderKind(value as ProviderKind)}
            options={[
              { value: 'company', label: strings.organization.providerKindCompany },
              {
                value: 'independent_specialist',
                label: strings.organization.providerKindIndependent,
              },
            ]}
          />
        )}

        {isCustomer && (
          <section aria-labelledby="participation-location">
            <SectionCaption id="participation-location">
              {strings.orgForm.firstLocationTitle}
            </SectionCaption>
            <TextField
              id="participation-location-name"
              label={strings.orgForm.locationName}
              value={locationName}
              onChange={setLocationName}
            />
            <SelectField
              id="participation-city"
              label={strings.orgForm.city}
              value={cityId}
              placeholder={strings.common.notSpecified}
              onChange={(value) => {
                setCityId(value);
                setDistrictId('');
              }}
              options={(cities.data ?? []).map((city) => ({ value: city.id, label: city.name }))}
            />
            <SelectField
              id="participation-district"
              label={strings.orgForm.district}
              value={districtId}
              placeholder={strings.common.notSpecified}
              allowEmpty
              disabled={!selectedCity}
              onChange={setDistrictId}
              options={(selectedCity?.districts ?? []).map((d) => ({ value: d.id, label: d.name }))}
            />
            <TextAreaField
              id="participation-address"
              label={strings.orgForm.address}
              value={address}
              onChange={setAddress}
              rows={2}
            />
          </section>
        )}

        {error && <Banner tone="x" role="alert" title={error} />}
      </form>
    </Screen>
  );
}

export function ParticipationScreen() {
  const { activeMembership } = useSession();
  const organization = useCurrentOrganization();
  const [snapshot, setSnapshot] = useState<{
    org: Organization;
    kind: OrganizationKind | null;
  } | null>(null);
  if (organization.data && !snapshot) {
    setSnapshot({ org: organization.data, kind: missingKind(organization.data) });
  }
  const frame = (body: ReactNode) => <Screen title={strings.organization.title}>{body}</Screen>;

  if (!activeMembership) return null;
  if (!canManageOrganization(activeMembership.role)) return frame(<NoAccessState />);
  if (snapshot) {
    if (!snapshot.kind) return <Navigate to="/organization" replace />;
    return <ParticipationForm organization={snapshot.org} kind={snapshot.kind} />;
  }
  if (organization.isError) {
    return frame(
      <ErrorState error={organization.error} onRetry={() => void organization.refetch()} />,
    );
  }
  return frame(<Skeleton lines={4} />);
}
