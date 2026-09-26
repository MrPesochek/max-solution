const LINK_ROUTE = '#/auth/link';
const VIA_LINK_KEY = 'max-webapp.opened-via-login-link';

let captured: string | null = null;

function readAndStripToken(): string | null {
  const { hash, pathname, search } = window.location;
  if (!hash.startsWith(LINK_ROUTE)) return null;
  const rest = hash.slice(LINK_ROUTE.length);
  if (rest !== '' && !rest.startsWith('?')) return null;
  window.history.replaceState(window.history.state, '', `${pathname}${search}#/`);
  return new URLSearchParams(rest.slice(1)).get('t') || null;
}

export function captureLoginLinkToken(): void {
  captured = readAndStripToken() ?? captured;
}

export function takeLoginLinkToken(): string | null {
  const token = readAndStripToken() ?? captured;
  captured = null;
  return token;
}

export function rememberOpenedViaLink(): void {
  try {
    window.sessionStorage.setItem(VIA_LINK_KEY, '1');
  } catch {
    // хранилище недоступно — после перезагрузки покажем общий экран входа
  }
}

export function wasOpenedViaLink(): boolean {
  try {
    return window.sessionStorage.getItem(VIA_LINK_KEY) === '1';
  } catch {
    return false;
  }
}

export function botChatUrl(): string | null {
  const name = import.meta.env.VITE_MAX_BOT_USERNAME?.trim();
  return name ? `https://max.ru/${encodeURIComponent(name)}` : null;
}

export function openBotChat(): void {
  const url = botChatUrl();
  if (url) window.location.assign(url);
}

export function resetLoginLinkForTests(): void {
  captured = null;
  try {
    window.sessionStorage.removeItem(VIA_LINK_KEY);
  } catch {
    // нет хранилища — нечего чистить
  }
}
