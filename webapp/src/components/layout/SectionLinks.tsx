import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canAccessIntegration, isProvider } from '../../lib/roles';
import { useOperatorAccess } from '../../api/hooks/useOperatorAccess';
import { List, ListRow } from '../../ui/List';
import { SectionCaption } from '../../ui/blocks/Blocks';

export function SectionLinks({
  hideIntegration = false,
}: {
  hideIntegration?: boolean;
} = {}) {
  const { activeMembership } = useSession();
  const operatorAccess = useOperatorAccess();
  const role = activeMembership?.role;
  if (!role) return null;

  const rows: { to: string; label: string }[] = [];
  if (!hideIntegration && isProvider(role) && canAccessIntegration(role)) {
    rows.push({ to: '/integration', label: strings.ui.sections.integration });
  }
  if (operatorAccess.hasAccess) {
    rows.push({ to: '/operator', label: strings.ui.sections.operator });
  }
  if (rows.length === 0) return null;

  return (
    <section aria-label={strings.ui.sections.caption}>
      <SectionCaption>{strings.ui.sections.caption}</SectionCaption>
      <List>
        {rows.map((row) => (
          <ListRow key={row.to} title={row.label} to={row.to} chevron />
        ))}
      </List>
    </section>
  );
}
