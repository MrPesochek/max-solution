import { useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { membershipLabel } from '../../lib/membership';
import { SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { useLayout } from '../../ui/layout/layoutContext';
import { initials } from '../../ui/format';
import { membershipSubtitle, organizationGradient } from '../onboarding/membershipRow';

export function MembershipSwitchList() {
  const { memberships, activeMembership, selectOrganization } = useSession();
  const navigate = useNavigate();
  const layout = useLayout();
  const others = memberships.filter((m) => m.status === 'active' && m.id !== activeMembership?.id);
  if (!activeMembership || others.length === 0) return null;

  return (
    <section aria-labelledby="org-switch-caption">
      <SectionCaption id="org-switch-caption">{strings.orgPicker.switchTitle}</SectionCaption>
      <List>
        {others.map((membership) => (
          <ListRow
            key={membership.id}
            title={membership.organization.name}
            subtitle={membershipSubtitle(membership)}
            icon={initials(membership.organization.name)}
            gradient={organizationGradient(membership.organization.id)}
            aria-label={strings.orgPicker.switchTo(membershipLabel(membership))}
            chevron
            disabled={layout.leaving}
            onClick={() =>
              void layout.leave(() => {
                selectOrganization(membership.id);
                navigate('/', { replace: true });
              })
            }
          />
        ))}
      </List>
    </section>
  );
}
