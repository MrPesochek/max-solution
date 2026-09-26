import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useUploadAttachment } from '../../api/hooks/useAttachments';
import type { RequestMessage } from '../../api/types';
import { useFilePicker } from '../../ui/useFilePicker';
import { useActionRunner } from '../actions/useActionRunner';

export interface FailedMessage {
  body: string;
  files: File[];
  at: string;
}

export function useMessageComposer({
  requestId,
  send,
  onSendError,
}: {
  requestId: string;
  send: (body: string) => Promise<RequestMessage>;
  onSendError?: (error: unknown) => void;
}) {
  const [draft, setDraft] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [failed, setFailed] = useState<FailedMessage | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const picker = useFilePicker({
    onFile: (file) => {
      setPickError(null);
      setFiles((current) => [...current, file]);
    },
    onTooLarge: (file) => setPickError(strings.requests.messages.photoTooLarge(file.name)),
  });
  const upload = useUploadAttachment(requestId);
  const runner = useActionRunner({ fallbackMessage: strings.requests.card.messageSendError });
  const [sentMessageId, setSentMessageId] = useState<string | null>(null);

  const deliver = (body: string, pending: File[]) =>
    runner.run('send', async () => {
      let messageId = sentMessageId;
      if (!messageId) {
        const message = await send(body).catch(
          (error: unknown) => {
            onSendError?.(error);
            throw error;
          },
        );
        messageId = message.id;
        setSentMessageId(messageId);
      }
      for (const file of pending) {
        await upload.mutateAsync({ file, messageId });
      }
      setSentMessageId(null);
      return true;
    });

  const handleSend = async (text?: string) => {
    const body = (text ?? draft).trim();
    if (!body) return;
    const pending = text === undefined ? [...files] : [];
    if (text === undefined) {
      setDraft('');
      setFiles([]);
    }
    const done = await deliver(body, pending);
    if (!done) setFailed({ body, files: pending, at: new Date().toISOString() });
  };

  const handleRetry = async () => {
    if (!failed) return;
    const done = await deliver(failed.body, failed.files);
    if (done) setFailed(null);
  };

  return { draft, setDraft, files, setFiles, failed, pickError, picker, sentMessageId, runner, handleSend, handleRetry };
}
