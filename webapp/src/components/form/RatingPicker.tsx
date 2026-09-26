import { strings } from '../../strings/ru';

interface RatingPickerProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  label: string;
}

const STARS = [1, 2, 3, 4, 5];

export function RatingPicker({ value, onChange, disabled, label }: RatingPickerProps) {
  return (
    <div className="rating-picker" role="group" aria-label={label}>
      {STARS.map((star) => (
        <button
          key={star}
          type="button"
          disabled={disabled}
          className={`rating-picker__star${star <= value ? ' is-filled' : ''}`}
          aria-pressed={star === value}
          aria-label={strings.attachments.ratingStar(star)}
          onClick={() => onChange(star)}
        >
          ★
        </button>
      ))}
    </div>
  );
}
