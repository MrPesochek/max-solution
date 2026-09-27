import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canManageProviderProfile } from '../../lib/roles';
import { canToggleAccepting } from '../../lib/trust';
import { useProviderIncoming, useProviderInWork } from '../../api/hooks/useProviderRequests';
import { useMarketplaceHasMore, useMarketplaceList } from '../../api/hooks/useMarketplace';
import { useProviderProfile, useSetAcceptingNewRequests } from '../../api/hooks/useProviderProfile';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Screen } from '../../ui/layout/Screen';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { SegmentTabs } from '../../ui/Segmented';
import { Toggle } from '../../ui/Toggle';
import { WorkspaceHeader } from '../../ui/WorkspaceHeader';
import { IncomingList } from './hub/IncomingList';
import { AvailableList } from './hub/AvailableList';
import { InWorkList } from './hub/InWorkList';

export type HubTab = 'incoming' | 'available' | 'in-work';

const TAB_PATH: Record<HubTab, string> = {
  incoming: '/provider/incoming',
  available: '/provider/available',
  'in-work': '/provider/in-work',
};

const TAB_LABEL: Record<HubTab, string> = {
  incoming: strings.nav.incoming,
  available: strings.nav.availableRequests,
  'in-work': strings.nav.inWork,
};

const TABS: HubTab[] = ['incoming', 'available', 'in-work'];

function tabOf(pathname: string): HubTab | null {
  return TABS.find((tab) => TAB_PATH[tab] === pathname) ?? null;
}

let lastTab: HubTab = 'incoming';

export function ProviderRequestsHubScreen({ tab: forced }: { tab?: HubTab }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const tab = forced ?? tabOf(pathname) ?? lastTab;
  useEffect(() => {
    lastTab = tab;
  }, [tab]);

  const incoming = useProviderIncoming();
  const inWork = useProviderInWork();
  const available = useMarketplaceList();
  const availableMore = useMarketplaceHasMore();
  const profile = useProviderProfile();
  const setAccepting = useSetAcceptingNewRequests();
  const [error, setError] = useState<string | null>(null);

  if (!activeMembership) return null;
  const w = strings.workspace;
  const isAdmin = canManageProviderProfile(activeMembership.role);
  const accepting = profile.data?.accepting_new_requests ?? false;
  const toggleable = isAdmin && Boolean(profile.data && canToggleAccepting(profile.data.status));
  const paused = profile.isSuccess && profile.data.status === 'active' && !accepting;

  const counts: Record<HubTab, number> = {
    incoming: incoming.data?.length ?? 0,
    available: available.data?.length ?? 0,
    'in-work': inWork.data?.length ?? 0,
  };
  const more: Record<HubTab, boolean> = {
    incoming: incoming.hasNextPage,
    available: availableMore,
    'in-work': inWork.hasNextPage,
  };

  const toggle = async (next: boolean) => {
    setError(null);
    try {
      await setAccepting.mutateAsync(next);
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <Screen title={strings.ui.appTitle}>
      <WorkspaceHeader
        eyebrow={activeMembership.organization.name}
        title={w.hubTitle}
        side={
          profile.isSuccess ? (
            <Toggle
              pill
              checked={accepting}
              aria-label={strings.provider.acceptingLabel}
              disabled={!toggleable || setAccepting.isPending}
              onChange={(next) => void toggle(next)}
            >
              {accepting ? w.acceptingOn : w.acceptingPaused}
            </Toggle>
          ) : undefined
        }
      />
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      <SegmentTabs<HubTab>
        label={w.hubSegmentsLabel}
        idPrefix="provider-hub"
        items={TABS.map((id) => ({
          id,
          label: TAB_LABEL[id],
          count: id === tab ? undefined : counts[id] || undefined,
          countMore: more[id],
        }))}
        value={tab}
        onChange={(next) => navigate(TAB_PATH[next], { replace: true })}
      />

      {paused && tab !== 'in-work' && (
        <Banner tone="y" title={w.pausedNoteTitle}>
          {w.pausedNoteText}
        </Banner>
      )}

      <div id="provider-hub-panel" role="tabpanel" aria-labelledby={`provider-hub-${tab}`}>
        {tab === 'incoming' && <IncomingList query={incoming} paused={paused} />}
        {tab === 'available' && <AvailableList query={available} profile={profile} />}
        {tab === 'in-work' && <InWorkList query={inWork} />}
      </div>
    </Screen>
  );
}
