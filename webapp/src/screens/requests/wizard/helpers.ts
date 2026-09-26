import { strings } from '../../../strings/ru';
import type { ServiceBinding } from '../../../api/types';

const t = strings.requests.wizard;

export const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
export const MAX_PHOTOS = 10;
export const SCREEN_SLOT = 'display_error';
export const OTHER_REASON = 'other';

export function noPhotoReason(choice: string | null, otherText: string): string | null {
  if (!choice) return null;
  if (choice === OTHER_REASON) return otherText.trim() || null;
  return choice;
}

export { equipmentTitle } from '../components/equipmentName';

export interface NoPhotoState {
  noScreen: boolean;
  choice: string | null;
  otherText: string;
}

export function parseNoPhotoReason(
  stored: string | null | undefined,
  slotLabels: readonly string[],
): NoPhotoState {
  const state: NoPhotoState = { noScreen: false, choice: null, otherText: '' };
  for (const part of (stored ?? '').split('; ')) {
    const colon = part.indexOf(': ');
    const reason = (
      colon >= 0 && slotLabels.includes(part.slice(0, colon)) ? part.slice(colon + 2) : part
    ).trim();
    if (!reason || reason === strings.common.notSpecified) continue;
    if (reason === t.noScreen) {
      state.noScreen = true;
    } else if (!state.choice) {
      const known = t.noPhotoReasons.find((option) => option === reason);
      state.choice = known ?? OTHER_REASON;
      state.otherText = known ? '' : reason;
    }
  }
  return state;
}

export function equipmentLetter(title: string): string {
  return title.trim().slice(0, 1).toUpperCase() || '?';
}

export function deliverableBinding(binding: ServiceBinding | null | undefined): ServiceBinding | null {
  if (!binding || binding.status !== 'confirmed' || !binding.provider.organization_id) return null;
  return binding;
}

export function bindingBasisText(binding: ServiceBinding): string {
  switch (binding.basis) {
    case 'warranty':
      return t.basisWarranty;
    case 'service_contract':
      return binding.contract_number ? t.basisContractNumber(binding.contract_number) : t.basisContract;
    default:
      return t.basisPreferred;
  }
}

export function bindingConfirmedText(binding: ServiceBinding): string {
  switch (binding.basis) {
    case 'warranty':
      return t.reviewBasisWarranty;
    case 'service_contract':
      return t.reviewBasisContract;
    default:
      return t.reviewBasisPreferred;
  }
}

export function symptomPresets(categoryCode: string | null | undefined): readonly string[] {
  return (categoryCode && t.symptomPresets[categoryCode]) || t.symptomPresetsDefault;
}

const lowerFirst = (value: string) => value.charAt(0).toLowerCase() + value.slice(1);
const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

export function joinSymptoms(chips: readonly string[], text: string, presets: readonly string[]): string {
  const ordered = presets.filter((preset) => chips.some((chip) => same(chip, preset)));
  const head = ordered.map((chip, index) => (index === 0 ? chip : lowerFirst(chip))).join(', ');
  const body = text.trim();
  if (!head) return text;
  return body ? `${head}. ${body}` : head;
}

export function splitSymptoms(
  description: string | null | undefined,
  presets: readonly string[],
): { chips: string[]; text: string } {
  const value = description ?? '';
  const dot = value.indexOf('. ');
  const head = dot >= 0 ? value.slice(0, dot) : value;
  const parts = head.split(', ');
  const matched = parts.map((part) => presets.find((preset) => same(preset, part)));
  if (!head.trim() || matched.some((m) => !m)) return { chips: [], text: value };
  return { chips: matched as string[], text: dot >= 0 ? value.slice(dot + 2) : '' };
}
