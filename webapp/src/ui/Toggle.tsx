import type { ReactNode } from 'react';

export type ToggleSize = 'm' | 'l';

export function ToggleTrack({ checked, size = 'm' }: { checked: boolean; size?: ToggleSize }) {
  return (
    <span
      className={`ui-toggle__track ui-toggle__track--${size}${checked ? ' ui-toggle__track--on' : ''}`}
      aria-hidden="true"
    />
  );
}

interface ToggleProps {
  checked: boolean;
  onChange?: (next: boolean) => void;
  children?: ReactNode;
  'aria-label'?: string;
  disabled?: boolean;
  size?: ToggleSize;
  pill?: boolean;
}

export function Toggle({
  checked,
  onChange,
  children,
  'aria-label': ariaLabel,
  disabled,
  size = 'm',
  pill,
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      className={['ui-toggle', pill && 'ui-toggle--pill'].filter(Boolean).join(' ')}
      onClick={() => onChange?.(!checked)}
    >
      <ToggleTrack checked={checked} size={size} />
      {children && <span className="ui-toggle__label">{children}</span>}
    </button>
  );
}
