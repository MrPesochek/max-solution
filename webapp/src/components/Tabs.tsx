import { useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
}

interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  idPrefix: string;
  label: string;
  children?: ReactNode;
}

export function Tabs<T extends string>({ items, value, onChange, idPrefix, label, children }: TabsProps<T>) {
  const refs = useRef(new Map<T, HTMLButtonElement>());
  const panelId = `${idPrefix}-panel`;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.id === value);
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % items.length;
    if (event.key === 'ArrowLeft') nextIndex = (index - 1 + items.length) % items.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = items.length - 1;
    const next = nextIndex === null ? undefined : items[nextIndex];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    refs.current.get(next.id)?.focus();
  };

  return (
    <>
      <div
        className="ui-segmented ui-segmented--m"
        style={{ '--ui-seg-count': items.length } as CSSProperties}
        role="tablist"
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
              role="tab"
              id={`${idPrefix}-${item.id}`}
              aria-selected={selected}
              aria-controls={children === undefined ? undefined : panelId}
              tabIndex={selected ? 0 : -1}
              className="ui-segmented__item"
              onClick={() => onChange(item.id)}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {children !== undefined && (
        <div id={panelId} role="tabpanel" aria-labelledby={`${idPrefix}-${value}`}>
          {children}
        </div>
      )}
    </>
  );
}
