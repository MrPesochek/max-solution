export interface MaxUserUnsafe {
  id?: number | string;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
}

export interface MaxInitDataUnsafe {
  user?: MaxUserUnsafe;
  auth_date?: number;
  start_param?: string;
  query_id?: string;
  hash?: string;
}

interface BackButtonApi {
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
}

interface HapticFeedbackApi {
  impactOccurred: (style?: string) => void;
  notificationOccurred: (type?: 'error' | 'success' | 'warning') => void;
  selectionChanged: () => void;
}

interface WebAppBridge {
  initData?: string;
  initDataUnsafe?: MaxInitDataUnsafe;
  platform?: string;
  version?: string;
  ready?: () => void;
  close?: () => void;
  openLink?: (url: string) => void;
  requestContact?: (callback: (contact: unknown) => void) => void;
  colorScheme?: 'light' | 'dark';
  BackButton?: BackButtonApi;
  HapticFeedback?: HapticFeedbackApi;
}

declare global {
  interface Window {
    WebApp?: WebAppBridge;
  }
}

const SCRIPT_LOAD_TIMEOUT_MS = 4000;

let loadPromise: Promise<boolean> | null = null;
let pendingScript: HTMLScriptElement | null = null;
const lateListeners = new Set<() => void>();

export function onBridgeReady(listener: () => void): () => void {
  lateListeners.add(listener);
  return () => {
    lateListeners.delete(listener);
  };
}

function notifyLateBridge(): void {
  if (!isBridgeAvailable()) return;
  for (const listener of [...lateListeners]) listener();
}

function injectScript(src: string): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };

    const timer = setTimeout(() => finish(false), SCRIPT_LOAD_TIMEOUT_MS);

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    pendingScript = script;
    script.onload = () => {
      clearTimeout(timer);
      if (pendingScript === script) pendingScript = null;
      if (settled) {
        notifyLateBridge();
        return;
      }
      finish(Boolean(window.WebApp));
    };
    script.onerror = () => {
      clearTimeout(timer);
      if (pendingScript === script) pendingScript = null;
      script.remove();
      finish(false);
    };
    document.head.appendChild(script);
  });
}

export function loadMaxBridge(): Promise<boolean> {
  if (loadPromise) return loadPromise;

  if (typeof window !== 'undefined' && window.WebApp) {
    loadPromise = Promise.resolve(true);
    return loadPromise;
  }

  const src = import.meta.env.VITE_MAX_BRIDGE_URL;
  if (!src || typeof document === 'undefined') {
    loadPromise = Promise.resolve(false);
    return loadPromise;
  }

  loadPromise = injectScript(src);
  return loadPromise;
}

export function reloadMaxBridge(): Promise<boolean> {
  if (isBridgeAvailable()) return Promise.resolve(true);
  const src = import.meta.env.VITE_MAX_BRIDGE_URL;
  if (!src || typeof document === 'undefined') return Promise.resolve(false);
  pendingScript?.remove();
  pendingScript = null;
  loadPromise = injectScript(src).then(() => isBridgeAvailable());
  return loadPromise;
}

export function resetMaxBridgeForTests(): void {
  pendingScript?.remove();
  pendingScript = null;
  loadPromise = null;
  lateListeners.clear();
}

function getBridge(): WebAppBridge | undefined {
  return typeof window !== 'undefined' ? window.WebApp : undefined;
}

export function isBridgeAvailable(): boolean {
  return Boolean(getBridge()?.initData);
}

export function getInitData(): string | null {
  return getBridge()?.initData || null;
}

export function getInitDataUnsafe(): MaxInitDataUnsafe | null {
  return getBridge()?.initDataUnsafe ?? null;
}

export function getStartParam(): string | null {
  return getBridge()?.initDataUnsafe?.start_param ?? null;
}

export function getColorScheme(): 'light' | 'dark' | null {
  if (!isBridgeAvailable()) return null;
  return getBridge()?.colorScheme ?? null;
}

export function getPlatform(): 'ios' | 'android' | null {
  const raw = getBridge()?.platform?.toLowerCase();
  if (!raw) return null;
  return raw.includes('ios') ? 'ios' : 'android';
}

export function notifyReady(): void {
  getBridge()?.ready?.();
}

export function closeApp(): void {
  getBridge()?.close?.();
}

export function openExternalLink(url: string): void {
  const bridge = getBridge();
  if (bridge?.openLink) {
    bridge.openLink(url);
  } else if (typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

export function requestContact(callback: (contact: unknown) => void): void {
  getBridge()?.requestContact?.(callback);
}

export const backButton = {
  show(): void {
    getBridge()?.BackButton?.show();
  },
  hide(): void {
    getBridge()?.BackButton?.hide();
  },
  onClick(cb: () => void): void {
    getBridge()?.BackButton?.onClick(cb);
  },
  offClick(cb: () => void): void {
    getBridge()?.BackButton?.offClick(cb);
  },
};

export const haptics = {
  impact(style?: string): void {
    getBridge()?.HapticFeedback?.impactOccurred(style);
  },
  notification(type?: 'error' | 'success' | 'warning'): void {
    getBridge()?.HapticFeedback?.notificationOccurred(type);
  },
  selection(): void {
    getBridge()?.HapticFeedback?.selectionChanged();
  },
};
