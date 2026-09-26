import { strings } from '../strings/ru';
import type { Membership } from '../api/types';

export function membershipLabel(membership: Membership): string {
  return `${membership.organization.name} · ${strings.orgPicker.side[membership.side]}`;
}
