import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import type { OrganizationRedirectState } from '../../components/layout/RequireOrganization';
import { Avatar, Note, PageTitle } from '../../ui/blocks/Blocks';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { StandaloneScreen } from './StandaloneScreen';
import { InvitationCodeSheet } from './InvitationCodeSheet';
import { membershipSubtitle } from './membershipRow';
import { OnboardingScreen } from './OnboardingScreen';
import { ShowcaseEntry } from './ShowcaseEntry';
import './onboarding.css';

export function OrganizationPickerScreen() {
  const { memberships, activeMembership, selectOrganization } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as OrganizationRedirectState | null)?.from ?? '/';

  const selectable = memberships.filter((membership) => membership.status === 'active');
  const [selected, setSelected] = useState<string | null>(() =>
    activeMembership?.status === 'active'
      ? activeMembership.id
      : selectable.length === 1
        ? selectable[0]!.id
        : null,
  );
  const [invitationOpen, setInvitationOpen] = useState(false);

  if (memberships.length === 0) return <OnboardingScreen />;

  const organizationsCount = new Set(memberships.map((m) => m.organization.id)).size;

  const enter = () => {
    if (!selected) return;
    selectOrganization(selected);
    navigate(from, { replace: true });
  };

  return (
    <StandaloneScreen
      title={strings.orgPicker.title}
      hideHeader
      className="onb-noheader"
      actions={
        <BottomActions>
          <ActionButton disabled={!selected} onClick={enter}>
            {strings.orgPicker.enter}
          </ActionButton>
          <p className="onb-links">
            <button
              type="button"
              className="onb-link onb-link--600"
              onClick={() => navigate('/onboarding')}
            >
              {strings.orgPicker.createOrganization}
            </button>
            <button
              type="button"
              className="onb-link onb-link--600"
              onClick={() => setInvitationOpen(true)}
            >
              {strings.orgPicker.enterInvitation}
            </button>
          </p>
        </BottomActions>
      }
    >
      <PageTitle as="h1" subtitle={strings.orgPicker.count(organizationsCount)}>
        {strings.orgPicker.heading}
      </PageTitle>
      <ChoiceGroup label={strings.orgPicker.caption}>
        {memberships.map((membership) => {
          const pending = membership.status !== 'active';
          const on = selected === membership.id;
          return (
            <ChoiceCard
              key={membership.id}
              title={membership.organization.name}
              subtitle={
                pending
                  ? `${membershipSubtitle(membership)} · ${strings.orgPicker.pending}`
                  : membershipSubtitle(membership)
              }
              media={
                <Avatar
                  name={membership.organization.name}
                  size={48}
                  square
                  gradient={on ? 'a' : pending ? 'n' : 'o'}
                  aria-hidden
                />
              }
              selected={on}
              disabled={pending}
              onSelect={() => setSelected(membership.id)}
            />
          );
        })}
      </ChoiceGroup>
      <Note>{strings.orgPicker.switchNote}</Note>
      <ShowcaseEntry />
      <InvitationCodeSheet open={invitationOpen} onClose={() => setInvitationOpen(false)} />
    </StandaloneScreen>
  );
}
