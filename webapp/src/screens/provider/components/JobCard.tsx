import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Illustration, type IllustrationName } from '../../../ui/illustrations';
import './workspace.css';

export type JobTagTone = 'x' | 'a' | 'ok' | 'y' | 'w';

export interface JobCardProps {
  to: string;
  art: IllustrationName;
  title: ReactNode;
  place?: ReactNode;
  tag?: { label: ReactNode; tone?: JobTagTone };
  text?: ReactNode;
  meta?: ReactNode;
}

export function JobCard({ to, art, title, place, tag, text, meta }: JobCardProps) {
  return (
    <Link className="pw-job" to={to}>
      <span className="pw-job__top">
        <Illustration name={art} width={56} className="pw-job__art" />
        <span className="pw-job__main">
          <span className="pw-job__title">{title}</span>
          {place && <span className="pw-job__place">{place}</span>}
        </span>
        {tag && (
          <span
            className={`pw-job__tag${tag.tone && tag.tone !== 'w' ? ` pw-job__tag--${tag.tone}` : ''}`}
          >
            {tag.label}
          </span>
        )}
      </span>
      {text && <span className="pw-job__text">{text}</span>}
      {meta && <span className="pw-job__meta">{meta}</span>}
    </Link>
  );
}

export function JobList({ children }: { children: ReactNode }) {
  return <div className="pw-jobs">{children}</div>;
}
