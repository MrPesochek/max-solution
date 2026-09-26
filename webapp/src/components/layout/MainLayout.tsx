import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import { FlowNavigationProvider, useFlowNavigation } from './FlowNavigation';
import { OfflineBanner } from '../OfflineBanner';
import { useSession } from '../../session/SessionContext';
import { strings } from '../../strings/ru';
import {
  LayoutContext,
  isTabRoot,
  parentPathOf,
  tabSide,
  type LayoutContextValue,
} from '../../ui/layout/layoutContext';
import { ScreenHeader } from '../../ui/layout/Screen';
import { TabBar } from '../../ui/layout/TabBar';

function useScrollMemory(key: string, navigationType: string) {
  const positions = useRef(new Map<string, number>());
  const current = useRef(key);
  useLayoutEffect(() => {
    const onScroll = () => positions.current.set(current.current, window.scrollY);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  useLayoutEffect(() => {
    current.current = key;
    const saved = navigationType === 'POP' ? positions.current.get(key) : undefined;
    (document.scrollingElement ?? document.documentElement).scrollTop = saved ?? 0;
  }, [key, navigationType]);
}

function LayoutShell() {
  const { activeMembership, clearActiveOrganization } = useSession();
  const location = useLocation();
  const { pathname } = location;
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  useScrollMemory(location.key, navigationType);
  const beforeExit = useFlowNavigation();
  const [leaving, setLeaving] = useState(false);
  const leavingRef = useRef(false);
  const [screens, setScreens] = useState(0);

  const side = tabSide(activeMembership?.role);
  const tabRoot = isTabRoot(pathname, side);

  const leave = useCallback(
    async (action: () => void) => {
      if (leavingRef.current) return;
      leavingRef.current = true;
      setLeaving(true);
      try {
        if (await beforeExit()) action();
      } finally {
        leavingRef.current = false;
        setLeaving(false);
      }
    },
    [beforeExit],
  );

  const switchOrganization = useCallback(() => {
    void leave(() => {
      clearActiveOrganization();
      navigate('/organizations');
    });
  }, [leave, clearActiveOrganization, navigate]);

  const registerScreen = useCallback(() => {
    setScreens((count) => count + 1);
    return () => setScreens((count) => count - 1);
  }, []);

  const value = useMemo<LayoutContextValue>(
    () => ({
      inLayout: true,
      nested: !tabRoot,
      parentPath: parentPathOf(pathname, side),
      leave,
      leaving,
      activeContext: activeMembership
        ? {
            organization: activeMembership.organization.name,
            role: strings.roles[activeMembership.role],
          }
        : undefined,
      switchOrganization,
      registerScreen,
    }),
    [tabRoot, pathname, side, leave, leaving, activeMembership, switchOrganization, registerScreen],
  );

  if (!activeMembership) return null;
  const legacy = screens === 0;

  return (
    <LayoutContext.Provider value={value}>
      <div className="ui-layout" data-tabbar={tabRoot} data-chrome={legacy ? 'legacy' : 'screen'}>
        <OfflineBanner />
        {legacy && <ScreenHeader title={strings.ui.appTitle} />}
        <main className="ui-layout__main">
          <Outlet />
        </main>
        {tabRoot && <TabBar side={side} role={activeMembership.role} />}
      </div>
    </LayoutContext.Provider>
  );
}

export function MainLayout() {
  return (
    <FlowNavigationProvider>
      <LayoutShell />
    </FlowNavigationProvider>
  );
}
