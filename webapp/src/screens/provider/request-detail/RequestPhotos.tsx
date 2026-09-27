import { useRef } from 'react';
import { strings } from '../../../strings/ru';
import { useUploadAttachment } from '../../../api/hooks/useAttachments';
import type { Attachment, RequestProvider } from '../../../api/types';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { useActionRunner } from '../../../components/actions/useActionRunner';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../../ui/PhotoGrid';

function tileState(attachment: Attachment): PhotoState {
  if (attachment.processing_state === 'rejected') return 'e';
  if (attachment.processing_state === 'quarantined') return 'q';
  return 'ok';
}

export function RequestPhotos({
  request,
  canUpload,
  onStale,
}: {
  request: RequestProvider;
  canUpload: boolean;
  onStale?: () => unknown;
}) {
  const upload = useUploadAttachment(request.id);
  const runner = useActionRunner({ onStale, fallbackMessage: strings.attachments.uploadError });
  const inputRef = useRef<HTMLInputElement>(null);
  const own = request.attachments.filter((a) => !a.message_id);
  if (own.length === 0 && !canUpload) return null;

  return (
    <>
      <PhotoGrid label={strings.requests.card.attachmentsTitle}>
        {own.map((attachment, index) => {
          const state = tileState(attachment);
          const alt = strings.attachments.requestPhotoAlt(request.request_number, index + 1);
          const replace = canUpload && state === 'e';
          return (
            <PhotoTile
              key={attachment.id}
              state={state}
              attachmentId={attachment.id}
              alt={alt}
              onClick={replace ? () => inputRef.current?.click() : undefined}
              actionLabel={replace ? strings.attachments.replaceRejected(alt) : undefined}
              disabled={replace ? runner.busy : undefined}
            />
          );
        })}
        {canUpload && (
          <PhotoTile
            state="add"
            label={runner.busy ? strings.attachments.uploading : strings.workspace.photoAddLabel}
            actionLabel={strings.attachments.addPhoto}
            disabled={runner.busy}
            onClick={() => inputRef.current?.click()}
          />
        )}
      </PhotoGrid>
      {canUpload && (
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          aria-label={strings.attachments.addPhoto}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void runner.run('upload', () => upload.mutateAsync({ file }));
          }}
        />
      )}
      <ActionFeedback feedback={runner.feedback} />
    </>
  );
}
