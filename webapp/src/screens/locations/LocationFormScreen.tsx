import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useCities } from '../../api/hooks/useDirectories';
import { useCreateLocation, useLocation, useUpdateLocation } from '../../api/hooks/useLocations';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { useSession } from '../../session/SessionContext';
import { canManageLocationsAndEquipment } from '../../lib/roles';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { PhoneField, SelectField, TextField } from '../../ui/FormField';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';

const FORM_ID = 'location-form';

export function LocationFormScreen() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const cities = useCities();
  const existing = useLocation(id);
  const createLocation = useCreateLocation();
  const updateLocation = useUpdateLocation(id ?? '');

  const [name, setName] = useState('');
  const [cityId, setCityId] = useState('');
  const [districtId, setDistrictId] = useState('');
  const [address, setAddress] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (existing.data && !loaded) {
      setLoaded(true);
      setName(existing.data.name);
      setCityId(existing.data.city_id);
      setDistrictId(existing.data.district_id ?? '');
      setAddress(existing.data.address);
      setContactPhone(existing.data.contact_phone ?? '');
    }
  }, [existing.data, loaded]);

  const title = isEdit
    ? (existing.data?.name ?? strings.locations.editLocation)
    : strings.locations.newLocation;
  const frame = (body: ReactNode) => <Screen title={title}>{body}</Screen>;

  if (!activeMembership) return null;
  if (!canManageLocationsAndEquipment(activeMembership.role)) return frame(<NoAccessState />);

  if (isEdit && existing.isPending) return frame(<Skeleton lines={5} />);
  if (isEdit && existing.isError) {
    return frame(<ErrorState error={existing.error} onRetry={() => void existing.refetch()} />);
  }
  if (cities.isPending) return frame(<Skeleton lines={5} />);
  if (cities.isError)
    return frame(<ErrorState error={cities.error} onRetry={() => void cities.refetch()} />);

  const onlyCity = cities.data.length === 1 ? cities.data[0]! : null;
  const effectiveCityId = cityId || onlyCity?.id || '';
  const selectedCity = cities.data.find((city) => city.id === effectiveCityId);
  const needsDistrict = (selectedCity?.districts.length ?? 0) > 0;
  const canSubmit = Boolean(
    name.trim() && effectiveCityId && address.trim(),
  );

  const o = strings.orgForm;
  const nameError = submitted && !name.trim() ? o.requiredLocationName : undefined;
  const cityError = submitted && !effectiveCityId ? o.requiredCity : undefined;
  const addressError = submitted && !address.trim() ? o.requiredAddress : undefined;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (!canSubmit) {
      setSubmitted(true);
      const first = !name.trim()
        ? 'loc-name'
        : !effectiveCityId
          ? 'loc-city'
          : 'loc-address';
      document.getElementById(first)?.focus();
      return;
    }

    const input = {
      name: name.trim(),
      city_id: effectiveCityId,
      district_id: districtId || null,
      address: address.trim(),
      contact_phone: contactPhone.trim() || null,
    };

    try {
      if (isEdit) {
        await updateLocation.mutateAsync(input);
      } else {
        await createLocation.mutateAsync(input);
      }
      navigate('/locations');
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  const isSubmitting = createLocation.isPending || updateLocation.isPending;

  return (
    <Screen
      title={title}
      actions={
        <BottomActions>
          <ActionButton type="submit" form={FORM_ID} loading={isSubmitting}>
            {strings.common.save}
          </ActionButton>
        </BottomActions>
      }
    >
      <form id={FORM_ID} onSubmit={handleSubmit} noValidate>
        <TextField
          id="loc-name"
          label={strings.locations.name}
          value={name}
          onChange={setName}
          required
          error={nameError}
        />
        {!onlyCity && (
          <SelectField
            id="loc-city"
            label={strings.locations.city}
            value={cityId}
            required
            error={cityError}
            placeholder={strings.common.notSpecified}
            onChange={(value) => {
              setCityId(value);
              setDistrictId('');
            }}
            options={cities.data.map((city) => ({ value: city.id, label: city.name }))}
          />
        )}
        {needsDistrict && (
          <SelectField
            id="loc-district"
            label={strings.locations.district}
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
          label={strings.locations.address}
          placeholder={strings.orgForm.addressPlaceholder}
          value={address}
          onChange={setAddress}
          autoComplete="street-address"
          required
          error={addressError}
        />
        <PhoneField
          id="loc-contact-phone"
          label={strings.locations.contactPhone}
          value={contactPhone}
          onChange={setContactPhone}
        />
        {formError && <Banner tone="x" role="alert" title={formError} />}
        <Note>{strings.locations.privacyNote}</Note>
      </form>
    </Screen>
  );
}
