import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { authWithLink, authWithMax, fetchMe, logout as apiLogout } from '../api/auth';
import { setContextLostHandler, setReauthHandler, clearSession } from '../api/client';
import { ApiError } from '../api/errors';
import { getActiveMembershipId, readStoredContext, setActiveContext } from '../api/orgStore';
import { setToken } from '../api/tokenStore';
import { queryClient } from '../api/queryClient';
import type { CurrentUser, Membership, OrganizationRef } from '../api/types';
import { getInitData, isBridgeAvailable, onBridgeReady, reloadMaxBridge } from '../max/bridge';
import { parseStartParam, startParamToPath } from '../max/startParam';
import { rememberOpenedViaLink, takeLoginLinkToken, wasOpenedViaLink } from './loginLink';
import { strings } from '../strings/ru';

type SessionStatus =
  | 'loading'
  | 'authenticated'
  | 'no_organization'
  | 'demo_login'
  | 'reopen_required'
  | 'login_error'
  | 'link_invalid';

const demoLoginEnabled = () => import.meta.env.VITE_DEMO_LOGIN === 'true';

interface SessionContextValue {
  status: SessionStatus;
  user: CurrentUser | null;
  memberships: Membership[];
  organizations: OrganizationRef[];
  activeMembership: Membership | null;
  isDemoLoginEnabled: boolean;
  openedViaLink: boolean;
  selectOrganization: (membershipId: string) => void;
  activateMembership: (membership: Membership) => void;
  clearActiveOrganization: () => void;
  refreshMemberships: () => Promise<void>;
  loginDemo: (userKey: string) => Promise<void>;
  retryLogin: () => void;
  logout: () => Promise<void>;
  loginErrorMessage: string | null;
}

const SessionContext = createContext<SessionContextValue | null>(null);

function pickActiveMembership(memberships: Membership[]): Membership | null {
  const active = memberships.filter((m) => m.status === 'active');
  const stored = readStoredContext();
  const storedMembershipId = stored.membershipId ?? getActiveMembershipId();
  if (storedMembershipId) {
    const found = active.find((m) => m.id === storedMembershipId);
    if (found) return found;
  }
  if (stored.organizationId) {
    const inOrg = active.filter((m) => m.organization.id === stored.organizationId);
    if (inOrg.length === 1) return inOrg[0] ?? null;
  }
  return active.length === 1 ? (active[0] ?? null) : null;
}

function isRetryableLoginError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.isNetworkError || error.isRateLimited || error.status >= 500;
}

