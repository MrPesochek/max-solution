import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from '../mocks/server';
import { resetMockState, snapshotMockState } from '../mocks/mockState';
import { resetTokenStoreForTests } from '../api/tokenStore';
import { resetOrgStoreForTests } from '../api/orgStore';
import { setReauthHandler } from '../api/client';
import { queryClient } from '../api/queryClient';
import { resetLoginLinkForTests } from '../session/loginLink';

if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

const lazyModules = import.meta.glob(['../screens/**/*.tsx', '!../screens/**/*.test.tsx']);

beforeAll(async () => {
  server.listen({ onUnhandledRequest: 'error' });
  for (const load of Object.values(lazyModules)) await load();
  snapshotMockState();
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  server.events.removeAllListeners();
  delete window.WebApp;
  resetTokenStoreForTests();
  resetOrgStoreForTests();
  setReauthHandler(null);
  queryClient.clear();
  resetLoginLinkForTests();
  window.location.hash = '';
  resetMockState();
});
afterAll(() => server.close());
