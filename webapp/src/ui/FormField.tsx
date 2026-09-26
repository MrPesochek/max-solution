import {
  useId,
  type ChangeEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

interface FieldFrameProps {
  label?: ReactNode;
  error?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  id: string;
  select?: boolean;
  children: ReactNode;
}

export function FieldFrame({ label, error, hint, disabled, id, select, children }: FieldFrameProps) {
  return (
    <div
      className={[
        'ui-field',
        error ? 'ui-field--error' : null,
        disabled ? 'ui-field--disabled' : null,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {label && (
        <label className="ui-field__label" htmlFor={id}>
          {label}
        </label>
      )}
      <div className={`ui-field__box${select ? ' ui-field__box--select' : ''}`}>{children}</div>
      {error ? (
        <span id={`${id}-error`} className="ui-field__error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={`${id}-hint`} className="ui-field__hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function describedBy(id: string, error: ReactNode, hint: ReactNode): string | undefined {
  if (error) return `${id}-error`;
  if (hint) return `${id}-hint`;
  return undefined;
}

type BaseFieldProps = {
  label?: ReactNode;
  error?: ReactNode;
  hint?: ReactNode;
};

export type TextFieldProps = BaseFieldProps &
  Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> & {
    onChange?: (value: string, event: ChangeEvent<HTMLInputElement>) => void;
  };

export function TextField({ label, error, hint, id, onChange, className, ...rest }: TextFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldFrame label={label} error={error} hint={hint} disabled={rest.disabled} id={fieldId}>
      <input
        id={fieldId}
        className={['ui-field__control', className].filter(Boolean).join(' ')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        onChange={(event) => onChange?.(event.target.value, event)}
        {...rest}
      />
    </FieldFrame>
  );
}

export function PhoneField(props: TextFieldProps) {
  return <TextField type="tel" inputMode="tel" autoComplete="tel" {...props} />;
}

export type TextAreaFieldProps = BaseFieldProps &
  Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange'> & {
    onChange?: (value: string, event: ChangeEvent<HTMLTextAreaElement>) => void;
  };

export function TextAreaField({
  label,
  error,
  hint,
  id,
  onChange,
  className,
  rows = 3,
  ...rest
}: TextAreaFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldFrame label={label} error={error} hint={hint} disabled={rest.disabled} id={fieldId}>
      <textarea
        id={fieldId}
        rows={rows}
        className={['ui-field__control', className].filter(Boolean).join(' ')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        onChange={(event) => onChange?.(event.target.value, event)}
        {...rest}
      />
    </FieldFrame>
  );
}

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export type SelectFieldProps = BaseFieldProps &
  Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value'> & {
    value: string;
    options: SelectOption[];
    placeholder?: string;
    allowEmpty?: boolean;
    onChange?: (value: string, event: ChangeEvent<HTMLSelectElement>) => void;
  };

export function SelectField({
  label,
  error,
  hint,
  id,
  value,
  options,
  placeholder,
  allowEmpty,
  onChange,
  className,
  ...rest
}: SelectFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  return (
    <FieldFrame label={label} error={error} hint={hint} disabled={rest.disabled} id={fieldId} select>
      <select
        id={fieldId}
        value={value}
        className={['ui-field__control', value === '' ? 'ui-field__control--empty' : null, className]
          .filter(Boolean)
          .join(' ')}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fieldId, error, hint)}
        onChange={(event) => onChange?.(event.target.value, event)}
        {...rest}
      >
        {placeholder !== undefined && (
          <option value="" disabled={!allowEmpty}>
            {placeholder}
          </option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}
