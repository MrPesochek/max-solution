import { useRef, type ChangeEvent } from 'react';
import { strings } from '../../strings/ru';
import { useUploadAttachment } from '../../api/hooks/useAttachments';
import type { Attachment } from '../../api/types';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../ui/PhotoGrid';
import { Note, SectionCaption } from '../../ui/blocks/Blocks';
import { ActionFeedback } from '../actions/ActionFeedback';
import { useActionRunner } from '../actions/useActionRunner';

interface RequestAttachmentsProps {
  requestId: string;
  requestNumber: string | number;
  attachments: Attachment[];
  canUpload: boolean;
  onStale?: () => unknown;
  slotLabels?: Record<string, string>;
  hideCaption?: boolean;
}

const STATE: Record<Attachment['processing_state'], PhotoState> = {
  ready: 'ok',
  quarantined: 'q',
  rejected: 'e',
};

export function RequestAttachments({
  requestId,
  requestNumber,
  attachments,
  canUpload,
  onStale,
  slotLabels = {},
  hideCaption = false,
}: RequestAttachmentsProps) {
  const upload = useUploadAttachment(requestId);
  const runner = useActionRunner({ onStale, fallbackMessage: strings.attachments.uploadError });
  const input = useRef<HTMLInputElement | null>(null);
  const own = attachments.filter((a) => !a.message_id);

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) void runner.run('upload', () => upload.mutateAsync({ file }));
  };

  return (
    <section aria-label={strings.requests.card.attachmentsTitle}>
      {!hideCaption && <SectionCaption>{strings.requests.card.attachmentsTitle}</SectionCaption>}
      {own.length === 0 && !canUpload ? (
        <Note>{strings.requests.card.attachmentsEmpty}</Note>
      ) : (
        <PhotoGrid label={strings.requests.card.attachmentsTitle}>
          {own.map((a, index) => {
            const slot = a.slot ? slotLabels[a.slot] : undefined;
            return (
              <PhotoTile
                key={a.id}
                state={STATE[a.processing_state]}
                attachmentId={a.processing_state === 'ready' ? a.id : null}
                label={slot}
                alt={strings.attachments.requestPhotoAlt(requestNumber, index + 1)}
              />
            );
          })}
          {canUpload && (
            <PhotoTile
              state={runner.busy ? 'q' : 'add'}
              label={runner.busy ? strings.attachments.uploading : strings.attachments.addPhoto}
              actionLabel={strings.attachments.addPhoto}
              disabled={runner.busy}
              onClick={() => input.current?.click()}
            />
          )}
        </PhotoGrid>
      )}
      {canUpload && (
        <input
          ref={input}
          type="file"
          accept="image/*"
          hidden
          aria-label={strings.attachments.addPhoto}
          onChange={handleFile}
        />
      )}
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
    </section>
  );
}
