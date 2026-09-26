import { api } from './client';
import type { AuthResponse } from './types';

export function authDemo(userKey: string): Promise<AuthResponse> {
  return api.post<AuthResponse>(
    '/auth/demo',
    { user_key: userKey },
    { withoutOrganization: true, skipReauth: true },
  );
}
