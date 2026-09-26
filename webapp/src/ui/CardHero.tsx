import type { ReactNode } from 'react';
import type { IllustrationName } from './illustrations';
import { SceneBanner } from './SceneBanner';

export interface HeroContent {
  scene: IllustrationName;
  title: ReactNode;
  accent?: ReactNode;
  text?: ReactNode;
  note?: ReactNode;
}

export function CardHero({
  scene,
  title,
  accent,
  text,
  note,
  size = 'l',
}: HeroContent & { size?: 'xl' | 'l' | 'm' }) {
  const height = size === 'l' ? 140 : 150;
  return (
    <>
      <SceneBanner name={scene} height={height} width={size === 'l' ? 175 : 188} />
      <div className={`ui-card-hero ui-card-hero--${size}`}>
        <h2 className="ui-card-hero__title">{title}</h2>
        {accent && <span className="ui-card-hero__accent">{accent}</span>}
        {text && <p className="ui-card-hero__text">{text}</p>}
        {note && (
          <span className="ui-card-hero__note" role="status">
            {note}
          </span>
        )}
      </div>
    </>
  );
}
