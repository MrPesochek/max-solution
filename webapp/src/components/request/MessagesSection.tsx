import { Fragment, useEffect, useState, type ReactNode } from 'react';
import { strings } from '../../strings/ru';
import { usePostMessage, useRequestMessages } from '../../api/hooks/useRequests';
import type { MessageFeed } from '../../api/hooks/messageFeed';
import type { Attachment, RequestMessage } from '../../api/types';
import { dayLabel, formatTime, messageTime } from '../../lib/datetime';
import { MessageBubble } from '../../ui/MessageBubble';
import { List, ListRow } from '../../ui/List';
import { Note } from '../../ui/blocks/Blocks';
import { TextField } from '../../ui/FormField';
import { ActionButton } from '../../ui/layout/ActionButton';
import { useUnsavedGuard } from '../../ui/layout/unsavedGuard';
import { Skeleton } from '../states/Skeleton';
import { ErrorState } from '../states/ErrorState';
import { AttachmentThumb } from '../attachments/AttachmentThumb';
import { ActionFeedback } from '../actions/ActionFeedback';
import { useMessageComposer, type FailedMessage } from './useMessageComposer';
import './request.css';

export interface MessageThreadSource {
  query: MessageFeed;
  send: (body: string) => Promise<RequestMessage>;
}

interface MessagesSectionProps {
  requestId: string;
  assignmentId?: string;
  ownAuthorKind: string;
  placeholder?: string;
  sendLabel?: string;
  allowPhotos?: boolean;
  attachments?: Attachment[];
  embedded?: boolean;
  otherAuthor?: string;
  canPost?: boolean;
  timezone?: string | null;
  thread?: MessageThreadSource;
  filter?: (message: RequestMessage) => boolean;
  fieldLabel?: string;
  onSendError?: (error: unknown) => void;
  variant?: 'bubbles' | 'chat';
  quickReplies?: readonly string[];
  authorName?: (message: RequestMessage) => string | null;
  deliveredToCrm?: (message: RequestMessage) => boolean;
}

