import type { ReactNode } from 'react';
import { strings } from '../strings/ru';

export type StepState = 'done' | 'current' | 'todo' | 'attention';

export interface StepItem {
  id?: string;
  label: ReactNode;
  sub?: ReactNode;
  time?: ReactNode;
  state: StepState;
}

interface StepperProps {
  steps: StepItem[];
  variant?: 'marks' | 'dots';
  'aria-label'?: string;
  className?: string;
}

const PATH: Record<StepState, string> = {
  done: 'M5 12.5l4.5 4.5L19 7.5',
  current: '',
  todo: '',
  attention: 'M12 7v6M12 17v.5',
};

export function Stepper({ steps, variant = 'marks', 'aria-label': ariaLabel, className }: StepperProps) {
  const withSub = steps.some((step) => step.sub);
  return (
    <ol
      className={['ui-steps', `ui-steps--${variant}`, withSub && 'ui-steps--sub', className].filter(Boolean).join(' ')}
      aria-label={ariaLabel}
    >
      {steps.map((step, index) => (
        <li
          key={step.id ?? index}
          className={`ui-steps__item ui-steps__item--${step.state}`}
          aria-current={step.state === 'current' ? 'step' : undefined}
        >
          <span className="ui-steps__mark" aria-hidden="true">
            {variant === 'marks' && PATH[step.state] && (
              <svg viewBox="0 0 24 24" fill="none">
                <path
                  d={PATH[step.state]}
                  stroke="currentColor"
                  strokeWidth={step.state === 'done' ? 3.4 : 2.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </span>
          <span className="ui-steps__main">
            <span className="ui-steps__label">{step.label}</span>
            {step.sub && <span className="ui-steps__sub">{step.sub}</span>}
            <span className="ui-visually-hidden">, {strings.ui.stepState[step.state]}</span>
          </span>
          {step.time && <span className="ui-steps__time">{step.time}</span>}
        </li>
      ))}
    </ol>
  );
}

export function StepProgress({ current, total }: { current: number; total: number }) {
  return (
    <div
      className="ui-progress"
      role="progressbar"
      aria-label={strings.ui.stepOf(current, total)}
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={current}
      aria-valuetext={strings.ui.stepOf(current, total)}
    >
      {Array.from({ length: total }, (_, index) => (
        <span key={index} className={`ui-progress__seg${index < current ? ' ui-progress__seg--on' : ''}`} />
      ))}
    </div>
  );
}
