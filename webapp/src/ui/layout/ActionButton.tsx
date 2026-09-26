import type { MouseEvent, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@maxhub/max-ui';

export type ActionKind = 'p' | 's' | 'd' | 'g' | 'i';

export interface ActionButtonProps {
  children: ReactNode;
  kind?: ActionKind;
  onClick?: (event: MouseEvent<HTMLButtonElement | HTMLAnchorElement>) => void;
  to?: string;
  href?: string;
  disabled?: boolean;
  loading?: boolean;
  type?: 'button' | 'submit';
  compact?: boolean;
  className?: string;
  'aria-label'?: string;
  form?: string;
}

export function ActionButton({
  children,
  kind = 'p',
  onClick,
  to,
  href,
  disabled,
  loading,
  type = 'button',
  compact,
  className,
  form,
  'aria-label': ariaLabel,
}: ActionButtonProps) {
  const classes = ['ui-btn', `ui-btn--${kind}`, compact && 'ui-btn--compact', className]
    .filter(Boolean)
    .join(' ');

  if (to && !disabled) {
    return (
      <Button asChild className={classes} size="medium" variant="primary">
        <Link to={to} onClick={onClick} aria-label={ariaLabel}>
          {children}
        </Link>
      </Button>
    );
  }

  if (href && !disabled) {
    return (
      <Button asChild className={classes} size="medium" variant="primary">
        <a href={href} onClick={onClick} aria-label={ariaLabel}>
          {children}
        </a>
      </Button>
    );
  }

  return (
    <Button
      className={classes}
      size="medium"
      variant="primary"
      type={type}
      form={form}
      disabled={disabled || loading}
      loading={loading}
      aria-busy={loading || undefined}
      aria-label={ariaLabel}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}
