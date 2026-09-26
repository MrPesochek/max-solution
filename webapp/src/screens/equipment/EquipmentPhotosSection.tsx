import { useRef, useState, type ChangeEvent } from 'react';
import { strings } from '../../strings/ru';
import { useEquipmentPhotos, useUploadEquipmentPhoto } from '../../api/hooks/useEquipment';
import type { Attachment, PhotoTemplateSlot } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Note } from '../../ui/blocks/Blocks';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../ui/PhotoGrid';

function tileState(photo: Attachment): PhotoState {
  if (photo.processing_state === 'ready') return 'ok';
  return photo.processing_state === 'rejected' ? 'e' : 'q';
}

export function EquipmentPhotosSection({
  equipmentId,
  title,
  canUpload,
  slots = [],
}: {
  equipmentId: string;
  title: string;
  canUpload: boolean;
  slots?: PhotoTemplateSlot[];
}) {
  const photos = useEquipmentPhotos(equipmentId);
  const upload = useUploadEquipmentPhoto();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pendingSlot = useRef<string | undefined>(undefined);
  const slotLabels = Object.fromEntries(slots.map((slot) => [slot.code, slot.label]));

  const pick = (slot?: string) => {
    pendingSlot.current = slot;
    inputRef.current?.click();
  };

  const handleChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError(null);
    try {
      await upload.mutateAsync({ equipmentId, file, slot: pendingSlot.current });
    } catch (e) {
      setError(actionErrorMessage(e, strings.equipment.photosUploadError));
    }
  };

  if (photos.isPending) return <Skeleton lines={1} />;
  if (photos.isError) return <ErrorState error={photos.error} onRetry={() => void photos.refetch()} />;

  const items = photos.data;
  if (items.length === 0 && !canUpload) return null;
  const missingSlots = canUpload
    ? slots.filter((slot) => slot.required && !items.some((photo) => photo.slot === slot.code))
    : [];

  return (
    <section aria-label={strings.equipment.photosCaption}>
      {canUpload && (
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          aria-label={strings.equipment.photoFile}
          onChange={(event) => void handleChange(event)}
        />
      )}
      <PhotoGrid>
        {items.map((photo, index) => {
          const state = tileState(photo);
          const slot = photo.slot ? slotLabels[photo.slot] : undefined;
          const alt = slot ? `${title}: ${slot}` : strings.equipment.photoAlt(title, index + 1);
          return (
            <PhotoTile
              key={photo.id}
              label={slot}
              state={state}
              attachmentId={photo.id}
              alt={alt}
            />
          );
        })}
        {missingSlots.map((slot) => (
          <PhotoTile
            key={slot.code}
            state="add"
            label={slot.label}
            actionLabel={strings.equipment.photoAddSlot(slot.label)}
            disabled={upload.isPending}
            onClick={() => pick(slot.code)}
          />
        ))}
        {canUpload && missingSlots.length === 0 && (
          <PhotoTile
            state="add"
            label={upload.isPending ? strings.equipment.photosUploading : strings.equipment.photoTileAdd}
            actionLabel={strings.equipment.photoAdd}
            disabled={upload.isPending}
            onClick={() => pick()}
          />
        )}
      </PhotoGrid>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </section>
  );
}
