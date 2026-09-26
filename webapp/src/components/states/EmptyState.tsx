import type { ReactNode } from 'react';
import { StatusHero, type HeroTone } from '../../ui/StatusHero';
import type { IllustrationName } from '../../ui/illustrations';

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  tone?: HeroTone;
  top?: number;
  illustration?: IllustrationName;
}

export function EmptyState({
  title,
  description,
  action,
  icon = '—',
  tone = 'n',
  top = 40,
  illustration,
}: EmptyStateProps) {
  return (
    <StatusHero icon={icon} illustration={illustration} title={title} tone={tone} top={top} actions={action}>
      {description}
    </StatusHero>
  );
}
