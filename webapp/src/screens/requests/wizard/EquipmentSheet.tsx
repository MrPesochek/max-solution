import { strings } from '../../../strings/ru';
import { useLocations } from '../../../api/hooks/useLocations';
import { useEquipmentList } from '../../../api/hooks/useEquipment';
import { Skeleton } from '../../../components/states/Skeleton';
import { Note } from '../../../ui/blocks/Blocks';
import { SelectField } from '../../../ui/FormField';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Sheet } from '../../../ui/Sheet';
import { equipmentTitle } from './helpers';

const t = strings.requests.wizard;

interface EquipmentSheetProps {
  open: boolean;
  onClose: () => void;
  locationId: string;
  equipmentId: string;
  onLocationChange: (locationId: string) => void;
  onEquipmentChange: (equipmentId: string) => void;
}

export function EquipmentSheet({
  open,
  onClose,
  locationId,
  equipmentId,
  onLocationChange,
  onEquipmentChange,
}: EquipmentSheetProps) {
  const locations = useLocations();
  const equipmentOfLocation = useEquipmentList(open && locationId ? locationId : undefined);

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={t.changeEquipmentTitle}
      actions={
        <ActionButton disabled={!equipmentId} onClick={onClose}>
          {t.changeEquipmentDone}
        </ActionButton>
      }
    >
      {locations.isPending ? (
        <Skeleton lines={2} />
      ) : (
        <SelectField
          id="wizard-location"
          label={t.selectLocationLabel}
          value={locationId}
          onChange={onLocationChange}
          options={(locations.data ?? []).map((l) => ({ value: l.id, label: l.name }))}
          placeholder={t.selectLocationLabel}
        />
      )}
      {locationId && equipmentOfLocation.isPending && <Skeleton lines={2} />}
      {locationId && equipmentOfLocation.isSuccess && equipmentOfLocation.data.length === 0 && (
        <Note>{t.noEquipment}</Note>
      )}
      {locationId && equipmentOfLocation.isSuccess && equipmentOfLocation.data.length > 0 && (
        <SelectField
          id="wizard-equipment"
          label={t.selectEquipmentLabel}
          value={equipmentId}
          onChange={onEquipmentChange}
          options={equipmentOfLocation.data.map((e) => ({ value: e.id, label: equipmentTitle(e) }))}
          placeholder={t.selectEquipmentLabel}
        />
      )}
    </Sheet>
  );
}
