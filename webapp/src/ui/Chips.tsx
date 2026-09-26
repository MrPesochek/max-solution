import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { strings } from '../strings/ru';

export type ChipVariant = 'fill' | 'outline';
export type ChipSize = 'm' | 's';

export function Chips({
  children,
  label,
  scroll,
}: {
  children: ReactNode;
  label?: string;
  scroll?: boolean;
}) {
  return (
    <div
      className={`ui-chips${scroll ? ' ui-chips--scroll' : ''}`}
      role={label ? 'group' : undefined}
      aria-label={label}
    >
      {children}
    </div>
  );
}

export function Chip({
  children,
  selected,
  onClick,
  disabled,
  variant = 'fill',
  size = 'm',
}: {
  children: ReactNode;
  selected?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  variant?: ChipVariant;
  size?: ChipSize;
}) {
  return (
    <button
      type="button"
      className={`ui-chip ui-chip--${variant} ui-chip--${size}`}
      aria-pressed={selected ?? false}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export interface ChipOption<T extends string = string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

type ChipGroupProps<T extends string> = {
  label: string;
  options: ChipOption<T>[];
  variant?: ChipVariant;
  size?: ChipSize;
  scroll?: boolean;
  disabled?: boolean;
} & (
  | { multiple?: false; value: T | null; onChange: (value: T) => void }
  | { multiple: true; value: T[]; onChange: (value: T[]) => void }
);

export function ChipGroup<T extends string>(props: ChipGroupProps<T>) {
  const { label, options, variant = 'fill', size = 'm', scroll, disabled } = props;
  const refs = useRef(new Map<T, HTMLButtonElement>());

  const isSelected = (value: T) =>
    props.multiple ? props.value.includes(value) : props.value === value;

  const toggle = (value: T) => {
    if (props.multiple) {
      const next = props.value.includes(value)
        ? props.value.filter((item) => item !== value)
        : [...props.value, value];
      props.onChange(next);
    } else {
      props.onChange(value);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (props.multiple) return;
    const enabled = options.filter((option) => !option.disabled);
    const index = enabled.findIndex((option) => option.value === props.value);
    let next: ChipOption<T> | undefined;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = enabled[(index + 1) % enabled.length];
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp')
      next = enabled[(index - 1 + enabled.length) % enabled.length];
    if (!next) return;
    event.preventDefault();
    props.onChange(next.value);
    refs.current.get(next.value)?.focus();
  };

  const single = !props.multiple;
  const focusable = single
    ? (options.find((option) => option.value === props.value && !option.disabled) ??
      options.find((option) => !option.disabled))?.value
    : undefined;

  return (
    <div
      className={`ui-chips${scroll ? ' ui-chips--scroll' : ''}`}
      role={single ? 'radiogroup' : 'group'}
      aria-label={label}
      onKeyDown={handleKeyDown}
    >
      {options.map((option) => {
        const selected = isSelected(option.value);
        return (
          <button
            key={option.value}
            ref={(node) => {
              if (node) refs.current.set(option.value, node);
              else refs.current.delete(option.value);
            }}
            type="button"
            className={`ui-chip ui-chip--${variant} ui-chip--${size}`}
            role={single ? 'radio' : undefined}
            aria-checked={single ? selected : undefined}
            aria-pressed={single ? undefined : selected}
            tabIndex={single ? (option.value === focusable ? 0 : -1) : undefined}
            disabled={disabled || option.disabled}
            onClick={() => toggle(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export interface FilterOption {
  value: string;
  label: string;
}

interface FilterChipProps {
  label: string;
  allLabel: string;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function FilterChip({ label, allLabel, value, options, onChange, disabled }: FilterChipProps) {
  const selected = options.find((option) => option.value === value);
  return (
    <span className={`ui-chip ui-chip--outline ui-chip--s${selected ? ' ui-chip--active' : ''}`}>
      <span aria-hidden="true">
        {selected ? `${selected.label} ✕` : `${allLabel} ▾`}
      </span>
      <select
        className="ui-chip__select"
        aria-label={label}
        title={selected ? strings.ui.clearFilter(selected.label) : undefined}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  );
}