function contextOf(membership: Membership | null) {
  return membership ? { membershipId: membership.id, organizationId: membership.organization.id } : null;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationRef[]>([]);
  const [activeMembership, setActiveMembershipState] = useState<Membership | null>(null);
  const [loginErrorMessage, setLoginErrorMessage] = useState<string | null>(null);
  const bootstrapped = useRef(false);
  const statusRef = useRef<SessionStatus>(status);
  statusRef.current = status;
  const [openedViaLink, setOpenedViaLink] = useState(wasOpenedViaLink);
  const linkToken = useRef<string | null>(null);

  const lastUserId = useRef<string | null>(null);

  const applyAuthResult = useCallback(
    (nextUser: CurrentUser, nextMemberships: Membership[], nextOrganizations: OrganizationRef[]) => {
      if (lastUserId.current !== null && lastUserId.current !== nextUser.id) queryClient.clear();
      lastUserId.current = nextUser.id;
      setUser(nextUser);
      setMemberships(nextMemberships);
      setOrganizations(nextOrganizations);
      const active = pickActiveMembership(nextMemberships);
      setActiveMembershipState(active);
      if (active) setActiveContext(contextOf(active));
      setStatus(active ? 'authenticated' : 'no_organization');
    },
    [],
  );

  const reopenRequired = useRef(false);

  const requireReopen = useCallback(() => {
    reopenRequired.current = true;
    clearSession();
    setLoginErrorMessage(null);
    setStatus('reopen_required');
  }, []);

  const attemptMaxLogin = useCallback(
    async (initData: string): Promise<'ok' | 'reopen'> => {
      try {
        const result = await authWithMax(initData);
        setToken(result.token);
        applyAuthResult(result.user, result.memberships, result.organizations);
        return 'ok';
      } catch (error) {
        if (isRetryableLoginError(error)) throw error;
        return 'reopen';
      }
    },
    [applyAuthResult],
  );

  const runInitialLogin = useCallback(
    async (initData: string) => {
      try {
        if ((await attemptMaxLogin(initData)) === 'reopen') requireReopen();
      } catch {
        setLoginErrorMessage(strings.session.loginRetryableError);
        setStatus('login_error');
      }
    },
    [attemptMaxLogin, requireReopen],
  );

  const runLinkLogin = useCallback(
    async (token: string) => {
      linkToken.current = token;
      try {
        const result = await authWithLink(token);
        linkToken.current = null;
        setToken(result.token);
        const path = startParamToPath(parseStartParam(result.target));
        window.history.replaceState(window.history.state, '', `#${path ?? '/'}`);
        applyAuthResult(result.user, result.memberships, result.organizations);
      } catch (error) {
        if (isRetryableLoginError(error)) {
          setLoginErrorMessage(strings.session.loginRetryableError);
          setStatus('login_error');
          return;
        }
        linkToken.current = null;
        setStatus('link_invalid');
      }
    },
    [applyAuthResult],
  );

  const reauth = useCallback(async (): Promise<boolean> => {
    const initData = getInitData();
    if (!initData || reopenRequired.current) {
      if (!initData && openedViaLink) requireReopen();
      return false;
    }
    if ((await attemptMaxLogin(initData)) === 'ok') return true;
    requireReopen();
    return false;
  }, [attemptMaxLogin, requireReopen, openedViaLink]);

  useEffect(() => {
    setReauthHandler(reauth);
    return () => setReauthHandler(null);
  }, [reauth]);

  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;

    const initData = getInitData();
    if (initData) {
      void runInitialLogin(initData);
      return;
    }

    const token = takeLoginLinkToken();
    if (token) {
      rememberOpenedViaLink();
      setOpenedViaLink(true);
      void runLinkLogin(token);
      return;
    }

    if (wasOpenedViaLink()) {
      setStatus('reopen_required');
      return;
    }

    if (demoLoginEnabled()) {
      setStatus('demo_login');
      return;
    }

    setStatus(isBridgeAvailable() ? 'reopen_required' : 'demo_login');
  }, [runInitialLogin, runLinkLogin]);

  useEffect(
    () =>
      onBridgeReady(() => {
        const initData = getInitData();
        if (!initData || reopenRequired.current || linkToken.current) return;
        if (statusRef.current !== 'demo_login') return;
        statusRef.current = 'loading';
        setLoginErrorMessage(null);
        setStatus('loading');
        void runInitialLogin(initData);
      }),
    [runInitialLogin],
  );

  const selectOrganization = useCallback(
    (membershipId: string) => {
      const found = memberships.find((m) => m.id === membershipId);
      if (!found || found.status !== 'active') return;
      setActiveMembershipState(found);
      setActiveContext(contextOf(found));
      setStatus('authenticated');
    },
    [memberships],
  );

  const activateMembership = useCallback((membership: Membership) => {
    if (membership.status !== 'active') return;
    setMemberships((prev) => [...prev.filter((m) => m.id !== membership.id), membership]);
    setActiveMembershipState(membership);
    setActiveContext(contextOf(membership));
    setStatus('authenticated');
  }, []);

  const clearActiveOrganization = useCallback(() => {
    setActiveMembershipState(null);
    setActiveContext(null);
    setStatus('no_organization');
  }, []);

  useEffect(() => {
    setContextLostHandler(clearActiveOrganization);
    return () => setContextLostHandler(null);
  }, [clearActiveOrganization]);

  const refreshMemberships = useCallback(async () => {
    const me = await fetchMe();
    setUser(me.user);
    setMemberships(me.memberships);
    setOrganizations(me.organizations);
    if (activeMembership) {
      const stillThere = me.memberships.find((m) => m.id === activeMembership.id && m.status === 'active');
      setActiveMembershipState(stillThere ?? null);
      setActiveContext(contextOf(stillThere ?? null));
      setStatus(stillThere ? 'authenticated' : 'no_organization');
    } else {
      const active = pickActiveMembership(me.memberships);
      setActiveMembershipState(active);
      if (active) {
        setActiveContext(contextOf(active));
        setStatus('authenticated');
      }
    }
  }, [activeMembership]);

  const loginDemo = useCallback(
    async (userKey: string) => {
      if (import.meta.env.VITE_DEMO_LOGIN !== 'true') return;
      setLoginErrorMessage(null);
      try {
        const { authDemo } = await import('../api/demoAuth');
        const result = await authDemo(userKey);
        setToken(result.token);
        applyAuthResult(result.user, result.memberships, result.organizations);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          setLoginErrorMessage(strings.errorCodes.DEMO_LOGIN_DISABLED);
          return;
        }
        setLoginErrorMessage(
          error instanceof ApiError ? error.message : 'Не удалось выполнить демо-вход',
        );
      }
    },
    [applyAuthResult],
  );

  const retryLogin = useCallback(() => {
    const initData = getInitData();
    setLoginErrorMessage(null);
    if (!initData && linkToken.current) {
      setStatus('loading');
      void runLinkLogin(linkToken.current);
      return;
    }
    if (!initData && !reopenRequired.current && !openedViaLink && statusRef.current === 'demo_login') {
      statusRef.current = 'loading';
      setStatus('loading');
      void reloadMaxBridge().then(() => {
        const loaded = getInitData();
        if (loaded) void runInitialLogin(loaded);
        else setStatus('demo_login');
      });
      return;
    }
    if (!initData || reopenRequired.current) {
      setStatus(demoLoginEnabled() && !openedViaLink ? 'demo_login' : 'reopen_required');
      return;
    }
    setStatus('loading');
    void runInitialLogin(initData);
  }, [runInitialLogin, runLinkLogin, openedViaLink]);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // сессия всё равно очищается локально
    }
    clearSession();
    setActiveContext(null);
    setUser(null);
    setMemberships([]);
    setOrganizations([]);
    setActiveMembershipState(null);
    setStatus(demoLoginEnabled() && !openedViaLink ? 'demo_login' : 'reopen_required');
  }, [openedViaLink]);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      user,
      memberships,
      organizations,
      activeMembership,
      isDemoLoginEnabled: demoLoginEnabled(),
      openedViaLink,
      selectOrganization,
      activateMembership,
      clearActiveOrganization,
      refreshMemberships,
      loginDemo,
      retryLogin,
      logout,
      loginErrorMessage,
    }),
    [
      status,
      user,
      memberships,
      organizations,
      activeMembership,
      openedViaLink,
      selectOrganization,
      activateMembership,
      clearActiveOrganization,
      refreshMemberships,
      loginDemo,
      retryLogin,
      logout,
      loginErrorMessage,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession используется вне SessionProvider');
  return ctx;
}
