import { useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useEquipmentCategories } from '../../api/hooks/useDirectories';
import { useCreateEquipment, useUploadEquipmentPhoto } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import { ApiError } from '../../api/errors';
import type { EquipmentCategory } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { useSession } from '../../session/SessionContext';
import { canManageLocationsAndEquipment } from '../../lib/roles';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note } from '../../ui/blocks/Blocks';
import { TextField } from '../../ui/FormField';
import { ChipGroup } from '../../ui/Chips';
import { EquipmentIcon } from '../../ui/EquipmentIcon';
import { PlusIcon } from '../../ui/icons';
import { useFilePicker } from '../../ui/useFilePicker';
import './equipment.css';

const FORM_ID = 'equipment-form';
const OTHER_CODE = 'other';
const NAMEPLATE_SLOT = 'nameplate';
const NAMEPLATE_LABEL = strings.equipment.photoSlots[1];

function typeLabel(category: EquipmentCategory): string {
  return strings.equipment.typeShort[category.code] ?? category.name;
}

function CameraIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="6" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="2" />
      <circle cx="12" cy="13" r="3.5" stroke="currentColor" strokeWidth="2" />
      <path d="M9 6l1.5-2h3L15 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function safeReturnTo(value: string | null): string | null {
  return value && value.startsWith('/') && !value.startsWith('//') ? value : null;
}

function useFilePreview(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== 'function') {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}

function TypePicker({
  categories,
  other,
  value,
  onChange,
}: {
  categories: EquipmentCategory[];
  other: EquipmentCategory | undefined;
  value: string;
  onChange: (id: string) => void;
}) {
  const all = other ? [...categories, other] : categories;
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) return;
    const index = all.findIndex((c) => c.id === value);
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1;
    const next = all[(index + step + all.length) % all.length];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    document.getElementById(`eq-type-${next.id}`)?.focus();
  };
  const focusable = value || all[0]?.id;
  return (
    <div
      role="radiogroup"
      aria-label={strings.equipment.category}
      className="eq-typepick"
      onKeyDown={handleKeyDown}
    >
      <div className="eq-types">
        {categories.map((category) => (
          <button
            key={category.id}
            id={`eq-type-${category.id}`}
            type="button"
            role="radio"
            aria-checked={value === category.id}
            aria-label={category.name}
            tabIndex={category.id === focusable ? 0 : -1}
            className="eq-type"
            onClick={() => onChange(category.id)}
          >
            <EquipmentIcon code={category.code} name={category.name} width={64} />
            <span className="eq-type__label" aria-hidden="true">
              {typeLabel(category)}
            </span>
          </button>
        ))}
      </div>
      {other && (
        <button
          id={`eq-type-${other.id}`}
          type="button"
          role="radio"
          aria-checked={value === other.id}
          tabIndex={other.id === focusable ? 0 : -1}
          className="eq-type eq-type--other"
          onClick={() => onChange(other.id)}
        >
          <PlusIcon size={18} />
          <span className="eq-type__label">{strings.equipment.otherType}</span>
        </button>
      )}
    </div>
  );
}

function NameplatePicker({ file, onChange }: { file: File | null; onChange: (file: File | null) => void }) {
  const [tooLarge, setTooLarge] = useState<string | null>(null);
  const picker = useFilePicker({
    onFile: (next) => {
      setTooLarge(null);
      onChange(next);
    },
    onTooLarge: (big) => setTooLarge(strings.equipment.photoTooLarge(big.name)),
  });
  const preview = useFilePreview(file);
  return (
    <>
      <input
        {...picker.inputProps}
        capture="environment"
        aria-label={strings.equipment.photoFileSlot(NAMEPLATE_LABEL)}
      />
      {tooLarge && (
        <Note tone="error" role="alert">
          {tooLarge}
        </Note>
      )}
      {file ? (
        <div className="eq-plate eq-plate--done">
          {preview ? (
            <img className="eq-plate__thumb" src={preview} alt={NAMEPLATE_LABEL} />
          ) : (
            <span className="eq-plate__thumb" aria-hidden="true" />
          )}
          <span className="eq-plate__main">
            <span className="eq-plate__title">{strings.equipment.nameplateAdded}</span>
            <span className="eq-plate__hint">{strings.equipment.nameplateAddedHint}</span>
          </span>
          <button
            type="button"
            className="eq-plate__remove"
            aria-label={strings.equipment.photoRemoveSlot(NAMEPLATE_LABEL)}
            onClick={() => onChange(null)}
          >
            {strings.equipment.nameplateRemove}
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="eq-plate"
          aria-label={strings.equipment.photoAddSlot(NAMEPLATE_LABEL)}
          onClick={picker.open}
        >
          <span className="eq-plate__icon">
            <CameraIcon />
          </span>
          <span className="eq-plate__main">
            <span className="eq-plate__title">{strings.equipment.nameplateTake}</span>
            <span className="eq-plate__hint">{strings.equipment.nameplateTakeHint}</span>
          </span>
        </button>
      )}
    </>
  );
}

