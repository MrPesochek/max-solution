const CHECK_PATH = 'M5 12.5l4.5 4.5L19 7.5';

function Tick({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={CHECK_PATH} stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function CheckMark({ checked, disabled }: { checked: boolean; disabled?: boolean }) {
  return (
    <span
      className={['ui-check', checked && 'ui-check--on', disabled && 'ui-check--off'].filter(Boolean).join(' ')}
      aria-hidden="true"
    >
      {checked && <Tick size={14} />}
    </span>
  );
}

export function Radio({
  checked,
  variant = 'check',
  disabled,
}: {
  checked: boolean;
  variant?: 'check' | 'dot';
  disabled?: boolean;
}) {
  return (
    <span
      className={[
        'ui-radio',
        `ui-radio--${variant}`,
        checked && 'ui-radio--on',
        disabled && 'ui-radio--off',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-hidden="true"
    >
      {checked && variant === 'check' && <Tick size={14} />}
    </span>
  );
}
