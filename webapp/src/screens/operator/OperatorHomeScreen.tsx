import { strings } from '../../strings/ru';
import { SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { OperatorScreen } from './OperatorScreen';

const QUEUES = [
  {
    to: '/operator/verification',
    title: strings.operator.verificationQueueTitle,
    icon: 'П',
    gradient: 'b',
  },
  {
    to: '/operator/providers',
    title: strings.operator.providerProfilesTitle,
    icon: 'И',
    gradient: 'g',
  },
  {
    to: '/operator/warranty',
    title: strings.operator.warrantyQueueTitle,
    icon: 'Г',
    gradient: 'o',
  },
  {
    to: '/operator/bindings',
    title: strings.operator.bindingsQueueTitle,
    icon: 'С',
    gradient: 'p',
  },
  {
    to: '/operator/attachments',
    title: strings.operator.attachmentsQueueTitle,
    icon: 'Ф',
    gradient: 'r',
  },
  { to: '/operator/reviews', title: strings.operator.reviewsQueueTitle, icon: 'О', gradient: 'a' },
  { to: '/operator/complaints', title: strings.operator.casesQueueTitle, icon: 'Ж', gradient: 'n' },
] as const;

export function OperatorHomeScreen() {
  return (
    <OperatorScreen title={strings.operator.homeTitle} subtitle={strings.operator.homeSubtitle}>
      <SectionCaption>{strings.operator.queuesCaption}</SectionCaption>
      <List>
        {QUEUES.map((queue) => (
          <ListRow
            key={queue.to}
            title={queue.title}
            icon={queue.icon}
            gradient={queue.gradient}
            to={queue.to}
            chevron
          />
        ))}
      </List>
    </OperatorScreen>
  );
}
