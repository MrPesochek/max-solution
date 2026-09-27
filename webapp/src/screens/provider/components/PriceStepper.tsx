import { useState } from 'react';
import { strings } from '../../../strings/ru';
import './workspace.css';

const STEP_RUB = 100;
const MIN_RUB = 100;
const MAX_RUB = 1_000_000;

function parseRub(value: string): number {
  const rub = Number.parseFloat(value.replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(rub) ? rub : 0;
}

export function PriceStepper({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const rub = parseRub(value);
  const set = (next: number) => onChange(String(Math.min(MAX_RUB, Math.max(MIN_RUB, next))));
  return (
    <div className="pw-stepper">
      <button
        type="button"
        className="pw-stepper__btn"
        aria-label={strings.workspace.priceDecrease}
        disabled={rub <= MIN_RUB}
        onClick={() => set(Math.ceil(rub / STEP_RUB) * STEP_RUB - STEP_RUB)}
      >
        −
      </button>
      <input
        id={id}
        className="pw-stepper__value"
        aria-label={label}
        inputMode="decimal"
        value={!editing && rub > 0 ? `${rub.toLocaleString('ru-RU')} ₽` : value}
        onFocus={() => setEditing(true)}
        onBlur={() => setEditing(false)}
        placeholder={strings.workspace.priceAmountPlaceholder}
        onChange={(event) => onChange(event.target.value.replace(/[^\d,.]/g, ''))}
      />
      <button
        type="button"
        className="pw-stepper__btn"
        aria-label={strings.workspace.priceIncrease}
        disabled={rub >= MAX_RUB}
        onClick={() => set(Math.floor(rub / STEP_RUB) * STEP_RUB + STEP_RUB)}
      >
        +
      </button>
    </div>
  );
}
