import { useRef, useState } from 'react';
import { strings } from '../../../strings/ru';
import { useUploadAttachment } from '../../../api/hooks/useAttachments';
import type { Attachment, RequestProvider } from '../../../api/types';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { useActionRunner } from '../../../components/actions/useActionRunner';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../../ui/PhotoGrid';

type ReportSlot = 'before' | 'after';

function tileState(attachment: Attachment): PhotoState {
  if (attachment.processing_state === 'rejected') return 'e';
  if (attachment.processing_state === 'quarantined') return 'q';
  return 'ok';
}

export function ReportPhotoSlots({
  request,
  onStale,
}: {
  request: RequestProvider;
  onStale?: () => unknown;
}) {
  const upload = useUploadAttachment(request.id);
  const runner = useActionRunner({ onStale, fallbackMessage: strings.attachments.uploadError });
  const inputRef = useRef<HTMLInputElement>(null);
  const [slot, setSlot] = useState<ReportSlot>('before');
  const w = strings.workspace;
  const label: Record<ReportSlot, string> = {
    before: strings.requests.card.reportPhotoBefore,
    after: strings.requests.card.reportPhotoAfter,
  };

  const photos = request.attachments.filter((a) => a.slot === 'before' || a.slot === 'after');
  const before = photos.filter((a) => a.slot === 'before');
  const after = photos.filter((a) => a.slot === 'after');

  const pick = (next: ReportSlot) => {
    setSlot(next);
    inputRef.current?.click();
  };

  const addTile = (target: ReportSlot, caption: string) => (
    <PhotoTile
      key={`add-${target}`}
      state="add"
      label={runner.busy && slot === target ? strings.attachments.uploading : caption}
      actionLabel={w.reportPhotoAdd(label[target])}
      disabled={runner.busy}
      onClick={() => pick(target)}
    />
  );

  return (
    <>
      <PhotoGrid label={w.reportPhotosCaption}>
        {[...before, ...after].map((attachment, index) => {
          const target = attachment.slot as ReportSlot;
          const state = tileState(attachment);
          const alt = strings.requests.card.reportPhotoAlt(
            label[target],
            request.request_number,
            index + 1,
          );
          const rejected = state === 'e';
          return (
            <PhotoTile
              key={attachment.id}
              label={label[target]}
              state={state}
              attachmentId={attachment.id}
              alt={alt}
              onClick={rejected ? () => pick(target) : undefined}
              actionLabel={rejected ? strings.attachments.replaceRejected(alt) : undefined}
              disabled={rejected ? runner.busy : undefined}
            />
          );
        })}
        {before.length === 0 && addTile('before', label.before)}
        {after.length === 0 && addTile('after', label.after)}
        {before.length > 0 && after.length > 0 && addTile('after', w.photoAddLabel)}
      </PhotoGrid>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        aria-label={w.reportPhotoAdd(label[slot])}
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) void runner.run('upload', () => upload.mutateAsync({ file, slot }));
        }}
      />
      <ActionFeedback feedback={runner.feedback} />
    </>
  );
}
