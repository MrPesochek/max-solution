import type { KeyboardEvent } from 'react';
import { strings } from '../strings/ru';

const STARS = [1, 2, 3, 4, 5];
const STAR_PATH = 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z';

function StarIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d={STAR_PATH} fill="currentColor" />
    </svg>
  );
}

interface StarRatingProps {
  value: number;
  onChange?: (value: number) => void;
  label?: string;
  disabled?: boolean;
  captions?: boolean | string[];
  size?: 'l' | 's';
}

export function StarRating({
  value,
  onChange,
  label = strings.ui.starsLabel,
  disabled,
  captions,
  size = onChange ? 'l' : 's',
}: StarRatingProps) {
  const captionList = Array.isArray(captions) ? captions : captions ? strings.ui.starCaptions : null;
  const caption = captionList ? (value > 0 ? captionList[value - 1] : strings.ui.starPrompt) : null;

  if (!onChange) {
    return (
      <div className={`ui-stars ui-stars--${size}`} role="img" aria-label={`${label}: ${strings.ui.star(value)}`}>
        {STARS.map((star) => (
          <span
            key={star}
            className={`ui-stars__star${star <= value ? ' ui-stars__star--on' : ''}`}
            aria-hidden="true"
          >
            <StarIcon size={size === 'l' ? 28 : 16} />
          </span>
        ))}
      </div>
    );
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowUp'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowDown'
          ? -1
          : 0;
    if (!step) return;
    event.preventDefault();
    const next = Math.min(5, Math.max(1, (value || 0) + step));
    onChange(next);
    const group = event.currentTarget.parentElement;
    group?.querySelectorAll<HTMLButtonElement>('button')[next - 1]?.focus();
  };

  return (
    <div className="ui-rating">
      <div className={`ui-stars ui-stars--${size}`} role="radiogroup" aria-label={label}>
        {STARS.map((star) => (
          <button
            key={star}
            type="button"
            role="radio"
            aria-checked={star === value}
            aria-label={strings.ui.star(star)}
            tabIndex={star === (value || 1) ? 0 : -1}
            disabled={disabled}
            className={`ui-stars__star${star <= value ? ' ui-stars__star--on' : ''}`}
            onClick={() => onChange(star)}
            onKeyDown={handleKeyDown}
          >
            <StarIcon size={size === 'l' ? 28 : 16} />
          </button>
        ))}
      </div>
      {caption && (
        <span className="ui-rating__caption" aria-live="polite">
          {caption}
        </span>
      )}
    </div>
  );
}

interface StarsProps {
  value: number;
  onChange?: (value: number) => void;
  label?: string;
  disabled?: boolean;
}

export function Stars(props: StarsProps) {
  return <StarRating {...props} />;
}