export function MessagesSection({
  requestId,
  ownAuthorKind,
  assignmentId,
  placeholder = strings.requests.card.messagePlaceholder,
  sendLabel = strings.requests.card.messageSend,
  allowPhotos = false,
  attachments = [],
  embedded = false,
  otherAuthor,
  canPost = true,
  timezone,
  thread,
  filter,
  fieldLabel = strings.requests.messages.fieldLabel,
  onSendError,
  variant = 'bubbles',
  quickReplies = [],
  authorName,
  deliveredToCrm,
}: MessagesSectionProps) {
  const [openState, setOpen] = useState(false);
  const open = embedded || openState;
  const requestMessages = useRequestMessages(requestId, open && !thread);
  const messages = thread?.query ?? requestMessages;
  const visible = filter ? messages.data?.filter(filter) : messages.data;
  const postMessage = usePostMessage(requestId);
  const { draft, setDraft, files, setFiles, failed, pickError, picker, sentMessageId, runner, handleSend, handleRetry } =
    useMessageComposer({
      requestId,
      send: (body) => (thread ? thread.send(body) : postMessage.mutateAsync({ body, assignment_id: assignmentId })),
      onSendError,
    });
  const unsaved = useUnsavedGuard();
  const composerEmpty = !draft.trim() && files.length === 0;
  useEffect(() => {
    if (composerEmpty) unsaved.reset();
  }, [composerEmpty, unsaved]);

  const authorOf = (m: RequestMessage) =>
    m.author_kind === ownAuthorKind
      ? strings.requests.messages.you
      : (authorName?.(m) ?? otherAuthor ?? strings.requests.messages.author[m.author_kind] ?? m.author_kind);

  const earlier = messages.hasNextPage ? (
    <div className="ui-pad">
      <ActionButton
        kind="s"
        compact
        loading={messages.isFetchingNextPage}
        onClick={() => void messages.fetchNextPage()}
      >
        {strings.requests.messages.loadEarlier}
      </ActionButton>
    </div>
  ) : null;
  const pickNote = pickError ? (
    <Note tone="error" role="alert">
      {pickError}
    </Note>
  ) : null;

  if (variant === 'chat') {
    return (
      <ChatFeed
        earlier={earlier}
        messages={visible}
        loading={messages.isPending}
        error={messages.isError ? messages.error : null}
        onRetryLoad={() => void messages.refetch()}
        ownAuthorKind={ownAuthorKind}
        attachments={attachments}
        timezone={timezone}
        authorLabel={(m) => {
          if (m.author_kind === ownAuthorKind) return null;
          const name = authorOf(m);
          return name === otherAuthor ? null : name;
        }}
        deliveredToCrm={deliveredToCrm}
        failed={failed}
        retry={
          <button
            type="button"
            className="request-inline-action"
            disabled={runner.busy}
            onClick={() => void handleRetry()}
          >
            {strings.requests.messages.retry}
          </button>
        }
        footer={
          canPost ? (
            <div className="request-compose">
              {quickReplies.length > 0 && (
                <div className="request-quick" role="group" aria-label={strings.requests.messages.quickLabel}>
                  {quickReplies.map((reply) => (
                    <button
                      key={reply}
                      type="button"
                      className="request-quick__chip"
                      disabled={runner.busy || Boolean(failed) || Boolean(sentMessageId)}
                      onClick={() => void handleSend(reply)}
                    >
                      {reply}
                    </button>
                  ))}
                </div>
              )}
              {files.length > 0 && (
                <div className="request-compose__files">
                  <List aria-label={strings.requests.card.messagePhotosPending}>
                    {files.map((file) => (
                      <ListRow
                        key={`${file.name}-${file.lastModified}`}
                        title={file.name}
                        action="danger"
                        aria-label={`${strings.requests.card.attachmentDelete}: ${file.name}`}
                        value={strings.requests.card.attachmentDelete}
                        disabled={runner.busy}
                        onClick={() => setFiles((current) => current.filter((f) => f !== file))}
                      />
                    ))}
                  </List>
                </div>
              )}
              <div className="request-compose__row">
                {allowPhotos && (
                  <>
                    <input {...picker.inputProps} aria-label={strings.requests.card.messageAttachPhoto} />
                    <button
                      type="button"
                      className="request-compose__icon"
                      aria-label={strings.requests.card.messageAttachPhoto}
                      disabled={runner.busy || Boolean(failed)}
                      onClick={picker.open}
                    >
                      <AttachIcon />
                    </button>
                  </>
                )}
                <input
                  className="request-compose__input"
                  value={draft}
                  aria-label={placeholder}
                  placeholder={placeholder}
                  maxLength={4000}
                  enterKeyHint="send"
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && draft.trim() && !runner.busy && !failed) {
                      event.preventDefault();
                      void handleSend();
                    }
                  }}
                  disabled={Boolean(sentMessageId) || Boolean(failed)}
                />
                <button
                  type="button"
                  className="request-compose__send"
                  aria-label={sendLabel}
                  disabled={(!draft.trim() && !sentMessageId) || runner.busy || Boolean(failed)}
                  onClick={() => void handleSend()}
                >
                  <SendIcon />
                </button>
              </div>
              <div className="ui-pad">
                {pickNote}
                <ActionFeedback feedback={runner.feedback} />
              </div>
            </div>
          ) : null
        }
      />
    );
  }

  return (
    <>
      {!embedded && (
        <List>
          <ListRow
            title={open ? strings.requests.card.messagesHide : strings.requests.card.messagesShow}
            chevron
            expanded={open}
            onClick={() => setOpen((v) => !v)}
          />
        </List>
      )}
      {open && (
        <section aria-label={strings.requests.card.messagesTitle}>
          {messages.isPending && <Skeleton lines={2} />}
          {messages.isError && <ErrorState error={messages.error} onRetry={() => void messages.refetch()} />}
          {earlier}
          {messages.isSuccess && visible?.length === 0 && !failed && (
            <Note>{strings.requests.card.messagesEmpty}</Note>
          )}
          {visible?.map((m) => {
            const photos = attachments.filter((a) => a.message_id === m.id);
            return (
              <MessageBubble
                key={m.id}
                mine={m.author_kind === ownAuthorKind}
                author={authorOf(m)}
                time={messageTime(m.created_at, timezone)}
                extra={photos.length > 0 ? strings.requests.messages.photoCount(photos.length) : undefined}
                attachments={
                  photos.length > 0 ? (
                    <div className="request-message-photos">
                      {photos.map((a, index) => (
                        <AttachmentThumb
                          key={a.id}
                          attachment={a}
                          alt={strings.attachments.messagePhotoAlt(index + 1)}
                        />
                      ))}
                    </div>
                  ) : undefined
                }
              >
                {m.body}
              </MessageBubble>
            );
          })}
          {failed && (
            <MessageBubble
              mine
              author={strings.requests.messages.you}
              time={formatTime(failed.at, timezone)}
              extraTone="error"
              extra={
                <>
                  {strings.requests.messages.notDelivered} ·{' '}
                  <button
                    type="button"
                    className="request-inline-action"
                    disabled={runner.busy}
                    onClick={() => void handleRetry()}
                  >
                    {strings.requests.messages.retry}
                  </button>
                </>
              }
            >
              {failed.body}
            </MessageBubble>
          )}

          {canPost && (
            <div className="request-composer">
              <TextField
                label={fieldLabel}
                value={draft}
                aria-label={placeholder}
                placeholder={placeholder}
                maxLength={4000}
                onChange={setDraft}
                enterKeyHint="send"
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && draft.trim() && !runner.busy && !failed) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                disabled={Boolean(sentMessageId) || Boolean(failed)}
              />
              {files.length > 0 && (
                <List aria-label={strings.requests.card.messagePhotosPending}>
                  {files.map((file) => (
                    <ListRow
                      key={`${file.name}-${file.lastModified}`}
                      title={file.name}
                      action="danger"
                      aria-label={`${strings.requests.card.attachmentDelete}: ${file.name}`}
                      value={strings.requests.card.attachmentDelete}
                      disabled={runner.busy}
                      onClick={() => setFiles((current) => current.filter((f) => f !== file))}
                    />
                  ))}
                </List>
              )}
              <div className="request-composer__actions">
                {allowPhotos && (
                  <>
                    <input {...picker.inputProps} aria-label={strings.requests.card.messageAttachPhoto} />
                    <ActionButton
                      kind="s"
                      compact
                      disabled={runner.busy || Boolean(failed)}
                      onClick={picker.open}
                    >
                      {strings.requests.card.messageAttachPhoto}
                    </ActionButton>
                  </>
                )}
                <ActionButton
                  compact
                  loading={runner.isRunning('send') && !failed}
                  disabled={(!draft.trim() && !sentMessageId) || runner.busy || Boolean(failed)}
                  onClick={() => void handleSend()}
                >
                  {sendLabel}
                </ActionButton>
              </div>
            </div>
          )}
          <div className="ui-pad">
            {pickNote}
            <ActionFeedback feedback={runner.feedback} />
          </div>
        </section>
      )}
    </>
  );
}

function AttachIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="6" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="13" r="3.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 6l1.5-2h3L15 6" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function feedDay(iso: string, timezone?: string | null): string {
  const label = dayLabel(iso, timezone);
  if (!label) return '';
  if (label.kind === 'today') return strings.requests.messages.today;
  if (label.kind === 'yesterday') return strings.requests.messages.yesterday;
  return label.date;
}

function ChatFeed({
  earlier,
  messages,
  loading,
  error,
  onRetryLoad,
  ownAuthorKind,
  attachments,
  timezone,
  authorLabel,
  deliveredToCrm,
  failed,
  retry,
  footer,
}: {
  earlier: ReactNode;
  messages: RequestMessage[] | undefined;
  loading: boolean;
  error: unknown;
  onRetryLoad: () => void;
  ownAuthorKind: string;
  attachments: Attachment[];
  timezone?: string | null;
  authorLabel: (message: RequestMessage) => string | null;
  deliveredToCrm?: (message: RequestMessage) => boolean;
  failed: FailedMessage | null;
  retry: ReactNode;
  footer: ReactNode;
}) {
  const sorted = [...(messages ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at));
  let lastDay = '';
  let lastAuthor = '';
  return (
    <section className="request-chat-feed" aria-label={strings.requests.card.messagesTitle}>
      <div className="request-feed">
        {earlier}
        {loading && <Skeleton lines={3} />}
        {Boolean(error) && <ErrorState error={error} onRetry={onRetryLoad} />}
        {!loading && !error && sorted.length === 0 && !failed && (
          <Note>{strings.requests.card.messagesEmpty}</Note>
        )}
        {sorted.map((m) => {
          const day = feedDay(m.created_at, timezone);
          const showDay = day !== lastDay;
          lastDay = day;
          const mine = m.author_kind === ownAuthorKind;
          const label = authorLabel(m);
          const showAuthor = Boolean(label) && `${m.author_kind}:${label}` !== lastAuthor;
          lastAuthor = mine ? '' : `${m.author_kind}:${label}`;
          const photos = attachments.filter((a) => a.message_id === m.id);
          return (
            <Fragment key={m.id}>
              {showDay && <span className="request-feed__day">{day}</span>}
              <div className={`request-bubble${mine ? ' request-bubble--mine' : ''}`}>
                {showAuthor && <span className="request-bubble__author">{label}</span>}
                <span className="request-bubble__body">
                  {mine && <span className="ui-visually-hidden">{strings.requests.messages.you}: </span>}
                  {m.body}
                </span>
                {photos.length > 0 && (
                  <div className="request-message-photos">
                    {photos.map((a, index) => (
                      <AttachmentThumb key={a.id} attachment={a} alt={strings.attachments.messagePhotoAlt(index + 1)} />
                    ))}
                  </div>
                )}
                <span className="request-bubble__time">
                  {mine && deliveredToCrm?.(m)
                    ? `${formatTime(m.created_at, timezone)} · ${strings.requests.messages.deliveredToCrm}`
                    : formatTime(m.created_at, timezone)}
                </span>
              </div>
            </Fragment>
          );
        })}
        {failed && (
          <div className="request-bubble request-bubble--mine">
            <span className="request-bubble__body">{failed.body}</span>
            <span className="request-bubble__time request-bubble__time--error">
              {strings.requests.messages.notDelivered} · {retry}
            </span>
          </div>
        )}
      </div>
      {footer}
    </section>
  );
}
