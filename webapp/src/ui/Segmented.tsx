import { useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';

export interface SegmentedItem<T extends string> {
  id: T;
  label: ReactNode;
  count?: number;
  countMore?: boolean;
}

interface SegmentedProps<T extends string> {
  items: SegmentedItem<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  mode?: 'radio' | 'tab';
  idPrefix?: string;
  size?: 'm' | 's';
}

export function Segmented<T extends string>({
  items,
  value,
  onChange,
  label,
  mode = 'radio',
  idPrefix,
  size = 'm',
}: SegmentedProps<T>) {
  const refs = useRef(new Map<T, HTMLButtonElement>());

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.id === value);
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % items.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp')
      nextIndex = (index - 1 + items.length) % items.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = items.length - 1;
    const next = nextIndex === null ? undefined : items[nextIndex];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    refs.current.get(next.id)?.focus();
  };

  return (
    <div
      className={`ui-segmented ui-segmented--${size}`}
      style={{ '--ui-seg-count': items.length } as CSSProperties}
      role={mode === 'tab' ? 'tablist' : 'radiogroup'}
      aria-label={label}
      onKeyDown={handleKeyDown}
    >
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(node) => {
              if (node) refs.current.set(item.id, node);
              else refs.current.delete(item.id);
            }}
            type="button"
            className="ui-segmented__item"
            role={mode === 'tab' ? 'tab' : 'radio'}
            id={idPrefix ? `${idPrefix}-${item.id}` : undefined}
            aria-checked={mode === 'radio' ? selected : undefined}
            aria-selected={mode === 'tab' ? selected : undefined}
            aria-controls={mode === 'tab' && idPrefix ? `${idPrefix}-panel` : undefined}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.id)}
          >
            <span className="ui-segmented__label">{item.label}</span>
            {item.count ? (
              <>
                {' '}
                <span className="ui-segmented__count">
                  {item.count > 99 ? '99+' : item.countMore ? `${item.count}+` : item.count}
                </span>
              </>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function SegmentTabs<T extends string>(props: Omit<SegmentedProps<T>, 'mode'>) {
  return <Segmented {...props} mode="tab" />;
}
