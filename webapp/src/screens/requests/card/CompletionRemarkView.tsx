import { useRef, useState, type ChangeEvent } from 'react';
import { strings } from '../../../strings/ru';
import { usePostMessage, useRefreshRequest, useRejectCompletion } from '../../../api/hooks/useRequests';
import { useUploadAttachment } from '../../../api/hooks/useAttachments';
import type { RequestCustomer } from '../../../api/types';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { useActionRunner } from '../../../components/actions/useActionRunner';
import { Screen, BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note } from '../../../ui/blocks/Blocks';
import { ChipGroup } from '../../../ui/Chips';
import { TextAreaField } from '../../../ui/FormField';
import { List, ListRow } from '../../../ui/List';
import { MAX_PHOTO_BYTES, MAX_PHOTOS } from '../wizard/helpers';
import { CardHero } from '../../../ui/CardHero';
import { workerName } from './cardFormat';

export function CompletionRemarkView({
  request,
  onClose,
  onSent,
}: {
  request: RequestCustomer;
  onClose: () => void;
  onSent: () => void;
}) {
  const c = strings.requests.card;
  const [issues, setIssues] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [messageId, setMessageId] = useState<string | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const refresh = useRefreshRequest(request.id);
  const runner = useActionRunner({ onStale: refresh });
  const upload = useUploadAttachment(request.id);
  const post = usePostMessage(request.id);
  const reject = useRejectCompletion(request.id);
  const text = [...issues, reason.trim()].filter(Boolean).join('. ');

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      setFileError(c.remarkPhotoTooLarge(file.name));
      return;
    }
    setFileError(null);
    setFiles((current) => [...current, file]);
  };

  const handleSubmit = async () => {
    const done = await runner.run('reject', async () => {
      if (files.length > 0) {
        let id = messageId;
        if (!id) {
          id = (await post.mutateAsync({ body: text })).id;
          setMessageId(id);
        }
        const pending = [...files];
        for (const file of pending) {
          await upload.mutateAsync({ file, messageId: id });
          setFiles((current) => current.filter((f) => f !== file));
        }
      }
      await reject.mutateAsync({ reason: text, expected_version: request.version });
      return true;
    });
    if (done) onSent();
  };

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      back={onClose}
      actions={
        <BottomActions layout="row">
          <ActionButton kind="s" disabled={runner.busy} onClick={onClose}>
            {strings.ui.back}
          </ActionButton>
          <ActionButton
            loading={runner.isRunning('reject')}
            disabled={!text || runner.busy}
            onClick={() => void handleSubmit()}
          >
            {c.remarkSend}
          </ActionButton>
        </BottomActions>
      }
    >
      <CardHero scene="status-dispute" size="m" title={c.remarkHeading} text={c.remarkSubtitle(workerName(request))} />
      <div className="request-chip-block">
        <ChipGroup
          multiple
          label={c.remarkIssuesLabel}
          options={c.remarkIssues.map((issue) => ({ value: issue, label: issue }))}
          value={issues}
          onChange={setIssues}
        />
      </div>
      <TextAreaField
        label={c.remarkLabel}
        value={reason}
        placeholder={c.actionRejectCompletionReasonLabel}
        onChange={setReason}
        rows={3}
      />
      <List aria-label={c.remarkPhotos}>
        {files.map((file) => (
          <ListRow
            key={`${file.name}-${file.lastModified}`}
            title={file.name}
            action="danger"
            aria-label={`${c.attachmentDelete}: ${file.name}`}
            value={c.attachmentDelete}
            disabled={runner.busy}
            onClick={() => setFiles((current) => current.filter((f) => f !== file))}
          />
        ))}
        <ListRow
          title={strings.ui.photoAdd}
          action="accent"
          disabled={runner.busy || files.length >= MAX_PHOTOS}
          onClick={() => input.current?.click()}
        />
      </List>
      {fileError && (
        <Note tone="error" role="alert">
          {fileError}
        </Note>
      )}
      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/*"
        hidden
        aria-label={strings.ui.photoAdd}
        onChange={(event) => void handleFile(event)}
      />
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
      <Note>{c.remarkNote}</Note>
    </Screen>
  );
}

export function CompletionRemarkSent({ request, onDone }: { request: RequestCustomer; onDone: () => void }) {
  const c = strings.requests.card;
  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton onClick={onDone}>{c.done}</ActionButton>
        </BottomActions>
      }
    >
      <CardHero scene="status-waiting" size="m" title={c.remarkSentTitle} text={c.remarkSentText(workerName(request))} />
    </Screen>
  );
}
