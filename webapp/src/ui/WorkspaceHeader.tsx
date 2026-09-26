import type { ReactNode } from 'react';

export function WorkspaceHeader({
  eyebrow,
  title,
  subtitle,
  side,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  side?: ReactNode;
}) {
  return (
    <div className="ui-whead">
      <div className="ui-whead__main">
        {eyebrow && <span className="ui-whead__eyebrow">{eyebrow}</span>}
        <h1 className="ui-whead__title">{title}</h1>
        {subtitle && <span className="ui-whead__sub">{subtitle}</span>}
      </div>
      {side && <div className="ui-whead__side">{side}</div>}
    </div>
  );
}
