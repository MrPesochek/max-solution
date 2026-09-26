import type { ReactNode } from 'react';

export interface KeyValueRow {
  id?: string;
  label: ReactNode;
  value: ReactNode;
  oldValue?: ReactNode;
  mono?: boolean;
  tone?: 'accent' | 'error';
  hint?: ReactNode;
}

interface KeyValueRowsProps {
  rows: KeyValueRow[];
  variant?: 'info' | 'items';
  total?: { label: ReactNode; value: ReactNode };
  'aria-label'?: string;
  className?: string;
}

export function KeyValueRows({
  rows,
  variant = 'info',
  total,
  'aria-label': ariaLabel,
  className,
}: KeyValueRowsProps) {
  return (
    <div className={['ui-kv', `ui-kv--${variant}`, className].filter(Boolean).join(' ')}>
      <dl className="ui-kv__list" aria-label={ariaLabel}>
        {rows.map((row, index) => (
          <div key={row.id ?? (typeof row.label === 'string' ? row.label : index)} className="ui-kv__row">
            <dt className="ui-kv__key">
              {row.label}
              {row.hint && <span className="ui-kv__hint">{row.hint}</span>}
            </dt>
            <dd
              className={[
                'ui-kv__value',
                row.mono && 'ui-kv__value--mono',
                row.tone && `ui-kv__value--${row.tone}`,
              ]
                .filter(Boolean)
                .join(' ')}
            >
              {row.oldValue && <s className="ui-kv__old">{row.oldValue}</s>}
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      {total && (
        <div className="ui-kv__total">
          <span className="ui-kv__total-label">{total.label}</span>
          <span className="ui-kv__total-value">{total.value}</span>
        </div>
      )}
    </div>
  );
}
