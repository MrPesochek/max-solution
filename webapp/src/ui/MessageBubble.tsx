import type { ReactNode } from 'react';

interface MessageBubbleProps {
  author: ReactNode;
  time?: ReactNode;
  children: ReactNode;
  mine?: boolean;
  extra?: ReactNode;
  extraTone?: 'error';
  attachments?: ReactNode;
}

export function MessageBubble({
  author,
  time,
  children,
  mine,
  extra,
  extraTone,
  attachments,
}: MessageBubbleProps) {
  return (
    <div className={`ui-message${mine ? ' ui-message--me' : ''}`}>
      <div className="ui-message__head">
        <span className="ui-message__author">{author}</span>
        {time && <span className="ui-message__time">{time}</span>}
      </div>
      <span className="ui-message__body">{children}</span>
      {attachments}
      {extra && (
        <span
          className={`ui-message__extra${extraTone === 'error' ? ' ui-message__extra--error' : ''}`}
        >
          {extra}
        </span>
      )}
    </div>
  );
}
