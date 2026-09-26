import type { ReactNode } from 'react';

export function ScreenTitle({ children }: { children: ReactNode }) {
  return <h1 className="screen-title">{children}</h1>;
}
