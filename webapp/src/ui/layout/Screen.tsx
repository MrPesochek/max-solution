import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { haptics, isBridgeAvailable } from '../../max/bridge';
import { useLayout } from './layoutContext';
import { registerBack } from './backStack';
import { useUnsavedGuard } from './unsavedGuard';
import { Sheet } from '../Sheet';
import { List, ListRow } from '../List';

export interface HeaderMenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

export interface ScreenHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  back?: string | (() => void) | false;
  onClose?: () => void;
  menu?: HeaderMenuItem[];
}

function BackIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M15 5l-7 7 7 7"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5" cy="12" r="1.8" />
      <circle cx="12" cy="12" r="1.8" />
      <circle cx="19" cy="12" r="1.8" />
    </svg>
  );
}

function isAppTitle(title: ReactNode): boolean {
  return title === strings.ui.appTitle;
}

export function ScreenHeader({ title, subtitle, back, onClose, menu = [] }: ScreenHeaderProps) {
  const layout = useLayout();
  const navigate = useNavigate();
  const unsaved = useUnsavedGuard();
  const [menuOpen, setMenuOpen] = useState(false);
  const inMax = isBridgeAvailable();

  const backTarget =
    back === false
      ? null
      : typeof back === 'function'
        ? back
        : typeof back === 'string'
          ? back
          : layout.inLayout && layout.nested
            ? layout.parentPath
            : null;

  const goBack = () => {
    if (backTarget === null) return;
    haptics.impact('light');
    void unsaved.confirmLeave().then((ok) => {
      if (!ok) return;
      if (typeof backTarget === 'function') {
        backTarget();
        return;
      }
      void layout.leave(() => navigate(backTarget));
    });
  };

  const backRef = useRef(goBack);
  backRef.current = goBack;
  const hasBack = backTarget !== null;
  useEffect(() => {
    if (!hasBack) return;
    return registerBack('screen', () => backRef.current());
  }, [hasBack]);

  const menuItems: HeaderMenuItem[] = [
    ...menu,
    ...(layout.inLayout
      ? [{ label: strings.header.switchOrganization, onSelect: layout.switchOrganization }]
      : []),
  ];

  const tabRoot = layout.inLayout && !layout.nested;
  if (inMax && !hasBack && menu.length === 0 && (tabRoot || isAppTitle(title))) {
    return <div className="ui-header ui-header--bare" aria-hidden="true" />;
  }

  let left: ReactNode = <span className="ui-header__side" aria-hidden="true" />;
  if (!inMax && backTarget !== null) {
    left =
      typeof backTarget === 'string' ? (
        <Link
          className="ui-header__side ui-header__back"
          to={backTarget}
          aria-label={strings.ui.back}
          aria-disabled={layout.leaving || undefined}
          onClick={(event) => {
            event.preventDefault();
            goBack();
          }}
        >
          <BackIcon />
        </Link>
      ) : (
        <button
          type="button"
          className="ui-header__side ui-header__back"
          aria-label={strings.ui.back}
          onClick={goBack}
        >
          <BackIcon />
        </button>
      );
  } else if (!inMax && onClose) {
    left = (
      <button
        type="button"
        className="ui-header__side ui-header__close"
        aria-label={strings.ui.close}
        onClick={onClose}
      >
        <span aria-hidden="true">✕</span>
      </button>
    );
  }

  const right: ReactNode =
    menuItems.length > 0 ? (
      <button
        type="button"
        className="ui-header__side ui-header__more"
        aria-label={strings.ui.menu}
        aria-haspopup="dialog"
        aria-expanded={menuOpen}
        disabled={layout.leaving}
        onClick={() => setMenuOpen(true)}
      >
        <MoreIcon />
      </button>
    ) : (
      <span className="ui-header__side" aria-hidden="true" />
    );

  return (
    <HeaderBar left={left} title={title} subtitle={subtitle} right={right}>
      <Sheet
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        title={layout.activeContext?.organization ?? strings.ui.menuTitle}
        description={layout.activeContext?.role}
      >
        <List>
          {menuItems.map((item) => (
            <ListRow
              key={item.label}
              title={item.label}
              action={item.danger ? 'danger' : 'accent'}
              onClick={() => {
                setMenuOpen(false);
                item.onSelect();
              }}
            />
          ))}
        </List>
      </Sheet>
    </HeaderBar>
  );
}

export function HeaderBar({
  left,
  title,
  subtitle,
  right,
  children,
}: {
  left?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="ui-header">
      <div className="ui-header__bar">
        {left ?? <span className="ui-header__side" aria-hidden="true" />}
        <div className="ui-header__center">
          {isAppTitle(title) ? (
            <span className="ui-header__title">{title}</span>
          ) : (
            <h1 className="ui-header__title">{title}</h1>
          )}
          {subtitle && <span className="ui-header__subtitle">{subtitle}</span>}
        </div>
        {right ?? <span className="ui-header__side" aria-hidden="true" />}
      </div>
      {children}
    </header>
  );
}

export interface ScreenProps extends ScreenHeaderProps {
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  hideHeader?: boolean;
}

export function Screen({ actions, children, className, hideHeader, ...header }: ScreenProps) {
  const { registerScreen } = useLayout();
  useLayoutEffect(() => registerScreen(), [registerScreen]);

  return (
    <div className={['ui-screen', className].filter(Boolean).join(' ')}>
      {!hideHeader && <ScreenHeader {...header} />}
      <div className="ui-screen__body">
        {children}
      </div>
      {actions}
    </div>
  );
}

export function BottomActions({
  children,
  layout = 'stack',
  note,
}: {
  children: ReactNode;
  layout?: 'stack' | 'row';
  note?: ReactNode;
}) {
  return (
    <div className={`ui-actions ui-actions--${layout}`}>
      {note && <span className="ui-actions__note">{note}</span>}
      <div className="ui-actions__buttons">{children}</div>
    </div>
  );
}
