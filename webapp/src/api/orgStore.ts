const STORAGE_KEY = 'max-webapp.active-membership-id';
const LEGACY_STORAGE_KEY = 'max-webapp.active-organization-id';

export interface ActiveContext {
  membershipId: string;
  organizationId: string;
}

let active: ActiveContext | null = null;
const listeners = new Set<(context: ActiveContext | null) => void>();

export function getActiveOrganizationId(): string | null {
  return active?.organizationId ?? null;
}

export function getActiveMembershipId(): string | null {
  return active?.membershipId ?? null;
}

export function getActiveScope(): string | null {
  return active?.membershipId ?? null;
}

export function setActiveContext(context: ActiveContext | null): void {
  active = context;
  try {
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    if (context) window.localStorage.setItem(STORAGE_KEY, context.membershipId);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
  }
  for (const listener of listeners) listener(context);
}

export interface StoredContextHint {
  membershipId: string | null;
  organizationId: string | null;
}

export function readStoredContext(): StoredContextHint {
  try {
    return {
      membershipId: window.localStorage.getItem(STORAGE_KEY),
      organizationId: window.localStorage.getItem(LEGACY_STORAGE_KEY),
    };
  } catch {
    return { membershipId: null, organizationId: null };
  }
}

export function subscribeActiveContext(listener: (context: ActiveContext | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetOrgStoreForTests(): void {
  active = null;
  listeners.clear();
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
  }
}
