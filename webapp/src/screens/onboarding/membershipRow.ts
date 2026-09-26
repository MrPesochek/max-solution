import { strings } from '../../strings/ru';
import type { Membership } from '../../api/types';
import type { Gradient } from '../../ui/blocks/Blocks';

const GRADIENTS: Gradient[] = ['o', 'g', 'r', 'b', 'p'];

export function membershipSubtitle(membership: Membership): string {
  const role = strings.orgPicker.roleLower[membership.role] ?? membership.role;
  const points =
    membership.role === 'customer_employee' && membership.location_ids.length > 0
      ? `, ${strings.orgPicker.points(membership.location_ids.length)}`
      : '';
  return strings.orgPicker.sideRole(strings.orgPicker.sideTitle[membership.side], role + points);
}

export function organizationGradient(organizationId: string): Gradient {
  let hash = 0;
  for (const char of organizationId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return GRADIENTS[hash % GRADIENTS.length]!;
}
