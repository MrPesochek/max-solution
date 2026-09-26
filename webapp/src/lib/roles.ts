import type { Role } from '../api/types';

export function canManageOrganization(role: Role): boolean {
  return role === 'customer_manager' || role === 'provider_admin';
}

export function canManageLocationsAndEquipment(role: Role): boolean {
  return role === 'customer_manager';
}

export function canPublishExternalSearch(role: Role): boolean {
  return role === 'customer_manager';
}

export function isCustomer(role: Role): boolean {
  return role === 'customer_manager' || role === 'customer_employee';
}

export function isProvider(role: Role): boolean {
  return role === 'provider_admin' || role === 'provider_dispatcher';
}

export function canApproveMembership(role: Role): boolean {
  return role === 'customer_manager' || role === 'provider_admin';
}

export function canEditMembershipLocations(role: Role): boolean {
  return role === 'customer_manager';
}

export function canManageProviderProfile(role: Role): boolean {
  return role === 'provider_admin';
}

export function canAccessIntegration(role: Role): boolean {
  return role === 'provider_admin';
}

export function canManageBindings(role: Role): boolean {
  return role === 'customer_manager';
}

export function canRespondToBindings(role: Role): boolean {
  return role === 'provider_admin' || role === 'provider_dispatcher';
}

export function canManageRequestApprovals(role: Role): boolean {
  return role === 'customer_manager';
}
