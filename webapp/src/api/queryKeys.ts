export const queryKeys = {
  cities: ['directories', 'cities'] as const,
  equipmentCategories: ['directories', 'equipment-categories'] as const,
  organizationCurrent: (scope: string | null) => ['organizations', 'current', scope] as const,
  locations: (scope: string | null) => ['locations', scope] as const,
  location: (scope: string | null, id: string) => ['locations', scope, id] as const,
  equipment: (scope: string | null, locationId?: string) =>
    ['equipment', scope, locationId ?? 'all'] as const,
  equipmentItem: (scope: string | null, id: string) => ['equipment', scope, 'item', id] as const,
  equipmentPhotos: (scope: string | null, id: string) =>
    ['equipment', scope, 'photos', id] as const,
  memberships: (scope: string | null) => ['memberships', scope] as const,
  invitations: (scope: string | null) => ['invitations', scope] as const,
  invitationPreview: (token: string) => ['invitation-preview', token] as const,

  requestLists: (scope: string | null) => ['requests', scope, 'list'] as const,
  requests: (scope: string | null, filters: Record<string, unknown>) =>
    ['requests', scope, 'list', filters] as const,
  request: (scope: string | null, id: string) => ['requests', scope, 'item', id] as const,
  requestHistory: (scope: string | null, id: string) => ['requests', scope, 'history', id] as const,
  requestMessages: (scope: string | null, id: string) => ['requests', scope, 'messages', id] as const,
  requestOffers: (scope: string | null, id: string) => ['requests', scope, 'offers', id] as const,
  offerMessages: (scope: string | null, id: string, offerId: string) =>
    ['requests', scope, 'messages', id, 'offer', offerId] as const,
  pendingApprovals: (scope: string | null) => ['requests', scope, 'pending-approvals'] as const,
  requestAttachments: (scope: string | null, id: string) =>
    ['requests', scope, 'attachments', id] as const,
  equipmentBinding: (scope: string | null, equipmentId: string) =>
    ['requests', scope, 'equipment-binding', equipmentId] as const,
  marketplaceCard: (scope: string | null, id: string) => ['marketplace', scope, 'card', id] as const,
  marketplaceList: (scope: string | null) => ['marketplace', scope, 'list'] as const,
  marketplaceMessages: (scope: string | null, id: string) => ['marketplace', scope, 'messages', id] as const,
  providerRequests: (scope: string | null, filters: Record<string, unknown>) =>
    ['requests', scope, 'list', 'provider', filters] as const,

  providerProfile: (scope: string | null) => ['provider-profile', scope] as const,
  providersCatalog: (filters: { categoryId?: string; cityId?: string; districtId?: string }) =>
    ['providers-catalog', filters.categoryId ?? '', filters.cityId ?? '', filters.districtId ?? ''] as const,
  providerPublic: (id: string) => ['providers', id] as const,
  providerReviews: (id: string) => ['providers', id, 'reviews'] as const,
  portfolio: (scope: string | null) => ['provider-profile', scope, 'portfolio'] as const,
  providerSearch: (q: string) => ['providers-search', q] as const,
  providersCount: (filters: { categoryId?: string; cityId?: string; districtId?: string }) =>
    ['providers-count', filters.categoryId ?? '', filters.cityId ?? '', filters.districtId ?? ''] as const,

  requestReview: (scope: string | null, requestId: string) => ['reviews', scope, 'request', requestId] as const,
  myComplaints: (scope: string | null) => ['complaints', scope] as const,
  myReviews: (scope: string | null) => ['reviews', scope, 'mine'] as const,

  operatorAccess: ['operator', 'access-probe'] as const,
  operatorWarrantyAll: ['operator', 'warranty-authorizations'] as const,
  operatorWarranty: (providerOrgId?: string) => ['operator', 'warranty-authorizations', providerOrgId ?? 'all'] as const,
  operatorBindingsAll: ['operator', 'service-bindings'] as const,
  operatorBindings: (status?: string) => ['operator', 'service-bindings', status ?? 'all'] as const,
  operatorProvidersAll: ['operator', 'provider-profiles'] as const,
  operatorProviders: (status?: string) => ['operator', 'provider-profiles', status ?? 'all'] as const,
  operatorAttachments: (status: string) => ['operator', 'attachments', status] as const,
  operatorReviews: (status: string) => ['operator', 'reviews', status] as const,
  operatorModerationCases: (subjectType: string, status: string, kind?: string) =>
    kind
      ? (['operator', 'moderation-cases', subjectType, status, kind] as const)
      : (['operator', 'moderation-cases', subjectType, status] as const),
  operatorVerificationQueue: ['operator', 'verification-cases'] as const,

  bindings: (scope: string | null, filters: { equipmentId?: string; status?: string }) =>
    ['service-bindings', scope, filters.equipmentId ?? 'all', filters.status ?? 'all'] as const,
  binding: (scope: string | null, id: string) => ['service-bindings', scope, 'item', id] as const,
  bindingInvitations: (scope: string | null) => ['service-binding-invitations', scope] as const,
  bindingInvitationPreview: (token: string) => ['service-binding-invitation-preview', token] as const,

  verificationCases: (scope: string | null) => ['verification-cases', scope] as const,

  apiKeys: (scope: string | null) => ['integration', scope, 'api-keys'] as const,
  webhookSubscriptions: (scope: string | null) => ['integration', scope, 'webhook-subscriptions'] as const,
  deliveries: (scope: string | null) => ['integration', scope, 'deliveries'] as const,
  integrationSummary: (scope: string | null) => ['integration', scope, 'summary'] as const,
};
