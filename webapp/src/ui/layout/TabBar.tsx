import type { CSSProperties } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { Role } from '../../api/types';
import { strings } from '../../strings/ru';
import type { TabDef, TabSide } from './layoutContext';
import { TABS } from './tabs';

interface TabBarProps {
  side: TabSide;
  badges?: Partial<Record<string, number>>;
  activeTo?: string;
  role?: Role;
}

function isActive(tab: TabDef, pathname: string): boolean {
  if (tab.match?.includes(pathname)) return true;
  if (tab.end) return pathname === tab.to;
  return pathname === tab.to || pathname.startsWith(`${tab.to}/`);
}

export function TabBar({ side, badges, activeTo, role }: TabBarProps) {
  const { pathname } = useLocation();
  const items = TABS[side].filter(
    (tab) => !tab.visible || (role !== undefined && tab.visible(role)),
  );
  return (
    <nav
      className="ui-tabbar"
      aria-label={strings.nav.mainLabel}
      style={{ '--ui-tab-count': items.length } as CSSProperties}
    >
      {items.map((tab) => {
        const badge = badges?.[tab.to];
        const content = (
          <>
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d={tab.icon} />
            </svg>
            <span className="ui-tabbar__label">{tab.label}</span>
            {badge ? (
              <>
                <span className="ui-tabbar__badge" aria-hidden="true">
                  {badge > 99 ? '99+' : badge}
                </span>
                {/* Кружок со счётчиком — только картинка; диктору — «N новых» после подписи. */}
                <span className="ui-visually-hidden">{`, ${strings.ui.tabBadge(badge)}`}</span>
              </>
            ) : null}
          </>
        );
        const active = activeTo !== undefined ? tab.to === activeTo : isActive(tab, pathname);
        return (
          <Link
            key={tab.to}
            to={tab.to}
            className="ui-tabbar__item"
            aria-current={active ? 'page' : undefined}
          >
            {content}
          </Link>
        );
      })}
    </nav>
  );
}
