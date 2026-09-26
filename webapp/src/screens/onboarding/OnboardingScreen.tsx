import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import type { OrganizationKind } from '../../api/types';
import { PageTitle } from '../../ui/blocks/Blocks';
import { SceneBanner } from '../../ui/SceneBanner';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StandaloneScreen } from './StandaloneScreen';
import { InvitationCodeSheet } from './InvitationCodeSheet';
import { ShowcaseEntry } from './ShowcaseEntry';
import './onboarding.css';

const ROLES: { kind: OrganizationKind; illustration: 'role-employee' | 'role-master' }[] = [
  { kind: 'customer', illustration: 'role-employee' },
  { kind: 'provider', illustration: 'role-master' },
];

const TITLE: Record<OrganizationKind, string> = {
  customer: strings.onboarding.roleCustomer,
  provider: strings.onboarding.roleProvider,
};

const HINT: Record<OrganizationKind, string> = {
  customer: strings.onboarding.roleCustomerHint,
  provider: strings.onboarding.roleProviderHint,
};

export function OnboardingScreen() {
  const navigate = useNavigate();
  const { memberships } = useSession();
  const [searchParams] = useSearchParams();
  const [kind, setKind] = useState<OrganizationKind | null>(null);
  const [invitationOpen, setInvitationOpen] = useState(searchParams.get('invite') === '1');
  const returning = memberships.length > 0;

  return (
    <StandaloneScreen
      title={strings.ui.appTitle}
      hideHeader={!returning}
      className={returning ? undefined : 'onb-noheader'}
      back={returning ? '/organizations' : false}
      actions={
        <BottomActions>
          <ActionButton
            disabled={!kind}
            onClick={() => kind && navigate(`/onboarding/new-organization/${kind}`)}
          >
            {strings.onboarding.continue}
          </ActionButton>
          <p className="onb-links">
            <span>
              {strings.onboarding.haveInvitation}{' '}
              <button type="button" className="onb-link" onClick={() => setInvitationOpen(true)}>
                {strings.onboarding.enterCode}
              </button>
            </span>
          </p>
        </BottomActions>
      }
    >
      <SceneBanner name="welcome-handshake" height={190} width={233} />
      <PageTitle as="h1" subtitle={strings.onboarding.subtitle}>
        {strings.onboarding.title}
      </PageTitle>
      <ChoiceGroup label={strings.onboarding.rolesLabel}>
        {ROLES.map((role) => (
          <ChoiceCard
            key={role.kind}
            title={TITLE[role.kind]}
            subtitle={HINT[role.kind]}
            illustration={role.illustration}
            selected={kind === role.kind}
            onSelect={() => setKind(role.kind)}
          />
        ))}
      </ChoiceGroup>
      <ShowcaseEntry />
      <InvitationCodeSheet open={invitationOpen} onClose={() => setInvitationOpen(false)} />
    </StandaloneScreen>
  );
}
