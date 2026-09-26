import type { KeyboardEvent, ReactNode } from 'react';
import { CheckMark, Radio } from './Check';
import { Illustration, type IllustrationName } from './illustrations';

interface ChoiceCardProps {
  title: ReactNode;
  subtitle?: ReactNode;
  selected: boolean;
  onSelect: () => void;
  control?: 'radio' | 'checkbox';
  illustration?: IllustrationName;
  illustrationWidth?: number;
  media?: ReactNode;
  children?: ReactNode;
  disabled?: boolean;
}

export function ChoiceCard({
  title,
  subtitle,
  selected,
  onSelect,
  control = 'radio',
  illustration,
  illustrationWidth = 84,
  media,
  children,
  disabled,
}: ChoiceCardProps) {
  return (
    <button
      type="button"
      role={control}
      aria-checked={selected}
      disabled={disabled}
      className={['ui-choice', selected && 'ui-choice--on', illustration && 'ui-choice--art'].filter(Boolean).join(' ')}
      onClick={onSelect}
    >
      <span className="ui-choice__head">
        {illustration && <Illustration name={illustration} width={illustrationWidth} />}
        {media}
        <span className="ui-choice__main">
          <span className="ui-choice__title">{title}</span>
          {subtitle && <span className="ui-choice__sub">{subtitle}</span>}
        </span>
        {control === 'radio' ? <Radio checked={selected} /> : <CheckMark checked={selected} />}
      </span>
      {children && <span className="ui-choice__extra">{children}</span>}
    </button>
  );
}

export function ChoiceGroup({ label, children }: { label: string; children: ReactNode }) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) return;
    const radios = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'),
    );
    const index = radios.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    const step = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
    const next = radios[(index + step + radios.length) % radios.length];
    if (!next) return;
    event.preventDefault();
    next.focus();
    next.click();
  };
  return (
    <div className="ui-choices" role="radiogroup" aria-label={label} onKeyDown={handleKeyDown}>
      {children}
    </div>
  );
}
