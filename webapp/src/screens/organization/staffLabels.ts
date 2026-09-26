import { strings } from '../../strings/ru';
import type { Role } from '../../api/types';

export function placesLabel(
  role: Role | null,
  locationIds: string[],
  names: Map<string, string>,
): string | null {
  if (!role || role === 'provider_admin' || role === 'provider_dispatcher') return null;
  if (role === 'customer_manager') return strings.organization.allLocations;
  const list = locationIds.map((id) => names.get(id)).filter(Boolean);
  return list.length > 0 ? list.join(', ') : strings.organization.noLocations;
}

export function roleWithPlaces(
  role: Role | null,
  locationIds: string[],
  names: Map<string, string>,
): string {
  const roleText = role ? strings.home.roleShort[role] : strings.common.notSpecified;
  const places = placesLabel(role, locationIds, names);
  return places ? strings.organization.staffSubtitle(roleText, places) : roleText;
}
