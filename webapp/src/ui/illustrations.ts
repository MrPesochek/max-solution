import { createElement, type CSSProperties } from 'react';

export const ILLUSTRATION_NAMES = [
  'bar',
  'cabinet',
  'chest',
  'display',
  'icemaker',
  'unit',
  'cold-room',
  'status-cancel',
  'status-diagnostics',
  'status-dispute',
  'status-done',
  'status-offers',
  'status-part',
  'status-price',
  'status-repair',
  'status-search',
  'status-travel',
  'status-waiting',
  'request-sent',
  'request-temperature',
  'review',
  'thanks',
  'chat',
  'welcome-handshake',
  'role-employee',
  'role-master',
  'organization',
  'invitation',
  'service-invitation',
  'service-linked',
  'master',
  'performer-empty',
  'performer-new',
  'performer-territory',
  'profile-check',
  'profile-missing',
  'profile-verified',
  'equipment-add',
  'equipment-empty',
  'crm-sync',
  'crm-wires',
  'error-broken',
  'error-maintenance',
  'error-offline',
] as const;

export type IllustrationName = (typeof ILLUSTRATION_NAMES)[number];

const files = import.meta.glob<string>('../assets/illustrations/*.svg', {
  eager: true,
  query: '?no-inline',
  import: 'default',
});

function fileName(path: string): string {
  return path.slice(path.lastIndexOf('/') + 1, -'.svg'.length);
}

const byFile = new Map(Object.entries(files).map(([path, url]) => [fileName(path), url]));

export const ILLUSTRATIONS = Object.fromEntries(
  ILLUSTRATION_NAMES.map((name) => [name, byFile.get(name) ?? '']),
) as Record<IllustrationName, string>;

export function illustrationUrl(name: IllustrationName): string {
  return ILLUSTRATIONS[name];
}

export function isIllustrationName(value: unknown): value is IllustrationName {
  return typeof value === 'string' && (ILLUSTRATION_NAMES as readonly string[]).includes(value);
}

const BY_CODE: Record<string, IllustrationName> = {
  commercial_display_fridge: 'display',
  chest_freezer: 'chest',
  refrigerator_cabinet: 'cabinet',
  split_system_cold_room: 'cold-room',
  other: 'equipment-add',
  refrigeration_unit: 'unit',
  ice_maker: 'icemaker',
  bar_fridge: 'bar',
  fridge: 'cabinet',
};

const BY_NAME: [RegExp, IllustrationName][] = [
  [/витрин/i, 'display'],
  [/лар/i, 'chest'],
  [/л[её]д|льдо/i, 'icemaker'],
  [/бар/i, 'bar'],
  [/камер/i, 'cold-room'],
  [/агрегат|сплит|блок/i, 'unit'],
  [/шкаф|холодил/i, 'cabinet'],
];

export function equipmentIllustration(code?: string | null, name?: string | null): IllustrationName {
  if (code && BY_CODE[code]) return BY_CODE[code];
  const found = name ? BY_NAME.find(([pattern]) => pattern.test(name)) : undefined;
  return found ? found[1] : 'cabinet';
}

function ratio(name: IllustrationName): number {
  return name === 'master' ? 130 / 100 : 240 / 280;
}

export interface IllustrationProps {
  name: IllustrationName;
  width?: number;
  alt?: string;
  className?: string;
  style?: CSSProperties;
}

export function Illustration({ name, width = 188, alt = '', className, style }: IllustrationProps) {
  return createElement('img', {
    src: ILLUSTRATIONS[name],
    alt,
    width,
    height: Math.round(width * ratio(name)),
    className: ['ui-illustration', className].filter(Boolean).join(' '),
    style,
    draggable: false,
    decoding: 'async',
  });
}
