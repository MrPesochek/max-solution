import { backButton, isBridgeAvailable } from '../../max/bridge';

export type BackLevel = 'screen' | 'overlay';

interface Entry {
  level: BackLevel;
  handler: () => void;
}

const entries: Entry[] = [];
let subscribedTo: unknown = null;
let shown = false;

function top(): Entry | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i]!.level === 'overlay') return entries[i];
  }
  return entries[entries.length - 1];
}

function dispatch() {
  top()?.handler();
}

function sync() {
  if (!isBridgeAvailable()) return;
  if (subscribedTo !== window.WebApp) {
    backButton.onClick(dispatch);
    subscribedTo = window.WebApp;
    shown = false;
  }
  const visible = entries.length > 0;
  if (visible === shown) return;
  shown = visible;
  if (visible) backButton.show();
  else backButton.hide();
}

export function registerBack(level: BackLevel, handler: () => void): () => void {
  const entry: Entry = { level, handler };
  entries.push(entry);
  sync();
  return () => {
    const index = entries.indexOf(entry);
    if (index >= 0) entries.splice(index, 1);
    sync();
  };
}

export function dispatchBack(): boolean {
  const entry = top();
  entry?.handler();
  return Boolean(entry);
}

export function resetBackStackForTests(): void {
  entries.length = 0;
  subscribedTo = null;
  shown = false;
}
