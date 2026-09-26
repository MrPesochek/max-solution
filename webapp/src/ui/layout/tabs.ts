import { strings } from '../../strings/ru';
import { canAccessIntegration } from '../../lib/roles';
import { PROVIDER_REQUESTS_PATHS, type TabDef, type TabSide } from './layoutContext';

const ICON = {
  home: 'M4 10.5L12 4l8 6.5V20h-5.5v-5.5h-5V20H4z',
  list: 'M7 4h10a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 9h6M9 13h6M9 17h3',
  device:
    'M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM6 10h12M9 6.5v1M9 13v2',
  organization: 'M4 20V9l8-5 8 5v11M9 20v-6h6v6',
  person: 'M12 4a4 4 0 1 1 0 8a4 4 0 1 1 0-8zM4 21c1.5-4 4.5-6 8-6s6.5 2 8 6',
  chat: 'M4 6h16v10H9l-5 4z',
  code: 'M8 7L3 12l5 5M16 7l5 5-5 5',
};

export const TABS: Record<TabSide, TabDef[]> = {
  customer: [
    { to: '/', label: strings.nav.home, icon: ICON.home, end: true },
    { to: '/requests', label: strings.nav.requests, icon: ICON.list },
    { to: '/equipment', label: strings.nav.equipment, icon: ICON.device },
    { to: '/organization', label: strings.nav.organization, icon: ICON.organization },
  ],
  provider: [
    {
      to: '/provider/requests',
      label: strings.nav.providerRequests,
      icon: ICON.list,
      match: PROVIDER_REQUESTS_PATHS,
    },
    { to: '/provider/chats', label: strings.nav.chats, icon: ICON.chat },
    { to: '/provider/profile', label: strings.nav.providerProfile, icon: ICON.person },
    { to: '/integration', label: strings.nav.crm, icon: ICON.code, visible: canAccessIntegration },
  ],
};
