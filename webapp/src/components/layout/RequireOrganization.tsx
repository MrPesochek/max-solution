import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useSession } from '../../session/SessionContext';

export interface OrganizationRedirectState {
  from?: string;
}

export function RequireOrganization({ children }: { children: ReactNode }) {
  const { activeMembership } = useSession();
  const location = useLocation();
  if (!activeMembership) {
    const from = `${location.pathname}${location.search}`;
    const state: OrganizationRedirectState | undefined = from === '/' ? undefined : { from };
    return <Navigate to="/organizations" replace state={state} />;
  }
  return <>{children}</>;
}
