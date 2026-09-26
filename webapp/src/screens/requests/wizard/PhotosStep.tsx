import { useRef, useState, type ChangeEvent } from 'react';
import { strings } from '../../../strings/ru';
import { useDeleteAttachment, useUploadAttachment } from '../../../api/hooks/useAttachments';
import type { Attachment, PhotoTemplateSlot } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { describeActionError } from '../../../components/actions/actionErrors';
import { Note } from '../../../ui/blocks/Blocks';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../../ui/PhotoGrid';
import { List, ListRow } from '../../../ui/List';
import { Sheet } from '../../../ui/Sheet';
import { MAX_PHOTO_BYTES, MAX_PHOTOS, SCREEN_SLOT } from './helpers';

const t = strings.requests.wizard;

type SlotError = { kind: 'size'; megabytes: number } | { kind: 'upload'; message: string | null };

interface PhotosStepProps {
  requestId: string;
  template: PhotoTemplateSlot[];
  templateLoading: boolean;
  attachments: Attachment[];
  attachmentsBySlot: Map<string, Attachment[]>;
  noScreen: boolean;
  onNoScreenChange: (value: boolean) => void;
  onCannotPhoto: () => void;
  onError: (message: string | null) => void;
  onBusyChange: (busy: boolean) => void;
}

