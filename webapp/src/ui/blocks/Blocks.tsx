import type { ReactNode } from 'react';
import { initials } from '../format';

export type Tone = 'a' | 'w' | 'ok' | 'x' | 'y';
export type Gradient = 'o' | 'b' | 'r' | 'g' | 'p' | 'n' | 'a';

type HeadingTag = 'h1' | 'h2' | 'h3';

export function PageTitle({
  children,
  subtitle,
  eyebrow,
  eyebrowTone,
  size = 'l',
  as: Tag = 'h2',
}: {
  children: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  eyebrowTone?: 'danger' | 'accent';
  size?: 'l' | 'm';
  as?: HeadingTag;
}) {
  return (
    <div className={`ui-title ui-title--${size}`}>
      {eyebrow && (
        <span className={`ui-title__eyebrow${eyebrowTone ? ` ui-title__eyebrow--${eyebrowTone}` : ''}`}>
          {eyebrow}
        </span>
      )}
      <Tag className="ui-title__text">{children}</Tag>
      {subtitle && <p className="ui-title__sub">{subtitle}</p>}
    </div>
  );
}

export function SectionCaption({
  children,
  as: Tag = 'h3',
  id,
  action,
  large,
}: {
  children: ReactNode;
  as?: HeadingTag | 'div';
  id?: string;
  action?: ReactNode;
  large?: boolean;
}) {
  const heading = (
    <Tag className={`ui-caption${large ? ' ui-caption--large' : ''}`} id={id}>
      {children}
    </Tag>
  );
  if (!action) return heading;
  return (
    <div className="ui-caption-row">
      {heading}
      <span className="ui-caption-row__action">{action}</span>
    </div>
  );
}

export function Note({
  children,
  tone,
  role,
}: {
  children: ReactNode;
  tone?: 'error';
  role?: 'alert' | 'status';
}) {
  return (
    <p className={`ui-note${tone === 'error' ? ' ui-note--error' : ''}`} role={role}>
      {children}
    </p>
  );
}

export function TextCard({ children }: { children: ReactNode }) {
  return <div className="ui-card">{children}</div>;
}

export function Banner({
  title,
  children,
  tone = 'a',
  role,
  actions,
}: {
  title: ReactNode;
  children?: ReactNode;
  tone?: Tone;
  role?: 'alert' | 'status';
  actions?: ReactNode;
}) {
  return (
    <div className={`ui-banner ui-tone-${tone}`} role={role}>
      <span className="ui-banner__title">{title}</span>
      {children && <span className="ui-banner__text">{children}</span>}
      {actions && <div className="ui-banner__extra">{actions}</div>}
    </div>
  );
}

export function PriceBlock({
  value,
  caption,
  oldValue,
  children,
}: {
  value: ReactNode;
  caption?: ReactNode;
  oldValue?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="ui-price">
      <div className="ui-price__row">
        <span className="ui-price__value">{value}</span>
        {oldValue && <s className="ui-price__old">{oldValue}</s>}
      </div>
      {caption && <span className="ui-price__caption">{caption}</span>}
      {children}
    </div>
  );
}

export function Tag({ children, tone = 'w' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`ui-tag ui-tone-${tone}`}>{children}</span>;
}

export function Avatar({
  children,
  name,
  gradient = 'o',
  size = 40,
  square,
  'aria-hidden': ariaHidden,
}: {
  children?: ReactNode;
  name?: string | null;
  gradient?: Gradient;
  size?: number;
  square?: boolean;
  'aria-hidden'?: boolean;
}) {
  const tone = gradient === 'a' ? 'ui-avatar--strong' : gradient === 'n' ? 'ui-avatar--muted' : '';
  return (
    <span
      className={['ui-avatar', tone, square && 'ui-avatar--square'].filter(Boolean).join(' ')}
      style={size === 40 ? undefined : { width: size, height: size, fontSize: Math.round(size * 0.34) }}
      aria-hidden={ariaHidden || undefined}
    >
      {children ?? initials(name)}
    </span>
  );
}
