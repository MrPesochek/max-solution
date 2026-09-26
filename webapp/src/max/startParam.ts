export type StartParamKind = 'inv' | 'req' | 'mkt' | 'scr' | 'sb';

export interface ParsedStartParam {
  kind: StartParamKind;
  value: string;
}

const KNOWN_KINDS: ReadonlySet<string> = new Set(['inv', 'req', 'mkt', 'scr', 'sb']);

const OBJECT_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function parseStartParam(raw: string | null | undefined): ParsedStartParam | null {
  if (!raw) return null;
  const separatorIndex = raw.indexOf('_');
  if (separatorIndex <= 0 || separatorIndex === raw.length - 1) return null;

  const kind = raw.slice(0, separatorIndex);
  const value = raw.slice(separatorIndex + 1);
  if (!KNOWN_KINDS.has(kind) || value.length === 0) return null;
  if ((kind === 'req' || kind === 'mkt') && !OBJECT_ID.test(value)) return null;

  return { kind: kind as StartParamKind, value };
}

export function startParamToPath(parsed: ParsedStartParam | null): string | null {
  if (!parsed) return null;

  switch (parsed.kind) {
    case 'inv':
      return `/invitations/accept?token=${encodeURIComponent(parsed.value)}`;
    case 'sb':
      return `/bindings/accept?token=${encodeURIComponent(parsed.value)}`;
    case 'req':
      return `/requests/${encodeURIComponent(parsed.value)}`;
    case 'mkt':
      return `/provider/available/${encodeURIComponent(parsed.value)}`;
    case 'scr':
      return knownScreenPath(parsed.value);
    default:
      return null;
  }
}

const SCREEN_ROUTES: Record<string, string> = {
  home: '/',
  equipment: '/equipment',
  locations: '/locations',
  organization: '/organization',
  requests: '/requests',
  my_service: '/',
  find_provider: '/providers',
  inbox: '/provider/incoming',
  available: '/provider/available',
  in_progress: '/provider/in-work',
  profile: '/provider/profile',
  integration: '/integration',
};

function knownScreenPath(value: string): string | null {
  return SCREEN_ROUTES[value] ?? null;
}
