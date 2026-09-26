import type { ReactNode } from 'react';
import { Illustration, type IllustrationName } from './illustrations';

export type HeroTone = 'n' | 'x' | 'ok' | 'a';

interface StatusHeroProps {
  icon?: ReactNode;
  illustration?: IllustrationName;
  illustrationWidth?: number;
  title: ReactNode;
  children?: ReactNode;
  tone?: HeroTone;
  top?: number;
  actions?: ReactNode;
  role?: 'alert' | 'status';
  as?: 'h1' | 'h2' | 'h3';
}

export function StatusHero({
  icon,
  illustration,
  illustrationWidth = 233,
  title,
  children,
  tone = 'n',
  top = 96,
  actions,
  role,
  as: Heading = 'h2',
}: StatusHeroProps) {
  const toneClass = tone === 'n' ? 'ui-hero__icon--n' : `ui-tone-${tone}`;
  return (
    <div className="ui-hero" style={{ paddingTop: top }} role={role}>
      {illustration ? (
        <Illustration name={illustration} width={illustrationWidth} className="ui-hero__art" />
      ) : icon !== undefined ? (
        <span className={`ui-hero__icon ${toneClass}`} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <Heading className="ui-hero__title">{title}</Heading>
      {children && <p className="ui-hero__text">{children}</p>}
      {actions && <div className="ui-hero__extra">{actions}</div>}
    </div>
  );
}
