import type { ChangeEvent } from 'react';
import { FormLabel } from './FormLabel';

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  allowEmpty?: boolean;
}

export function Select({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
  disabled,
  allowEmpty = false,
}: SelectProps) {
  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => onChange(event.target.value);

  return (
    <div>
      <FormLabel htmlFor={id}>{label}</FormLabel>
      <select
        id={id}
        className="max-select"
        value={value}
        disabled={disabled}
        onChange={handleChange}
      >
        {placeholder && (
          <option value="" disabled={!allowEmpty}>
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