export function EquipmentFormScreen() {
  const params = useParams<{ locationId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const categories = useEquipmentCategories();
  const locations = useLocations();
  const createEquipment = useCreateEquipment();
  const uploadPhoto = useUploadEquipmentPhoto();

  const [locationId, setLocationId] = useState(params.locationId ?? searchParams.get('location') ?? '');
  const [categoryId, setCategoryId] = useState('');
  const [otherName, setOtherName] = useState('');
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState(() => searchParams.get('model') ?? '');
  const returnTo = safeReturnTo(searchParams.get('returnTo'));
  const [serialNumber, setSerialNumber] = useState('');
  const [nameplate, setNameplate] = useState<File | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const { regular, other } = useMemo(() => {
    const list = categories.data ?? [];
    return {
      regular: list.filter((c) => c.code !== OTHER_CODE),
      other: list.find((c) => c.code === OTHER_CODE),
    };
  }, [categories.data]);

  const title = strings.equipment.newEquipment;
  if (!activeMembership) return null;
  if (!canManageLocationsAndEquipment(activeMembership.role)) {
    return (
      <Screen title={title}>
        <NoAccessState />
      </Screen>
    );
  }
  if (categories.isPending || locations.isPending) {
    return (
      <Screen title={title}>
        <Skeleton lines={5} />
      </Screen>
    );
  }
  if (categories.isError || locations.isError) {
    return (
      <Screen title={title}>
        <ErrorState
          error={categories.error ?? locations.error}
          onRetry={() => {
            void categories.refetch();
            void locations.refetch();
          }}
        />
      </Screen>
    );
  }

  const onlyLocation = locations.data?.length === 1 ? locations.data[0]!.id : '';
  const selectedLocation = locationId || onlyLocation;
  const isOther = Boolean(other && categoryId === other.id);
  const busy = createEquipment.isPending || uploadPhoto.isPending;
  const close = () =>
    navigate(
      returnTo ?? (selectedLocation ? `/equipment?location=${encodeURIComponent(selectedLocation)}` : '/equipment'),
    );
  const canSubmit = Boolean(
    selectedLocation && categoryId && brand.trim() && model.trim() && (!isOther || otherName.trim()),
  );

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (!canSubmit || busy) return;
    let created;
    try {
      created = await createEquipment.mutateAsync({
        location_id: selectedLocation,
        equipment_category_id: categoryId,
        brand: brand.trim(),
        model: model.trim(),
        serial_number: serialNumber.trim() || null,
        notes: isOther ? strings.equipment.otherTypeNote(otherName.trim()) : null,
      });
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : strings.common.unknownError);
      return;
    }
    if (nameplate) {
      try {
        await uploadPhoto.mutateAsync({ equipmentId: created.id, file: nameplate, slot: NAMEPLATE_SLOT });
      } catch {
        navigate(`/equipment/${created.location_id}/${created.id}`, {
          replace: true,
          state: { photoUploadFailed: true },
        });
        return;
      }
    }
    navigate(returnTo ?? `/equipment?location=${encodeURIComponent(created.location_id)}`, { replace: Boolean(returnTo) });
  };

  return (
    <Screen
      title={title}
      back={false}
      onClose={close}
      actions={
        <BottomActions note={strings.equipment.addHint}>
          <ActionButton type="submit" form={FORM_ID} disabled={!canSubmit} loading={busy}>
            {strings.equipment.addSubmit}
          </ActionButton>
        </BottomActions>
      }
    >
      <form id={FORM_ID} onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="eq-field">
          <span className="eq-field__label" aria-hidden="true">
            {strings.equipment.typeLabel}
          </span>
          <TypePicker categories={regular} other={other} value={categoryId} onChange={setCategoryId} />
          {isOther && (
            <TextField
              id="eq-other-type"
              aria-label={strings.equipment.otherTypeLabel}
              placeholder={strings.equipment.otherTypePlaceholder}
              value={otherName}
              onChange={setOtherName}
              autoComplete="off"
            />
          )}
        </div>

        <div className="eq-field">
          <span className="eq-field__label">{strings.equipment.nameplateLabel}</span>
          <NameplatePicker file={nameplate} onChange={setNameplate} />
        </div>

        <div className="eq-pair">
          <TextField
            id="eq-brand"
            label={strings.equipment.brand}
            placeholder={strings.equipment.brandPlaceholder}
            value={brand}
            onChange={setBrand}
            autoComplete="off"
          />
          <TextField
            id="eq-model"
            label={strings.equipment.model}
            placeholder={strings.equipment.modelPlaceholder}
            value={model}
            onChange={setModel}
            autoComplete="off"
          />
        </div>
        <TextField
          id="eq-serial"
          label={strings.equipment.serialNumber}
          placeholder={strings.equipment.serialPlaceholder}
          value={serialNumber}
          onChange={setSerialNumber}
          autoComplete="off"
        />

        <div className="eq-field">
          <span className="eq-field__label" aria-hidden="true">
            {strings.equipment.location}
          </span>
          <ChipGroup
            label={strings.equipment.location}
            value={selectedLocation || null}
            onChange={setLocationId}
            options={(locations.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
          />
        </div>

        <Note>{strings.equipment.photoPrivacyNote}</Note>
        {formError && (
          <Note tone="error" role="alert">
            {formError}
          </Note>
        )}
      </form>
    </Screen>
  );
}
