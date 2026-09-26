import { useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useCities } from '../../api/hooks/useDirectories';
import { useCreateOrganization } from '../../api/hooks/useOrganizations';
import { ApiError } from '../../api/errors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { useSession } from '../../session/SessionContext';
import { isValidInn } from '../../lib/inn';
import { Banner, Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { PhoneField, SelectField, TextField } from '../../ui/FormField';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { ChipGroup } from '../../ui/Chips';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import type { City, CreateOrganizationInput, OrganizationKind } from '../../api/types';
import { StandaloneScreen } from './StandaloneScreen';
import './onboarding.css';

const FORM_ID = 'create-organization';

type ProviderType = 'company' | 'self';
type SelfForm = 'ip' | 'self_employed';

const digitsOnly = (value: string) => value.replace(/\D/g, '').slice(0, 12);

function focusFirst(errors: [string, unknown][]) {
  const first = errors.find(([, error]) => Boolean(error));
  if (first) document.getElementById(first[0])?.focus();
}

function customerInnHint(inn: string): string {
  if (!inn) return strings.orgForm.innHintEmpty;
  if (inn.length === 10 || inn.length === 12) return strings.orgForm.innHintOk;
  return strings.orgForm.innHintLeft((inn.length < 10 ? 10 : 12) - inn.length);
}

export function CreateOrganizationScreen() {
  const { kind } = useParams<{ kind: OrganizationKind }>();
  const cities = useCities();

  const frame = (body: ReactNode) => (
    <StandaloneScreen title={strings.orgForm.title} back="/onboarding">
      {body}
    </StandaloneScreen>
  );

  if (kind !== 'customer' && kind !== 'provider') {
    return frame(<ErrorState message={strings.orgForm.unknownKind} />);
  }
  if (kind === 'provider') return <ProviderStart />;

  if (cities.isPending) return frame(<Skeleton lines={4} />);
  if (cities.isError) {
    return frame(<ErrorState error={cities.error} onRetry={() => void cities.refetch()} />);
  }
  return <CustomerForm cities={cities.data} />;
}

function useCreateAndEnter() {
  const navigate = useNavigate();
  const { refreshMemberships, activateMembership } = useSession();
  const createOrganization = useCreateOrganization();
  const [innServerError, setInnServerError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const create = async (input: CreateOrganizationInput, next: string) => {
    setFormError(null);
    setInnServerError(null);
    try {
      const created = await createOrganization.mutateAsync(input);
      await refreshMemberships();
      activateMembership(created.membership);
      navigate(created.membership.status === 'active' ? next : '/organizations', { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.code === 'INN_ALREADY_VERIFIED') {
        setInnServerError(strings.orgForm.innTaken);
        return;
      }
      setFormError(error instanceof ApiError ? error.message : strings.common.unknownError);
    }
  };

  return {
    create,
    busy: createOrganization.isPending,
    innServerError,
    clearInnServerError: () => setInnServerError(null),
    formError,
  };
}

function CustomerForm({ cities }: { cities: City[] }) {
  const { create, busy, innServerError, clearInnServerError, formError } = useCreateAndEnter();

  const [name, setName] = useState('');
  const [inn, setInn] = useState('');
  const [innTouched, setInnTouched] = useState(false);
  const [contactPhone, setContactPhone] = useState('');
  const [locationName, setLocationName] = useState('');
  const [cityId, setCityId] = useState(cities.length === 1 ? cities[0]!.id : '');
  const [districtId, setDistrictId] = useState('');
  const [address, setAddress] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const selectedCity = cities.find((city) => city.id === cityId);
  const needsDistrict = (selectedCity?.districts.length ?? 0) > 0;
  const innInvalid = inn.length > 0 && !isValidInn(inn);
  const innError = innServerError ?? (innTouched && innInvalid ? strings.orgForm.innInvalid : null);

  const o = strings.orgForm;
  const required = (ok: boolean, message: string) => (submitted && !ok ? message : undefined);
  const fieldErrors: [string, string | null | undefined][] = [
    ['org-inn', innError ?? (submitted && innInvalid ? o.innInvalid : undefined)],
    ['org-name', required(Boolean(name.trim()), o.requiredName)],
    ['org-phone', required(Boolean(contactPhone.trim()), o.requiredPhone)],
    ['loc-name', required(Boolean(locationName.trim()), o.requiredLocationName)],
    ['loc-city', required(Boolean(cityId), o.requiredCity)],
    ['loc-address', required(Boolean(address.trim()), o.requiredAddress)],
  ];
  const errorOf = (id: string) => fieldErrors.find(([key]) => key === id)?.[1] ?? undefined;

  const canSubmit =
    name.trim().length > 0 &&
    contactPhone.trim().length > 0 &&
    !innInvalid &&
    Boolean(locationName.trim() && cityId && address.trim());

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) {
      setInnTouched(true);
      setSubmitted(true);
      focusFirst([
        ['org-inn', innInvalid],
        ['org-name', !name.trim()],
        ['org-phone', !contactPhone.trim()],
        ['loc-name', !locationName.trim()],
        ['loc-city', !cityId],
        ['loc-address', !address.trim()],
      ]);
      return;
    }
    void create(
      {
        name: name.trim(),
        contact_phone: contactPhone.trim(),
        inn: inn || null,
        kind: 'customer',
        first_location: {
          name: locationName.trim(),
          city_id: cityId,
          district_id: districtId || null,
          address: address.trim(),
        },
      },
      '/',
    );
  };

  return (
    <StandaloneScreen
      title={strings.orgForm.title}
      back="/onboarding"
      actions={
        <BottomActions>
          <ActionButton type="submit" form={FORM_ID} loading={busy}>
            {strings.orgForm.submitCustomer}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={strings.orgForm.customerSubtitle}>
        {strings.orgForm.customerTitle}
      </PageTitle>
      <form id={FORM_ID} onSubmit={handleSubmit} noValidate>
        <TextField
          id="org-inn"
          label={strings.orgForm.inn}
          className="ui-field__control--mono"
          value={inn}
          inputMode="numeric"
          maxLength={12}
          placeholder={strings.orgForm.innPlaceholder}
          error={errorOf('org-inn')}
          hint={errorOf('org-inn') ? undefined : customerInnHint(inn)}
          onChange={(value) => {
            setInn(digitsOnly(value));
            clearInnServerError();
          }}
          onBlur={() => setInnTouched(true)}
        />
        <TextField
          id="org-name"
          label={strings.orgForm.name}
          placeholder={strings.orgForm.namePlaceholder}
          value={name}
          onChange={setName}
          autoComplete="organization"
          required
          error={errorOf('org-name')}
        />
        <PhoneField
          id="org-phone"
          label={strings.orgForm.contactPhone}
          hint={strings.orgForm.contactPhoneHint}
          required
          error={errorOf('org-phone')}
          value={contactPhone}
          onChange={setContactPhone}
        />

        <section aria-labelledby="org-first-location">
          <SectionCaption id="org-first-location">
            {strings.orgForm.firstLocationTitle}
          </SectionCaption>
          <TextField
            id="loc-name"
            label={strings.orgForm.locationName}
            placeholder={strings.orgForm.locationNamePlaceholder}
            value={locationName}
            onChange={setLocationName}
            required
            error={errorOf('loc-name')}
          />
          {cities.length > 1 && (
            <SelectField
              id="loc-city"
              label={strings.orgForm.city}
              value={cityId}
              required
              error={errorOf('loc-city')}
              placeholder={strings.common.notSpecified}
              onChange={(value) => {
                setCityId(value);
                setDistrictId('');
              }}
              options={cities.map((city) => ({ value: city.id, label: city.name }))}
            />
          )}
          {needsDistrict && (
            <SelectField
              id="loc-district"
              label={strings.orgForm.district}
              value={districtId}
              placeholder={strings.common.notSpecified}
              disabled={!selectedCity}
              onChange={setDistrictId}
              options={(selectedCity?.districts ?? []).map((district) => ({
                value: district.id,
                label: district.name,
              }))}
            />
          )}
          <TextField
            id="loc-address"
            label={strings.orgForm.address}
            placeholder={strings.orgForm.addressPlaceholder}
            hint={strings.orgForm.firstLocationHint}
            value={address}
            onChange={setAddress}
            autoComplete="street-address"
            required
            error={errorOf('loc-address')}
          />
        </section>

        {formError && <Banner tone="x" role="alert" title={formError} />}
      </form>
    </StandaloneScreen>
  );
}

function ProviderStart() {
  const { create, busy, innServerError, clearInnServerError, formError } = useCreateAndEnter();
  const [type, setType] = useState<ProviderType>('company');
  const [selfForm, setSelfForm] = useState<SelfForm>('self_employed');
  const [name, setName] = useState('');
  const [inn, setInn] = useState('');
  const [innTouched, setInnTouched] = useState(false);
  const [contactPhone, setContactPhone] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const company = type === 'company';
  const innComplete = company ? inn.length === 10 || inn.length === 12 : inn.length === 12;
  const innInvalid = innComplete && !isValidInn(inn);
  const innError =
    innServerError ??
    (innTouched && inn.length > 0 && (!innComplete || innInvalid)
      ? strings.orgForm.innInvalidProvider
      : submitted && inn.length === 0
        ? strings.orgForm.requiredInnProvider
        : null);
  const nameError =
    submitted && !name.trim()
      ? company
        ? strings.orgForm.requiredName
        : strings.orgForm.requiredSelfName
      : undefined;
  const phoneError = submitted && !contactPhone.trim() ? strings.orgForm.requiredPhone : undefined;
  const canSubmit =
    name.trim().length > 0 && contactPhone.trim().length > 0 && innComplete && !innInvalid;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) {
      setInnTouched(true);
      setSubmitted(true);
      focusFirst([
        ['org-inn', !innComplete || innInvalid],
        ['org-name', !name.trim()],
        ['org-phone', !contactPhone.trim()],
      ]);
      return;
    }
    void create(
      {
        name: name.trim(),
        contact_phone: contactPhone.trim(),
        inn,
        kind: 'provider',
        provider_kind: company ? 'company' : 'independent_specialist',
        legal_form: company ? (inn.length === 12 ? 'ip' : 'ooo') : selfForm,
      },
      '/provider/profile/edit',
    );
  };

  return (
    <StandaloneScreen
      title={strings.orgForm.title}
      back="/onboarding"
      actions={
        <BottomActions>
          <ActionButton type="submit" form={FORM_ID} loading={busy}>
            {strings.orgForm.submitProvider}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={strings.orgForm.providerSubtitle}>
        {strings.orgForm.providerTitle}
      </PageTitle>
      <ChoiceGroup label={strings.orgForm.providerKindLabel}>
        <ChoiceCard
          title={strings.orgForm.providerCompany}
          subtitle={strings.orgForm.providerCompanyHint}
          selected={company}
          onSelect={() => setType('company')}
        />
        <ChoiceCard
          title={strings.orgForm.providerSelf}
          subtitle={strings.orgForm.providerSelfHint}
          selected={!company}
          onSelect={() => setType('self')}
        />
      </ChoiceGroup>
      {!company && (
        <div className="onb-subchoice">
          <ChipGroup
            label={strings.orgForm.legalFormLabel}
            value={selfForm}
            onChange={setSelfForm}
            options={[
              { value: 'self_employed', label: strings.orgForm.legalFormSelfEmployed },
              { value: 'ip', label: strings.orgForm.legalFormIp },
            ]}
          />
        </div>
      )}
      <form id={FORM_ID} onSubmit={handleSubmit} noValidate>
        <TextField
          id="org-inn"
          label={company ? strings.orgForm.companyInn : strings.orgForm.selfInn}
          className="ui-field__control--mono"
          value={inn}
          inputMode="numeric"
          maxLength={12}
          placeholder={company ? strings.orgForm.innPlaceholder : strings.orgForm.innDigits(12)}
          error={innError}
          onChange={(value) => {
            setInn(digitsOnly(value));
            clearInnServerError();
          }}
          onBlur={() => setInnTouched(true)}
        />
        <TextField
          id="org-name"
          label={company ? strings.orgForm.companyName : strings.orgForm.selfName}
          placeholder={company ? strings.orgForm.namePlaceholder : undefined}
          value={name}
          onChange={setName}
          autoComplete={company ? 'organization' : 'name'}
          required
          error={nameError}
        />
        <PhoneField
          id="org-phone"
          label={strings.orgForm.providerPhone}
          hint={strings.orgForm.providerPhoneHint}
          required
          error={phoneError}
          value={contactPhone}
          onChange={setContactPhone}
        />
        {formError && <Banner tone="x" role="alert" title={formError} />}
      </form>
      <Note>{strings.orgForm.providerNextNote}</Note>
    </StandaloneScreen>
  );
}
