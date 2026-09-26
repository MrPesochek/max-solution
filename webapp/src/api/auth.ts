import { api } from './client';
import type { AuthResponse, LinkAuthResponse, MeResponse } from './types';

export function authWithMax(initData: string): Promise<AuthResponse> {
  return api.post<AuthResponse>(
    '/auth/max',
    { init_data: initData },
    { withoutOrganization: true, skipReauth: true },
  );
}

export function authWithLink(token: string): Promise<LinkAuthResponse> {
  return api.post<LinkAuthResponse>(
    '/auth/link',
    { token },
    { withoutOrganization: true, skipReauth: true },
  );
}

export function fetchMe(): Promise<MeResponse> {
  return api.get<MeResponse>('/me', { withoutOrganization: true });
}

export function logout(): Promise<void> {
  return api.post<void>('/auth/logout', undefined, { withoutOrganization: true, skipReauth: true });
}
