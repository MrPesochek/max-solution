import { parseStartParam } from '../../max/startParam';

export function extractInviteToken(raw: string, kind: 'inv' | 'sb'): string {
  const trimmed = raw.trim();
  let candidate = trimmed;
  try {
    const url = new URL(trimmed);
    candidate = url.searchParams.get('startapp') ?? trimmed;
  } catch {
  }
  const parsed = parseStartParam(candidate);
  return parsed?.kind === kind ? parsed.value : candidate;
}

export function extractInvitationToken(raw: string): string {
  return extractInviteToken(raw, 'inv');
}
