import type { ReactNode } from 'react';
import { Spinner } from '@maxhub/max-ui';
import { useAttachmentBlobUrl } from '../api/hooks/useAttachments';
import { strings } from '../strings/ru';

export function PhotoGrid({
  children,
  label,
  columns = 3,
}: {
  children: ReactNode;
  label?: string;
  columns?: 3 | 4;
}) {
  return (
    <div
      className={`ui-photos${columns === 4 ? ' ui-photos--4' : ''}`}
      role={label ? 'group' : undefined}
      aria-label={label}
    >
      {children}
    </div>
  );
}

export type PhotoState = 'ok' | 'e' | 'q' | 'add' | 'off';

const INNER: Record<PhotoState, string> = {
  ok: strings.ui.photoPlaceholder,
  e: strings.ui.photoReplace,
  q: strings.ui.photoChecking,
  add: '',
  off: strings.ui.photoNone,
};

const STATUS: Partial<Record<PhotoState, string>> = {
  e: strings.ui.photoRejected,
  q: strings.ui.photoChecking,
};

interface PhotoTileProps {
  label?: ReactNode;
  state?: PhotoState;
  attachmentId?: string | null;
  alt?: string;
  onClick?: () => void;
  actionLabel?: string;
  disabled?: boolean;
  selected?: boolean;
}

export function PhotoTile({
  label,
  state = 'ok',
  attachmentId,
  alt,
  onClick,
  actionLabel,
  disabled,
  selected,
}: PhotoTileProps) {
  const { url, isLoading } = useAttachmentBlobUrl(state === 'ok' ? attachmentId : null, 'thumb');
  const showImage = state === 'ok' && url;

  const inner = showImage ? (
    <img className="ui-photo__img" src={url} alt={alt ?? strings.attachments.defaultAlt} />
  ) : isLoading && attachmentId ? (
    <Spinner size={20} />
  ) : state === 'add' ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  ) : (
    <span aria-hidden={alt ? true : undefined}>
      {state === 'e' && !onClick ? strings.ui.photoRejected : INNER[state]}
    </span>
  );
  const status = STATUS[state];
  const withStatus = (text: string | undefined) => (text && status ? `${text}. ${status}` : text);

  const tileClass = `ui-photo__tile ui-photo__tile--${state}`;
  return (
    <div className={`ui-photo ui-photo--${state}`}>
      {onClick ? (
        <button
          type="button"
          className={tileClass}
          aria-label={actionLabel ?? withStatus(alt)}
          aria-pressed={selected}
          disabled={disabled}
          onClick={onClick}
        >
          {inner}
          {selected && (
            <span className="ui-photo__check" aria-hidden="true">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                <path
                  d="M5 12.5l4.5 4.5L19 7.5"
                  stroke="currentColor"
                  strokeWidth="3.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          )}
        </button>
      ) : (
        <div
          className={tileClass}
          role={!showImage && alt ? 'img' : undefined}
          aria-label={!showImage && alt ? withStatus(alt) : undefined}
        >
          {inner}
        </div>
      )}
      {label && <span className="ui-photo__label">{label}</span>}
    </div>
  );
}
