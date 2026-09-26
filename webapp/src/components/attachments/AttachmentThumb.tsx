import { Spinner } from '@maxhub/max-ui';
import { useAttachmentBlobUrl } from '../../api/hooks/useAttachments';
import type { Attachment } from '../../api/types';
import { strings } from '../../strings/ru';

interface AttachmentThumbProps {
  attachment: Attachment;
  alt?: string;
  onClick?: () => void;
  selected?: boolean;
}

export function AttachmentThumb({ attachment, alt, onClick, selected }: AttachmentThumbProps) {
  const ready = attachment.processing_state === 'ready';
  const { url, isLoading, isError } = useAttachmentBlobUrl(ready ? attachment.id : null, 'thumb');
  const label = alt ?? strings.attachments.defaultAlt;

  if (!ready) {
    const stateLabel =
      attachment.processing_state === 'rejected'
        ? strings.requests.card.attachmentStateRejected
        : strings.requests.card.attachmentStateQuarantined;
    return (
      <div className="attachment-thumb" role="img" aria-label={`${label}: ${stateLabel}`}>
        <span className="pill pill-negative attachment-thumb__state">{stateLabel}</span>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="attachment-thumb" role="status" aria-label={strings.common.loading}>
        <Spinner size={20} />
      </div>
    );
  }

  if (isError || !url) {
    return (
      <div
        className="attachment-thumb"
        role="img"
        aria-label={`${label}: ${strings.requests.card.attachmentLoadError}`}
      >
        <span className="pill pill-negative attachment-thumb__state" aria-hidden="true">
          !
        </span>
      </div>
    );
  }

  const image = <img src={url} alt={label} />;
  if (!onClick) return <div className="attachment-thumb">{image}</div>;
  return (
    <button
      type="button"
      className="attachment-thumb is-interactive"
      aria-pressed={selected}
      onClick={onClick}
    >
      {image}
    </button>
  );
}
