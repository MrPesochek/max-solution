let currentToken: string | null = null;
const listeners = new Set<(token: string | null) => void>();

export function getToken(): string | null {
  return currentToken;
}

export function setToken(token: string | null): void {
  currentToken = token;
  for (const listener of listeners) listener(token);
}

export function subscribeToken(listener: (token: string | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetTokenStoreForTests(): void {
  currentToken = null;
  listeners.clear();
}