export function PhotosStep({
  requestId,
  template,
  templateLoading,
  attachments,
  attachmentsBySlot,
  noScreen,
  onNoScreenChange,
  onCannotPhoto,
  onError,
  onBusyChange,
}: PhotosStepProps) {
  const uploadAttachment = useUploadAttachment(requestId);
  const deleteAttachment = useDeleteAttachment(requestId);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pending = useRef<{ slot: string; replaces: string | null } | null>(null);
  const [uploadingSlot, setUploadingSlot] = useState<string | null>(null);
  const [slotErrors, setSlotErrors] = useState<Record<string, SlotError>>({});
  const [openPhoto, setOpenPhoto] = useState<{ slot: PhotoTemplateSlot; attachment: Attachment } | null>(null);

  const limitReached = attachments.length >= MAX_PHOTOS;
  const hasScreenSlot = template.some((slot) => slot.code === SCREEN_SLOT);

  const pickFile = (slot: string, replaces: string | null = null) => {
    pending.current = { slot, replaces };
    fileInputRef.current?.click();
  };

  const setSlotError = (slot: string, error: SlotError | null) =>
    setSlotErrors((prev) => {
      const next = { ...prev };
      if (error) next[slot] = error;
      else delete next[slot];
      return next;
    });

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    const target = pending.current;
    pending.current = null;
    if (!file || !target) return;
    onError(null);
    if (file.size > MAX_PHOTO_BYTES) {
      setSlotError(target.slot, { kind: 'size', megabytes: Math.ceil(file.size / (1024 * 1024)) });
      return;
    }
    setSlotError(target.slot, null);
    setUploadingSlot(target.slot);
    onBusyChange(true);
    try {
      await uploadAttachment.mutateAsync({ file, slot: target.slot });
      if (target.replaces) await deleteAttachment.mutateAsync(target.replaces);
    } catch (error) {
      const described = describeActionError(error);
      setSlotError(target.slot, {
        kind: 'upload',
        message: described.kind === 'offline' ? described.message : null,
      });
    } finally {
      setUploadingSlot(null);
      onBusyChange(false);
    }
  };

  const handleRemove = async (attachmentId: string) => {
    try {
      await deleteAttachment.mutateAsync(attachmentId);
    } catch (error) {
      const described = describeActionError(error);
      onError(described.kind === 'stale' ? strings.actions.staleDescription : described.message);
    }
  };

  const errorNotes = template
    .map((slot) => {
      const error = slotErrors[slot.code];
      if (!error) return null;
      const text =
        error.kind === 'size'
          ? t.photoTooLarge(slot.label)
          : (error.message ?? t.photoUploadFailed(slot.label));
      return { code: slot.code, text };
    })
    .filter((note): note is { code: string; text: string } => note !== null);

  const rejected = attachments.filter((a) => a.processing_state === 'rejected' && a.slot);

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/*"
        hidden
        data-testid="wizard-photo-input"
        onChange={(e) => void handleFileChange(e)}
      />
      <div className="wizard-label-block">
        <h3 className="wizard-label">{t.photosTitle}</h3>
        <p className="wizard-hint">{t.photosHint}</p>
      </div>
      {templateLoading && <Skeleton lines={3} />}
      {template.length > 0 && (
        <PhotoGrid label={t.photosTitle} columns={4}>
          {template.flatMap((slot) => {
            const slotAttachments = attachmentsBySlot.get(slot.code) ?? [];
            const error = slotErrors[slot.code];
            const uploading = uploadingSlot === slot.code;
            const label = slot.label;

            if (slot.code === SCREEN_SLOT && noScreen && slotAttachments.length === 0) {
              return [<PhotoTile key={slot.code} label={label} state="off" alt={t.noScreen} />];
            }

            const tiles = slotAttachments.map((attachment, index) => {
              const state: PhotoState =
                attachment.processing_state === 'ready'
                  ? 'ok'
                  : attachment.processing_state === 'rejected'
                    ? 'e'
                    : 'q';
              const alt = t.photoAlt(slot.label, index + 1);
              return (
                <PhotoTile
                  key={attachment.id}
                  label={label}
                  state={state}
                  attachmentId={attachment.id}
                  alt={alt}
                  actionLabel={t.photoOpen(alt)}
                  onClick={() => setOpenPhoto({ slot, attachment })}
                />
              );
            });

            if (uploading) {
              tiles.push(<PhotoTile key={`${slot.code}-q`} label={label} state="q" alt={t.photoUploading} />);
            } else if (error) {
              tiles.push(
                <PhotoTile
                  key={`${slot.code}-e`}
                  label={error.kind === 'size' ? t.photoSizeLabel(slot.label, error.megabytes) : label}
                  state="e"
                  actionLabel={t.photoRetry(slot.label)}
                  disabled={uploadAttachment.isPending}
                  onClick={() => pickFile(slot.code)}
                />,
              );
            } else if (slotAttachments.length === 0) {
              tiles.push(
                <PhotoTile
                  key={`${slot.code}-add`}
                  label={label}
                  state="add"
                  actionLabel={t.photoAdd(slot.label)}
                  disabled={uploadAttachment.isPending || limitReached}
                  onClick={() => pickFile(slot.code)}
                />,
              );
            }
            return tiles;
          })}
        </PhotoGrid>
      )}
      {errorNotes.map((note) => (
        <Note key={note.code} tone="error" role="alert">
          {note.text}
        </Note>
      ))}
      {rejected.length > 0 && (
        <Note tone="error">
          {t.photoRejected(
            rejected
              .map((a) => template.find((slot) => slot.code === a.slot)?.label ?? a.slot)
              .join(', '),
          )}
        </Note>
      )}
      {limitReached && <Note>{t.photoLimit}</Note>}
      <List>
        {hasScreenSlot && (
          <ListRow
            title={t.noScreen}
            control={{ type: 'switch', checked: noScreen }}
            onToggle={onNoScreenChange}
          />
        )}
        <ListRow title={t.cannotPhoto} chevron onClick={onCannotPhoto} />
      </List>

      <Sheet
        open={openPhoto !== null}
        onClose={() => setOpenPhoto(null)}
        title={openPhoto?.slot.label}
      >
        <List>
          <ListRow
            title={t.photoReplace}
            action="accent"
            disabled={uploadAttachment.isPending}
            onClick={() => {
              const current = openPhoto;
              setOpenPhoto(null);
              if (current) pickFile(current.slot.code, current.attachment.id);
            }}
          />
          <ListRow
            title={t.photoRemove}
            action="danger"
            disabled={deleteAttachment.isPending}
            onClick={() => {
              const current = openPhoto;
              setOpenPhoto(null);
              if (current) void handleRemove(current.attachment.id);
            }}
          />
        </List>
      </Sheet>
    </>
  );
}
