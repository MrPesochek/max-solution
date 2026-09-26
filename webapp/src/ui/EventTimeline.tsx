import { useId, useState, type ReactNode } from 'react';
import { strings } from '../strings/ru';

export interface TimelineEvent {
  id?: string;
  title: ReactNode;
  sub?: ReactNode;
  time?: ReactNode;
  tone?: 'accent' | 'danger' | 'neutral';
}

interface EventTimelineProps {
  events: TimelineEvent[];
  variant?: 'dot' | 'date';
  title?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  className?: string;
}

export function EventTimeline({
  events,
  variant = 'dot',
  title,
  collapsible,
  defaultOpen = false,
  className,
}: EventTimelineProps) {
  const [open, setOpen] = useState(defaultOpen || !collapsible);
  const listId = useId();

  const list = open ? (
    <ol id={listId} className={`ui-timeline ui-timeline--${variant}`}>
      {events.map((event, index) => (
        <li key={event.id ?? index} className="ui-timeline__item">
          {variant === 'dot' ? (
            <span className={`ui-timeline__dot ui-timeline__dot--${event.tone ?? 'neutral'}`} aria-hidden="true" />
          ) : (
            <span className="ui-timeline__date">{event.time}</span>
          )}
          <span className="ui-timeline__main">
            <span className="ui-timeline__title">{event.title}</span>
            {event.sub && <span className="ui-timeline__sub">{event.sub}</span>}
          </span>
          {variant === 'dot' && event.time && <span className="ui-timeline__time">{event.time}</span>}
        </li>
      ))}
    </ol>
  ) : null;

  if (!title && !collapsible) return <div className={className}>{list}</div>;

  return (
    <section className={['ui-timeline-block', className].filter(Boolean).join(' ')}>
      {collapsible ? (
        <button
          type="button"
          className="ui-timeline-block__head"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="ui-timeline-block__title">{title ?? strings.ui.history}</span>
          <span className="ui-timeline-block__toggle">{open ? strings.ui.hide : strings.ui.show}</span>
        </button>
      ) : (
        <h3 className="ui-timeline-block__title">{title}</h3>
      )}
      {list}
    </section>
  );
}
