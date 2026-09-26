import { createContext, useContext } from 'react';
import type { Role } from '../../api/types';
import { isProvider } from '../../lib/roles';

export interface LayoutContextValue {
  inLayout: boolean;
  nested: boolean;
  parentPath: string;
  leave: (action: () => void) => Promise<void>;
  leaving: boolean;
  activeContext?: { organization: string; role: string };
  switchOrganization: () => void;
  registerScreen: () => () => void;
}

export const LayoutContext = createContext<LayoutContextValue>({
  inLayout: false,
  nested: false,
  parentPath: '/',
  leave: async (action) => action(),
  leaving: false,
  switchOrganization: () => {},
  registerScreen: () => () => {},
});

export function useLayout(): LayoutContextValue {
  return useContext(LayoutContext);
}

export type TabSide = 'customer' | 'provider';

export interface TabDef {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
  match?: string[];
  visible?: (role: Role) => boolean;
}

export function tabSide(role: Role | undefined): TabSide {
  return role && isProvider(role) ? 'provider' : 'customer';
}

export function homePath(side: TabSide): string {
  return side === 'provider' ? '/provider/incoming' : '/';
}

const CUSTOMER_TAB_PATHS = ['/', '/requests', '/equipment', '/organization'];
export const PROVIDER_REQUESTS_PATHS = [
  '/provider/requests',
  '/provider/incoming',
  '/provider/available',
  '/provider/in-work',
];

const PROVIDER_TAB_PATHS = [
  ...PROVIDER_REQUESTS_PATHS,
  '/provider/chats',
  '/provider/profile',
  '/integration',
];

export function isTabRoot(pathname: string, side: TabSide): boolean {
  return (side === 'provider' ? PROVIDER_TAB_PATHS : CUSTOMER_TAB_PATHS).includes(pathname);
}

export function parentPathOf(pathname: string, side: TabSide): string {
  const parts = pathname.split('/').filter(Boolean);
  const [first, second, third] = parts;
  const profile = side === 'provider' ? '/provider/profile' : '/organization';
  switch (first) {
    case 'requests':
      if (parts.length >= 3) return `/requests/${second}`;
      return '/requests';
    case 'equipment':
      if (parts.length >= 4) return `/equipment/${second}/${third}`;
      if (parts.length >= 3) return `/equipment/${second}`;
      return '/equipment';
    case 'locations':
      return parts.length >= 2 ? '/locations' : profile;
    case 'organization':
      if (!second) return profile;
      if (second === 'invite' || (second === 'staff' && parts.length > 2))
        return '/organization/staff';
      return '/organization';
    case 'providers':
      if (parts.length >= 3) return `/providers/${second}`;
      return parts.length >= 2 ? '/providers' : '/';
    case 'bindings':
      if (side === 'provider') return '/provider/profile';
      return parts.length >= 2 ? '/bindings' : '/organization';
    case 'operator':
      return parts.length >= 2 ? '/operator' : profile;
    case 'integration':
      return parts.length >= 2 ? '/integration' : profile;
    case 'complaints':
      return profile;
    case 'provider':
      if (second === 'available' && third) return '/provider/available';
      if (second === 'verification' || second === 'reviews') return '/provider/profile';
      if (second === 'profile' && third) return '/provider/profile';
      if (second === 'chats') return '/provider/chats';
      return '/provider/requests';
    default:
      return homePath(side);
  }
}
