import { strings } from '../../strings/ru';
import { StatusHero } from '../../ui/StatusHero';

export function NoAccessState({ description, title }: { description?: string; title?: string } = {}) {
  return (
    <StatusHero icon="—" illustration="profile-missing" illustrationWidth={188} title={title ?? strings.states.noAccess} top={48}>
      {description ?? strings.states.noAccessDescription}
    </StatusHero>
  );
}
