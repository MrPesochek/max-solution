import { useId, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Spinner } from '@maxhub/max-ui';
import { Avatar, Tag, type Gradient, type Tone } from './blocks/Blocks';
import { CheckMark, Radio } from './Check';
import { ToggleTrack } from './Toggle';
import { Illustration, type IllustrationName } from './illustrations';

interface ListProps {
  children: ReactNode;
  role?: 'radiogroup' | 'group';
  'aria-label'?: string;
  className?: string;
  variant?: 'plain' | 'card';
}

export function List({
  children,
  role,
  className,
  variant = 'plain',
  'aria-label': ariaLabel,
}: ListProps) {
  return (
    <div
      className={['ui-list', variant === 'card' && 'ui-list--card', className]
        .filter(Boolean)
        .join(' ')}
      role={role}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}

export type RowMarker = 'ok' | 'x' | 'w' | '-';
export type RowControl =
  | { type: 'checkbox'; checked: boolean }
  | { type: 'radio'; checked: boolean }
  | { type: 'switch'; checked: boolean };

export interface ListRowProps {
  title: ReactNode;
  subtitle?: ReactNode;
  subtitleTone?: 'error' | 'accent';
  icon?: ReactNode;
  gradient?: Gradient;
  media?: IllustrationName;
  marker?: RowMarker;
  tag?: { label: ReactNode; tone?: Tone };
  value?: ReactNode;
  valueTone?: 'strong' | 'accent' | 'secondary';
  oldValue?: ReactNode;
  count?: number | string;
  chevron?: boolean;
  action?: 'accent' | 'danger';
  control?: RowControl;
  to?: string;
  href?: string;
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  onToggle?: (next: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
  'aria-label'?: string;
  expanded?: boolean;
  opensDialog?: boolean;
  extra?: ReactNode;
  className?: string;
}

const MARKS: Record<RowMarker, string> = { ok: '✓', x: '✕', w: '…', '-': '—' };

export function ListRow({
  title,
  subtitle,
  subtitleTone,
  icon,
  gradient,
  media,
  marker,
  tag,
  value,
  valueTone,
  oldValue,
  count,
  chevron,
  action,
  control,
  to,
  href,
  onClick,
  onToggle,
  disabled,
  loading,
  extra,
  className,
  expanded,
  opensDialog,
  'aria-label': ariaLabel,
}: ListRowProps) {
  const baseId = useId();
  const hasValue = value !== undefined && value !== null && value !== '';
  const describedBy = ariaLabel
    ? [
        subtitle && `${baseId}-sub`,
        tag && `${baseId}-tag`,
        hasValue && `${baseId}-value`,
        extra && `${baseId}-extra`,
      ]
        .filter(Boolean)
        .join(' ') || undefined
    : undefined;
  const hasLead =
    icon !== undefined ||
    media !== undefined ||
    marker !== undefined ||
    control?.type === 'checkbox';
  const tall = Boolean(subtitle) || Boolean(tag);
  const classes = ['ui-row', tall && 'ui-row--tall', hasLead && 'ui-row--lead', className]
    .filter(Boolean)
    .join(' ');

  const titleClasses = [
    'ui-row__title',
    (tall || action) && 'ui-row__title--strong',
    action && 'ui-row__title--action',
    action === 'danger' && 'ui-row__title--danger',
  ]
    .filter(Boolean)
    .join(' ');

  const content = (
    <>
      {media !== undefined && <Illustration name={media} width={52} className="ui-row__media" />}
      {icon !== undefined && (
        <Avatar gradient={gradient} aria-hidden>
          {icon}
        </Avatar>
      )}
      {marker !== undefined && (
        <span
          className={`ui-row__marker${marker === 'ok' ? ' ui-row__marker--ok' : marker === 'x' ? ' ui-row__marker--x' : ''}`}
          aria-hidden="true"
        >
          {MARKS[marker]}
        </span>
      )}
      {control?.type === 'checkbox' && <CheckMark checked={control.checked} />}
      <span className="ui-row__main">
        <span className={titleClasses}>{title}</span>
        {subtitle && (
          <span
            id={`${baseId}-sub`}
            className={`ui-row__sub${subtitleTone === 'error' ? ' ui-row__sub--error' : subtitleTone === 'accent' ? ' ui-row__sub--accent' : ''}`}
          >
            {subtitle}
          </span>
        )}
        {tag && (
          <span id={`${baseId}-tag`} className="ui-contents">
            <Tag tone={tag.tone}>{tag.label}</Tag>
          </span>
        )}
        {extra && (
          <span id={`${baseId}-extra`} className="ui-contents">
            {extra}
          </span>
        )}
      </span>
      {hasValue || oldValue ? (
        <span className="ui-row__right">
          {oldValue && <s className="ui-row__old">{oldValue}</s>}
          {hasValue && (
            <span
              id={`${baseId}-value`}
              className={[
                'ui-row__value',
                valueTone === 'strong' && 'ui-row__value--strong',
                valueTone === 'accent' && 'ui-row__value--accent',
                valueTone === 'secondary' && 'ui-row__value--secondary',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {value}
            </span>
          )}
        </span>
      ) : null}
      {count !== undefined && count !== null && count !== 0 && count !== '' && (
        <span className="ui-row__count">{count}</span>
      )}
      {control?.type === 'radio' && <Radio checked={control.checked} />}
      {control?.type === 'switch' && <ToggleTrack checked={control.checked} />}
      {loading && <Spinner className="ui-row__spinner" size={20} />}
      {chevron && <span className="ui-row__chevron" aria-hidden="true" />}
    </>
  );

  if (to && !disabled) {
    return (
      <Link
        className={classes}
        to={to}
        onClick={onClick}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
      >
        {content}
      </Link>
    );
  }
  if (href && !disabled) {
    return (
      <a
        className={classes}
        href={href}
        onClick={onClick}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
      >
        {content}
      </a>
    );
  }

  if (control) {
    const handle = (event: MouseEvent<HTMLElement>) => {
      onClick?.(event);
      onToggle?.(control.type === 'radio' ? true : !control.checked);
    };
    const handleKey = (event: KeyboardEvent<HTMLButtonElement>) => {
      if (control.type !== 'radio') return;
      if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) return;
      const group = event.currentTarget.closest('[role="radiogroup"]');
      if (!group) return;
      const radios = Array.from(
        group.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'),
      );
      const index = radios.indexOf(event.currentTarget);
      const step = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
      const next = radios[(index + step + radios.length) % radios.length];
      if (!next) return;
      event.preventDefault();
      next.focus();
      next.click();
    };
    return (
      <button
        type="button"
        className={classes}
        role={control.type}
        aria-checked={control.checked}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        disabled={disabled || loading}
        onClick={handle}
        onKeyDown={handleKey}
      >
        {content}
      </button>
    );
  }

  if (onClick) {
    return (
      <button
        type="button"
        className={classes}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        aria-expanded={opensDialog ? undefined : expanded}
        aria-haspopup={opensDialog ? 'dialog' : undefined}
        disabled={disabled || loading}
        onClick={onClick}
      >
        {content}
      </button>
    );
  }

  return <div className={classes}>{content}</div>;
}
