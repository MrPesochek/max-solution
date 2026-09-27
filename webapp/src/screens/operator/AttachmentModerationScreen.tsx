import { useState } from 'react';
import { Spinner } from '@maxhub/max-ui';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useApproveOperatorAttachment,
  useOperatorAttachmentBlobUrl,
  useOperatorAttachmentQueue,
  useRejectOperatorAttachment,
} from '../../api/hooks/useOperatorAttachments';
import type { OperatorAttachment } from '../../api/operatorTypes';
import { useConfirm } from '../../components/useConfirm';
import { Banner } from '../../ui/blocks/Blocks';
import { Sheet } from '../../ui/Sheet';
import { TextAreaField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { OperatorScreen } from './OperatorScreen';
import './operator.css';

const STATUS = 'pending';

function RejectSheet({ item, onClose }: { item: OperatorAttachment; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const reject = useRejectOperatorAttachment(item.id, STATUS);

  const handleReject = async () => {
    if (!reason.trim()) return;
    setError(null);
    try {
      await reject.mutateAsync({ reason: reason.trim() });
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  return (
    <Sheet
      open
      title={strings.operator.attachmentsReject}
      description={strings.operator.attachmentMeta(item.visibility_class, item.mime_type)}
      onClose={onClose}
      locked={reject.isPending}
      actions={
        <>
          <ActionButton
            kind="d"
            disabled={!reason.trim()}
            loading={reject.isPending}
            onClick={() => void handleReject()}
          >
            {strings.operator.attachmentsReject}
          </ActionButton>
          <ActionButton kind="s" disabled={reject.isPending} onClick={onClose}>
            {strings.common.cancel}
          </ActionButton>
        </>
      }
    >
      <TextAreaField
        id={`attachment-reject-${item.id}`}
        label={strings.operator.attachmentsRejectReasonLabel}
        value={reason}
        onChange={setReason}
        rows={2}
      />
      {error && <Banner tone="x" role="alert" title={error} />}
    </Sheet>
  );
}

function AttachmentCard({ item }: { item: OperatorAttachment }) {
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { url, isLoading, isError } = useOperatorAttachmentBlobUrl(item.id);
  const approve = useApproveOperatorAttachment(item.id, STATUS);
  const { confirm, dialog } = useConfirm();

  const handleApprove = async () => {
    const ok = await confirm({ title: strings.operator.attachmentsApprove });
    if (!ok) return;
    setError(null);
    try {
      await approve.mutateAsync();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : strings.operator.decisionError);
    }
  };

  return (
    <article className="operator-attachment" aria-label={strings.operator.attachmentsImageAlt}>
      <div className="operator-attachment__preview">
        {isLoading && <Spinner size={24} />}
        {isError && (
          <span className="operator-attachment__meta">{strings.operator.attachmentsLoadError}</span>
        )}
        {url && <img src={url} alt={strings.operator.attachmentsImageAlt} />}
      </div>
      <span className="operator-attachment__meta">
        {strings.operator.attachmentMeta(item.visibility_class, item.mime_type)}
      </span>
      {error && (
        <span className="operator-attachment__error" role="alert">
          {error}
        </span>
      )}
      <div className="operator-sheet-row">
        <ActionButton compact loading={approve.isPending} onClick={() => void handleApprove()}>
          {strings.operator.attachmentsApprove}
        </ActionButton>
        <ActionButton
          kind="d"
          compact
          disabled={approve.isPending}
          onClick={() => setRejecting(true)}
        >
          {strings.operator.attachmentsReject}
        </ActionButton>
      </div>
      {rejecting && <RejectSheet item={item} onClose={() => setRejecting(false)} />}
      {dialog}
    </article>
  );
}

export function AttachmentModerationScreen() {
  const queue = useOperatorAttachmentQueue(STATUS);
  const items = queue.data ?? [];

  return (
    <OperatorScreen
      title={strings.operator.attachmentsQueueTitle}
      query={queue}
      empty={items.length === 0}
      emptyTitle={strings.operator.attachmentsEmpty}
    >
      <Banner tone="y" title={strings.operator.attachmentsWarningTitle}>
        {strings.operator.attachmentsSensitiveWarning}
      </Banner>
      {items.map((item) => (
        <AttachmentCard key={item.id} item={item} />
      ))}
    </OperatorScreen>
  );
}
