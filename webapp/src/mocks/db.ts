import type {
  ApiKey,
  ApiKeyCreateInput,
  ApiKeyIssued,
  BindingBasis,
  BindingInvitation,
  BindingInvitationIssued,
  BindingInvitationItem,
  BindingInvitationItemInput,
  BindingInvitationPreview,
  BindingItemMatch,
  BindingRequestAccepted,
  BindingRequestInput,
  BindingStatus,
  City,
  Complaint,
  ContactBindingInput,
  CreateInvitationInput,
  CreateOrganizationInput,
  Delivery,
  DeliveryPage,
  DeliveryState,
  Equipment,
  EquipmentBindingSummary,
  EquipmentCategory,
  EquipmentInput,
  EquipmentUpdateInput,
  GuarantorKind,
  IntegrationScope,
  IntegrationSummary,
  Invitation,
  InvitationIssued,
  InvitationPreview,
  InvitationState,
  Location,
  LocationInput,
  LocationUpdateInput,
  Membership,
  MembershipStatus,
  Organization,
  OrganizationKind,
  OrganizationRef,
  Page,
  ParticipationInput,
  ProviderBinding,
  ProviderBrandRestriction,
  ProviderCatalogItem,
  ProviderCategory,
  ProviderKind,
  ProviderProfile,
  ProviderProfileStatus,
  ProviderProfileUpdateInput,
  ProviderPublicProfile,
  ProviderServiceArea,
  PublicReview,
  Role,
  ServiceBinding,
  StaffMember,
  UpdateOrganizationInput,
  VerificationBadge,
  VerificationCase,
  VerificationCheckKind,
  VerificationInformationInput,
  WarrantyAuthorization,
  WebhookSubscription,
  WebhookSubscriptionIssued,
} from '../api/types';
import type { components } from '../api/schema';
import { canEditProfileFields, canEditRequisites, canSubmitProfile } from '../lib/trust';
import { tracked } from './mockState';

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}_${counter.toString(36)}`;
}

function applyPatch<T extends object>(current: T, patch: Partial<Record<keyof T, unknown>>): T {
  const next = { ...current };
  for (const key of Object.keys(patch) as (keyof T)[]) {
    const value = patch[key];
    if (value !== undefined && value !== null) next[key] = value as T[typeof key];
  }
  return next;
}

function stripOrgId<T extends { organization_id: string }>(value: T): Omit<T, 'organization_id'> {
  const copy: Partial<T> = { ...value };
  delete copy.organization_id;
  return copy as Omit<T, 'organization_id'>;
}

const PROVIDER_ROLES: Role[] = ['provider_admin', 'provider_dispatcher'];

type ProfileAppeal = components['schemas']['ProfileAppealView'];

export type Side = 'customer' | 'provider';

export function sideOfRole(role: Role): Side {
  return PROVIDER_ROLES.includes(role) ? 'provider' : 'customer';
}

export interface DbUser {
  id: string;
  display_name: string;
}

export interface DbSession {
  token: string;
  user_id: string;
}

interface DbOrganization {
  id: string;
  name: string;
  kinds: OrganizationKind[];
  contact_phone: string | null;
  contact_name: string | null;
  representative_position: string | null;
  contact_email: string | null;
  legal_form: string | null;
  inn: string | null;
  created_at: string;
}

export interface DbMembership {
  id: string;
  user_id: string;
  organization_id: string;
  role: Role;
  status: MembershipStatus;
  location_ids: string[];
  accepted_at?: string | null;
  expected_name?: string | null;
}

interface DbInvitation {
  id: string;
  organization_id: string;
  role: Role;
  location_ids: string[];
  token: string;
  token_prefix: string;
  expires_at: string;
  inviter_name: string | null;
  dbStatus: 'pending' | 'accepted' | 'revoked';
  created_at: string;
  recipient_max_user_id: string | null;
  recipient_name: string | null;
}

interface DbProviderProfile {
  id: string;
  organizationId: string;
  providerKind: ProviderKind;
  status: ProviderProfileStatus;
  statusReason: string | null;
  acceptingNewRequests: boolean;
  visitTerms: string | null;
  visitPriceFromMinor: number | null;
  appeal: ProfileAppeal | null;
  canProvideDocuments: boolean;
  description: string | null;
  categoryIds: string[];
  serviceAreas: { city_id: string; district_ids: string[] }[];
  brandRestrictions: { equipment_category_id: string; brands: string[] }[];
  ratingOverride: number | null;
  reviewsCountOverride: number;
  uniqueCustomersOverride: number;
  publishedGallery: string[];
  createdAt: string;
  updatedAt: string;
}

interface DbVerificationCase {
  id: string;
  organizationId: string;
  subjectType: string;
  checkKind: VerificationCheckKind;
  decision: 'pending' | 'approved' | 'rejected' | 'needs_information' | 'revoked';
  decisionReason: string | null;
  source: string | null;
  evidenceNote: string | null;
  checkedAt: string | null;
  expiresAt: string | null;
  isDemo: boolean;
  createdAt: string;
}

interface DbWarrantyAuthorization {
  id: string;
  guarantorKind: GuarantorKind;
  guarantorName: string | null;
  providerOrgId: string;
  equipmentCategoryId: string | null;
  brands: string[];
  cityId: string | null;
  validFrom: string | null;
  validUntil: string | null;
  status: 'pending' | 'active' | 'expired' | 'revoked';
  isDemo: boolean;
}

interface DbServiceBinding {
  id: string;
  invitationItemIndex?: number | null;
  invitationItemDescription?: string | null;
  equipmentId: string;
  customerOrgId: string;
  providerOrgId: string | null;
  status: BindingStatus;
  statusReason: string | null;
  basis: BindingBasis;
  contractNumber: string | null;
  claimedContractNumber: string | null;
  personalContactName: string | null;
  personalContactPhone: string | null;
  guarantorKind: GuarantorKind | null;
  guarantorOrgId: string | null;
  statedGuarantorName?: string | null;
  warrantyAuthorizationId: string | null;
  validFrom: string | null;
  validUntil: string | null;
  customerConfirmedAt: string | null;
  providerConfirmedAt: string | null;
  createdAt: string;
}

interface DbBindingInvitation {
  id: string;
  providerOrgId: string;
  targetOrgId: string | null;
  token: string;
  tokenPrefix: string;
  contractNumber: string;
  basis: BindingBasis;
  validFrom: string | null;
  validUntil: string | null;
  customerInn: string;
  customerName: string | null;
  guarantorKind?: GuarantorKind | null;
  guarantorName?: string | null;
  equipmentItems: BindingInvitationItemInput[];
  equipmentIds: string[];
  dbStatus: 'pending' | 'accepted' | 'revoked' | 'declined';
  declinedAt?: string | null;
  declineReason?: string | null;
  expiresAt: string;
  createdAt: string;
}

interface DbApiKey {
  id: string;
  organizationId: string;
  name: string;
  scopes: IntegrationScope[];
  status: 'active' | 'revoked';
  keyPrefix: string;
  fullKey: string;
  createdAt: string;
  rotatedAt: string | null;
  revokedAt: string | null;
  lastUsedAt: string | null;
}

interface DbWebhookSubscription {
  id: string;
  organizationId: string;
  url: string;
  events: string[];
  status: 'active' | 'disabled';
  createdAt: string;
  disabledAt: string | null;
}

interface DbDelivery {
  id: string;
  organizationId: string;
  eventId: string;
  eventType: string;
  subscriptionId: string;
  state: DeliveryState;
  inFlight: boolean;
  attemptCount: number;
  lastHttpStatus: number | null;
  lastError: string | null;
  lastAttemptAt: string | null;
  nextAttemptAt: string | null;
  expiresAt: string;
  createdAt: string;
}

const users = tracked(new Map<string, DbUser>());
const organizations = tracked(new Map<string, DbOrganization>());
const memberships = tracked(new Map<string, DbMembership>());
const sessions = tracked(new Map<string, DbSession>());
const locations = tracked(new Map<string, Location & { organization_id: string }>());
const equipment = tracked(new Map<string, Equipment>());
const invitations = tracked(new Map<string, DbInvitation>());

const providerProfiles = tracked(new Map<string, DbProviderProfile>());
const verificationCases = tracked(new Map<string, DbVerificationCase>());
const warrantyAuthorizations = tracked(new Map<string, DbWarrantyAuthorization>());
const serviceBindings = tracked(new Map<string, DbServiceBinding>());
const bindingInvitations = tracked(new Map<string, DbBindingInvitation>());
const apiKeys = tracked(new Map<string, DbApiKey>());
const webhookSubscriptions = tracked(new Map<string, DbWebhookSubscription>());
const deliveries = tracked(new Map<string, DbDelivery>());
const galleryCaptions = tracked(new Map<string, string>());

export function setGalleryCaption(attachmentId: string, caption: string | null): void {
  if (caption) galleryCaptions.set(attachmentId, caption);
  else galleryCaptions.delete(attachmentId);
}

export function publishGalleryItem(organizationId: string, attachmentId: string, caption: string | null): void {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return;
  if (!profile.publishedGallery.includes(attachmentId)) profile.publishedGallery.push(attachmentId);
  setGalleryCaption(attachmentId, caption);
}

export function unpublishGalleryItem(attachmentId: string): void {
  for (const profile of providerProfiles.values()) {
    profile.publishedGallery = profile.publishedGallery.filter((id) => id !== attachmentId);
  }
  setGalleryCaption(attachmentId, null);
}
const bindingRequestAttempts = tracked(new Map<string, number[]>());

const cities: City[] = [
  {
    id: 'city_msk',
    name: 'Москва',
    region: null,
    timezone: 'Europe/Moscow',
    districts: [
      { id: 'dist_msk_c', name: 'Центральный' },
      { id: 'dist_msk_s', name: 'Южный' },
      { id: 'dist_msk_n', name: 'Северный' },
    ],
  },
  {
    id: 'city_spb',
    name: 'Санкт-Петербург',
    region: null,
    timezone: 'Europe/Moscow',
    districts: [
      { id: 'dist_spb_c', name: 'Центральный' },
      { id: 'dist_spb_v', name: 'Василеостровский' },
    ],
  },
];

const equipmentCategories: EquipmentCategory[] = [
  {
    id: 'cat_other',
    code: 'other',
    name: 'Техника другого типа',
    photo_template: [
      { code: 'overview', label: 'Общий вид', required: true, visibility_class: 'request_private' },
      { code: 'nameplate', label: 'Шильдик', required: false, visibility_class: 'request_sensitive' },
    ],
  },
  {
    id: 'cat_fridge',
    code: 'fridge',
    name: 'Холодильное оборудование',
    photo_template: [
      { code: 'overview', label: 'Общий вид', required: true, visibility_class: 'request_private' },
      { code: 'nameplate', label: 'Шильдик', required: true, visibility_class: 'request_sensitive' },
      {
        code: 'display_error',
        label: 'Экран / код ошибки',
        required: false,
        visibility_class: 'request_private',
      },
    ],
  },
  {
    id: 'cat_coffee',
    code: 'coffee',
    name: 'Кофемашины',
    photo_template: [
      { code: 'overview', label: 'Общий вид', required: true, visibility_class: 'request_private' },
    ],
  },
  {
    id: 'cat_bar_fridge',
    code: 'bar_fridge',
    name: 'Холодильник для напитков',
    photo_template: [
      { code: 'overview', label: 'Общий вид', required: true, visibility_class: 'request_private' },
      { code: 'nameplate', label: 'Шильдик', required: true, visibility_class: 'request_sensitive' },
    ],
  },
  {
    id: 'cat_refrigeration_unit',
    code: 'refrigeration_unit',
    name: 'Холодильный блок',
    photo_template: [
      { code: 'overview', label: 'Общий вид', required: true, visibility_class: 'request_private' },
      { code: 'nameplate', label: 'Шильдик', required: true, visibility_class: 'request_sensitive' },
    ],
  },
];

function createUser(displayName: string): DbUser {
  const user: DbUser = { id: nextId('usr'), display_name: displayName };
  users.set(user.id, user);
  return user;
}

function createOrganization(name: string, kinds: OrganizationKind[]): DbOrganization {
  const org: DbOrganization = {
    id: nextId('org'),
    name,
    kinds,
    contact_phone: '+7 900 000-00-00',
    contact_name: null,
    representative_position: null,
    contact_email: null,
    legal_form: null,
    inn: null,
    created_at: new Date().toISOString(),
  };
  organizations.set(org.id, org);
  return org;
}

function createMembership(
  userId: string,
  organizationId: string,
  role: Role,
  locationIds: string[] = [],
  status: MembershipStatus = 'active',
): DbMembership {
  const membership: DbMembership = {
    id: nextId('mem'),
    user_id: userId,
    organization_id: organizationId,
    role,
    status,
    location_ids: locationIds,
  };
  memberships.set(membership.id, membership);
  return membership;
}

function createLocation(
  organizationId: string,
  input: LocationInput,
): Location & { organization_id: string } {
  const location: Location & { organization_id: string } = {
    id: nextId('loc'),
    organization_id: organizationId,
    name: input.name,
    city_id: input.city_id,
    district_id: input.district_id ?? null,
    address: input.address,
    timezone: input.timezone ?? 'Europe/Moscow',
    contact_name: input.contact_name ?? null,
    contact_phone: input.contact_phone ?? null,
    created_at: new Date().toISOString(),
  };
  locations.set(location.id, location);
  return location;
}

const demoCustomer = createOrganization('ООО «Ромашка»', ['customer']);
const demoProvider = createOrganization('Сервис-Холод', ['provider']);

const demoManagerUser = createUser('Иван Петров');
const demoEmployeeUser = createUser('Анна Смирнова');
const demoProviderAdminUser = createUser('Сергей Холодов');
const demoDispatcherUser = createUser('Дмитрий Морозов');
const demoPendingDispatcherUser = createUser('Ольга Зимина');
const demoNewUser = createUser('Новый пользователь');
const demoOperatorUser = createUser('Оператор Платформы');

const demoLocation1 = createLocation(demoCustomer.id, {
  name: 'Кафе на Тверской',
  city_id: 'city_msk',
  district_id: 'dist_msk_c',
  address: 'ул. Тверская, 1',
  timezone: 'Europe/Moscow',
});
createLocation(demoCustomer.id, {
  name: 'Магазин на Невском',
  city_id: 'city_spb',
  district_id: 'dist_spb_c',
  address: 'Невский пр., 10',
  timezone: 'Europe/Moscow',
});

createMembership(demoManagerUser.id, demoCustomer.id, 'customer_manager', [demoLocation1.id]);
createMembership(demoEmployeeUser.id, demoCustomer.id, 'customer_employee', [demoLocation1.id]);
createMembership(demoProviderAdminUser.id, demoProvider.id, 'provider_admin');
createMembership(demoDispatcherUser.id, demoProvider.id, 'provider_dispatcher');
createMembership(demoPendingDispatcherUser.id, demoProvider.id, 'provider_dispatcher', [], 'pending');
createMembership(demoOperatorUser.id, demoCustomer.id, 'customer_employee', [demoLocation1.id]);

const seedEquipment: Equipment = {
  id: nextId('eq'),
  location_id: demoLocation1.id,
  equipment_category_id: 'cat_fridge',
  brand: 'Bosch',
  model: 'KGN39VL316',
  serial_number: 'SN-001122',
  notes: null,
  created_at: new Date().toISOString(),
};
equipment.set(seedEquipment.id, seedEquipment);

const seedCoffeeEquipment: Equipment = {
  id: nextId('eq'),
  location_id: demoLocation1.id,
  equipment_category_id: 'cat_coffee',
  brand: 'Saeco',
  model: 'Royal',
  serial_number: 'SN-778899',
  notes: null,
  created_at: new Date().toISOString(),
};
equipment.set(seedCoffeeEquipment.id, seedCoffeeEquipment);

const demoCustomerInn = '7712345600';
demoCustomer.inn = demoCustomerInn;

function createProviderProfile(organizationId: string, status: ProviderProfileStatus): DbProviderProfile {
  const now = new Date().toISOString();
  const profile: DbProviderProfile = {
    id: nextId('pp'),
    organizationId,
    providerKind: 'company',
    status,
    statusReason: null,
    acceptingNewRequests: false,
    visitTerms: null,
    visitPriceFromMinor: null,
    appeal: null,
    canProvideDocuments: false,
    description: null,
    categoryIds: [],
    serviceAreas: [],
    brandRestrictions: [],
    ratingOverride: null,
    reviewsCountOverride: 0,
    uniqueCustomersOverride: 0,
    publishedGallery: [],
    createdAt: now,
    updatedAt: now,
  };
  providerProfiles.set(organizationId, profile);
  return profile;
}

createProviderProfile(demoProvider.id, 'draft');

const demoNeedsInfoProvider = createOrganization('Холод-Сервис Плюс', ['provider']);
const demoNeedsInfoAdminUser = createUser('Игорь Белов');
createMembership(demoNeedsInfoAdminUser.id, demoNeedsInfoProvider.id, 'provider_admin');
const needsInfoProfile = createProviderProfile(demoNeedsInfoProvider.id, 'needs_information');
needsInfoProfile.statusReason = 'Не подтверждён независимый канал связи с представителем';
seedVerificationCase(demoNeedsInfoProvider.id, 'requisites', 'approved', {
  source: 'ЕГРЮЛ (демонстрационная проверка)',
  checkedAt: new Date().toISOString(),
});
seedVerificationCase(demoNeedsInfoProvider.id, 'representative', 'needs_information', {
  decisionReason: 'Нужен обратный звонок по независимо найденному номеру компании',
});

const demoSuspendedProvider = createOrganization('Ремонт-Сервис (приостановлен)', ['provider']);
const demoSuspendedAdminUser = createUser('Павел Гусев');
createMembership(demoSuspendedAdminUser.id, demoSuspendedProvider.id, 'provider_admin');
const suspendedProfile = createProviderProfile(demoSuspendedProvider.id, 'suspended');
suspendedProfile.statusReason = 'Повторные обоснованные жалобы заказчиков — профиль приостановлен до проверки';

const demoRejectedProvider = createOrganization('ИП Отклонённый', ['provider']);
const demoRejectedAdminUser = createUser('Светлана Титова');
createMembership(demoRejectedAdminUser.id, demoRejectedProvider.id, 'provider_admin');
const rejectedProfile = createProviderProfile(demoRejectedProvider.id, 'rejected');
rejectedProfile.statusReason = 'Не удалось подтвердить реквизиты по официальному источнику';

const demoActiveProvider = createOrganization('Сервис-Холод Плюс', ['provider']);
demoActiveProvider.legal_form = 'ooo';
demoActiveProvider.inn = '7712345691';
demoActiveProvider.contact_name = 'Мария Осипова';
demoActiveProvider.contact_email = 'contact@service-holod.example';

const demoActiveProviderAdminUser = createUser('Марина Крылова');
const demoActiveProviderDispatcherUser = createUser('Олег Рябов');
createMembership(demoActiveProviderAdminUser.id, demoActiveProvider.id, 'provider_admin');
createMembership(demoActiveProviderDispatcherUser.id, demoActiveProvider.id, 'provider_dispatcher');

const activeProfile = createProviderProfile(demoActiveProvider.id, 'active');
activeProfile.acceptingNewRequests = true;
activeProfile.categoryIds = ['cat_fridge', 'cat_coffee'];
activeProfile.serviceAreas = [{ city_id: 'city_msk', district_ids: [] }];
activeProfile.visitTerms = 'Выезд по будням с 9 до 18, бесплатно в пределах МКАД.';
activeProfile.canProvideDocuments = true;
activeProfile.description = 'Ремонт и обслуживание холодильного оборудования и кофемашин.';
activeProfile.ratingOverride = 4.6;
activeProfile.reviewsCountOverride = 12;
activeProfile.uniqueCustomersOverride = 9;

function seedVerificationCase(
  organizationId: string,
  checkKind: VerificationCheckKind,
  decision: DbVerificationCase['decision'],
  extra: Partial<DbVerificationCase> = {},
): DbVerificationCase {
  const now = new Date().toISOString();
  const dbCase: DbVerificationCase = {
    id: nextId('vc'),
    organizationId,
    subjectType: checkKind === 'requisites' ? 'organization_details' : checkKind,
    checkKind,
    decision,
    decisionReason: null,
    source: null,
    evidenceNote: null,
    checkedAt: null,
    expiresAt: null,
    isDemo: true,
    createdAt: now,
    ...extra,
  };
  verificationCases.set(dbCase.id, dbCase);
  return dbCase;
}

seedVerificationCase(demoActiveProvider.id, 'requisites', 'approved', {
  source: 'ЕГРЮЛ (демонстрационная проверка)',
  checkedAt: new Date().toISOString(),
});
seedVerificationCase(demoActiveProvider.id, 'representative', 'approved', {
  source: 'Обратный звонок по независимо найденному номеру (демонстрационная проверка)',
  checkedAt: new Date().toISOString(),
});

const demoWarranty: DbWarrantyAuthorization = {
  id: nextId('wa'),
  guarantorKind: 'manufacturer',
  guarantorName: 'Bosch (демонстрационная проверка)',
  providerOrgId: demoActiveProvider.id,
  equipmentCategoryId: 'cat_fridge',
  brands: ['Bosch'],
  cityId: 'city_msk',
  validFrom: null,
  validUntil: null,
  status: 'active',
  isDemo: true,
};
warrantyAuthorizations.set(demoWarranty.id, demoWarranty);

const now0 = new Date().toISOString();
const confirmedBinding: DbServiceBinding = {
  id: nextId('sb'),
  equipmentId: seedEquipment.id,
  customerOrgId: demoCustomer.id,
  providerOrgId: demoActiveProvider.id,
  status: 'confirmed',
  statusReason: null,
  basis: 'warranty',
  contractNumber: 'Д-100',
  claimedContractNumber: null,
  personalContactName: null,
  personalContactPhone: null,
  guarantorKind: 'manufacturer',
  guarantorOrgId: null,
  warrantyAuthorizationId: demoWarranty.id,
  validFrom: null,
  validUntil: '2026-12-31',
  customerConfirmedAt: now0,
  providerConfirmedAt: now0,
  createdAt: now0,
};
serviceBindings.set(confirmedBinding.id, confirmedBinding);

const pendingRequestBinding: DbServiceBinding = {
  id: nextId('sb'),
  equipmentId: seedCoffeeEquipment.id,
  customerOrgId: demoCustomer.id,
  providerOrgId: demoActiveProvider.id,
  status: 'pending',
  statusReason: null,
  basis: 'service_contract',
  contractNumber: null,
  claimedContractNumber: 'Д-205',
  personalContactName: null,
  personalContactPhone: null,
  guarantorKind: null,
  guarantorOrgId: null,
  warrantyAuthorizationId: null,
  validFrom: null,
  validUntil: null,
  customerConfirmedAt: now0,
  providerConfirmedAt: null,
  createdAt: now0,
};
serviceBindings.set(pendingRequestBinding.id, pendingRequestBinding);

const contactOnlyBinding: DbServiceBinding = {
  id: nextId('sb'),
  equipmentId: seedCoffeeEquipment.id,
  customerOrgId: demoCustomer.id,
  providerOrgId: null,
  status: 'pending',
  statusReason: null,
  basis: 'preferred_provider',
  contractNumber: null,
  claimedContractNumber: null,
  personalContactName: 'Мастер Николай (частный)',
  personalContactPhone: '+7 900 111-22-33',
  guarantorKind: null,
  guarantorOrgId: null,
  warrantyAuthorizationId: null,
  validFrom: null,
  validUntil: null,
  customerConfirmedAt: now0,
  providerConfirmedAt: null,
  createdAt: now0,
};
serviceBindings.set(contactOnlyBinding.id, contactOnlyBinding);

const validBindingInvitation: DbBindingInvitation = {
  id: nextId('inv'),
  providerOrgId: demoActiveProvider.id,
  targetOrgId: demoCustomer.id,
  token: 'demo-sb-valid-token',
  tokenPrefix: 'demo-sb-',
  contractNumber: 'Д-300',
  basis: 'service_contract',
  validFrom: null,
  validUntil: null,
  customerInn: demoCustomerInn,
  customerName: demoCustomer.name,
  equipmentItems: [{ description: 'Холодильная витрина', serial_number: 'SN-001122', model: null }],
  equipmentIds: [],
  dbStatus: 'pending',
  expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
  createdAt: new Date().toISOString(),
};
bindingInvitations.set(validBindingInvitation.id, validBindingInvitation);

const expiredBindingInvitation: DbBindingInvitation = {
  id: nextId('inv'),
  providerOrgId: demoActiveProvider.id,
  targetOrgId: null,
  token: 'demo-sb-expired-token',
  tokenPrefix: 'demo-sb-',
  contractNumber: 'Д-301',
  basis: 'service_contract',
  validFrom: null,
  validUntil: null,
  customerInn: '7712345600',
  customerName: null,
  equipmentItems: [],
  equipmentIds: [],
  dbStatus: 'pending',
  expiresAt: new Date(Date.now() - 60 * 1000).toISOString(),
  createdAt: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(),
};
bindingInvitations.set(expiredBindingInvitation.id, expiredBindingInvitation);

const seedActiveKey: DbApiKey = {
  id: nextId('ik'),
  organizationId: demoActiveProvider.id,
  name: 'CRM продакшн',
  scopes: ['requests:read', 'requests:write', 'service_bindings:read'],
  status: 'active',
  keyPrefix: 'key_live_demo1',
  fullKey: 'key_live_demo1_seed_not_shown_again',
  createdAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
  rotatedAt: null,
  revokedAt: null,
  lastUsedAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
};
apiKeys.set(seedActiveKey.id, seedActiveKey);

const seedRevokedKey: DbApiKey = {
  id: nextId('ik'),
  organizationId: demoActiveProvider.id,
  name: 'Старый тестовый ключ',
  scopes: ['requests:read'],
  status: 'revoked',
  keyPrefix: 'key_live_demo0',
  fullKey: 'key_live_demo0_seed_not_shown_again',
  createdAt: new Date(Date.now() - 40 * 24 * 60 * 60 * 1000).toISOString(),
  rotatedAt: null,
  revokedAt: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
  lastUsedAt: null,
};
apiKeys.set(seedRevokedKey.id, seedRevokedKey);

const seedSubscription: DbWebhookSubscription = {
  id: nextId('whs'),
  organizationId: demoActiveProvider.id,
  url: 'https://crm.example-service.local/webhooks/repairbot',
  events: ['request.assigned', 'service_binding.changed'],
  status: 'active',
  createdAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
  disabledAt: null,
};
webhookSubscriptions.set(seedSubscription.id, seedSubscription);

const seedDeliveryDelivered: DbDelivery = {
  id: nextId('dlv'),
  organizationId: demoActiveProvider.id,
  eventId: nextId('evt'),
  eventType: 'service_binding.changed',
  subscriptionId: seedSubscription.id,
  state: 'delivered',
  inFlight: false,
  attemptCount: 1,
  lastHttpStatus: 200,
  lastError: null,
  lastAttemptAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  nextAttemptAt: null,
  expiresAt: new Date(Date.now() + 23 * 60 * 60 * 1000).toISOString(),
  createdAt: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
};
deliveries.set(seedDeliveryDelivered.id, seedDeliveryDelivered);

const seedDeliveryBlocked: DbDelivery = {
  id: nextId('dlv'),
  organizationId: demoActiveProvider.id,
  eventId: nextId('evt'),
  eventType: 'request.changed',
  subscriptionId: seedSubscription.id,
  state: 'blocked',
  inFlight: false,
  attemptCount: 12,
  lastHttpStatus: 500,
  lastError: 'Таймаут ответа сервера CRM',
  lastAttemptAt: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
  nextAttemptAt: null,
  expiresAt: new Date(Date.now() - 60 * 1000).toISOString(),
  createdAt: new Date(Date.now() - 26 * 60 * 60 * 1000).toISOString(),
};
deliveries.set(seedDeliveryBlocked.id, seedDeliveryBlocked);

const demoDualOrg = createOrganization('ООО «Два берега»', ['customer', 'provider']);
const demoDualManagerUser = createUser('Елена Двойнова');
const demoDualLocation = createLocation(demoDualOrg.id, {
  name: 'Цех на Садовой',
  city_id: 'city_msk',
  district_id: 'dist_msk_c',
  address: 'ул. Садовая, 5',
  timezone: 'Europe/Moscow',
});
createMembership(demoDualManagerUser.id, demoDualOrg.id, 'customer_manager', [demoDualLocation.id]);
createMembership(demoDualManagerUser.id, demoDualOrg.id, 'provider_admin');
createProviderProfile(demoDualOrg.id, 'draft');

const DEMO_KEYS: Record<string, string> = {
  dual_manager: demoDualManagerUser.id,
  customer_manager: demoManagerUser.id,
  customer_employee: demoEmployeeUser.id,
  provider_admin: demoProviderAdminUser.id,
  provider_dispatcher: demoDispatcherUser.id,
  provider_dispatcher_pending: demoPendingDispatcherUser.id,
  provider_active_admin: demoActiveProviderAdminUser.id,
  provider_active_dispatcher: demoActiveProviderDispatcherUser.id,
  provider_needs_info_admin: demoNeedsInfoAdminUser.id,
  provider_suspended_admin: demoSuspendedAdminUser.id,
  provider_rejected_admin: demoRejectedAdminUser.id,
  new_user: demoNewUser.id,
  operator: demoOperatorUser.id,
};

const operatorUserIds = tracked(new Set<string>([demoOperatorUser.id]));

export function isOperatorUser(userId: string): boolean {
  return operatorUserIds.has(userId);
}

export function findUserIdByDemoKey(key: string): string | null {
  return DEMO_KEYS[key] ?? null;
}

export function createSession(userId: string): DbSession {
  const session: DbSession = { token: nextId('tok'), user_id: userId };
  sessions.set(session.token, session);
  return session;
}

export function findSession(token: string | null): DbSession | null {
  if (!token) return null;
  return sessions.get(token) ?? null;
}

export function revokeSession(token: string): void {
  sessions.delete(token);
}

export function getUser(userId: string): DbUser | null {
  return users.get(userId) ?? null;
}

function toOrganizationRef(org: DbOrganization): OrganizationRef {
  return { id: org.id, name: org.name, kinds: org.kinds };
}

function verificationStatusOf(organizationId: string, kind: 'requisites' | 'representative'): string {
  const found = Array.from(verificationCases.values()).find(
    (c) => c.organizationId === organizationId && c.checkKind === kind,
  );
  if (found?.decision === 'approved') return 'verified';
  if (found?.decision === 'pending') return 'pending';
  return 'unverified';
}

function toOrganizationView(org: DbOrganization): Organization {
  return {
    id: org.id,
    name: org.name,
    kinds: org.kinds,
    legal_form: org.legal_form,
    inn: org.inn,
    contact_name: org.contact_name,
    representative_position: org.representative_position,
    contact_phone: org.contact_phone,
    contact_email: org.contact_email,
    details_verification_status: verificationStatusOf(org.id, 'requisites'),
    representative_verification_status: verificationStatusOf(org.id, 'representative'),
    created_at: org.created_at,
  };
}

function toMembershipView(m: DbMembership): Membership {
  const org = organizations.get(m.organization_id);
  if (!org) throw new Error('Организация не найдена');
  return {
    id: m.id,
    organization: toOrganizationRef(org),
    role: m.role,
    side: sideOfRole(m.role),
    status: m.status,
    location_ids: m.location_ids,
  };
}

export function getMembershipsForUser(userId: string): Membership[] {
  return Array.from(memberships.values())
    .filter((m) => m.user_id === userId && m.status !== 'revoked')
    .map(toMembershipView);
}

export function getOrganizationsForUser(userId: string): OrganizationRef[] {
  const seen = new Map<string, OrganizationRef>();
  for (const m of memberships.values()) {
    if (m.user_id !== userId || m.status === 'revoked' || seen.has(m.organization_id)) continue;
    const org = organizations.get(m.organization_id);
    if (org) seen.set(org.id, toOrganizationRef(org));
  }
  return Array.from(seen.values());
}

export function getActiveMembershipByOrgAndUser(userId: string, organizationId: string): DbMembership | null {
  return (
    Array.from(memberships.values()).find(
      (m) => m.user_id === userId && m.organization_id === organizationId && m.status === 'active',
    ) ?? null
  );
}

export function resolveActiveMembership(
  userId: string,
  membershipId: string | null,
  organizationId: string | null,
): DbMembership | 'not_found' | 'ambiguous' {
  const found = Array.from(memberships.values()).filter(
    (m) =>
      m.user_id === userId &&
      m.status === 'active' &&
      (membershipId === null || m.id === membershipId) &&
      (organizationId === null || m.organization_id === organizationId),
  );
  if (found.length === 0) return 'not_found';
  if (found.length > 1) return 'ambiguous';
  return found[0]!;
}

export function getCities(): Page<City> {
  return { items: cities, next_cursor: null };
}

export function getEquipmentCategories(): Page<EquipmentCategory> {
  return { items: equipmentCategories, next_cursor: null };
}

export function createOrganizationWithMembership(
  userId: string,
  input: CreateOrganizationInput,
): { organization: Organization; membership: Membership } {
  const org = createOrganization(input.name, [input.kind]);
  org.contact_phone = input.contact_phone;
  org.contact_name = input.contact_name ?? null;
  org.representative_position = input.representative_position ?? null;
  org.contact_email = input.contact_email ?? null;
  org.legal_form = input.legal_form ?? null;
  org.inn = input.inn ?? null;

  const role: Role = input.kind === 'customer' ? 'customer_manager' : 'provider_admin';
  let locationIds: string[] = [];
  if (input.kind === 'customer' && input.first_location) {
    const location = createLocation(org.id, {
      name: input.first_location.name,
      city_id: input.first_location.city_id,
      district_id: input.first_location.district_id,
      address: input.first_location.address,
      timezone: input.first_location.timezone,
    });
    locationIds = [location.id];
  }
  const membership = createMembership(userId, org.id, role, locationIds, 'active');
  return { organization: toOrganizationView(org), membership: toMembershipView(membership) };
}

export function getCurrentOrganization(organizationId: string): Organization | null {
  const org = organizations.get(organizationId);
  return org ? toOrganizationView(org) : null;
}

export type OrganizationUpdateError = 'INN_LOCKED' | 'REQUISITES_UNDER_REVIEW';

export function updateOrganization(
  organizationId: string,
  input: UpdateOrganizationInput,
): Organization | OrganizationUpdateError | null {
  const org = organizations.get(organizationId);
  if (!org) return null;
  const innChanged = input.inn !== undefined && (input.inn ?? null) !== org.inn;
  const legalFormChanged = input.legal_form !== undefined && (input.legal_form ?? null) !== org.legal_form;
  const status = verificationStatusOf(organizationId, 'requisites');
  if (innChanged && status === 'verified') return 'INN_LOCKED';
  if ((innChanged || legalFormChanged) && status === 'pending') return 'REQUISITES_UNDER_REVIEW';
  if (input.name) org.name = input.name;
  if (input.contact_name !== undefined) org.contact_name = input.contact_name ?? null;
  if (input.representative_position !== undefined) {
    org.representative_position = input.representative_position ?? null;
  }
  if (input.contact_phone !== undefined) org.contact_phone = input.contact_phone ?? null;
  if (input.contact_email !== undefined) org.contact_email = input.contact_email ?? null;
  if (input.legal_form !== undefined) org.legal_form = input.legal_form ?? null;
  if (input.inn !== undefined) org.inn = input.inn ?? null;
  return toOrganizationView(org);
}

export type ParticipationError = 'PARTICIPATION_EXISTS' | 'INN_ALREADY_VERIFIED';

export function addParticipation(
  userId: string,
  organizationId: string,
  input: ParticipationInput,
): { organization: Organization; membership: Membership } | ParticipationError | null {
  const org = organizations.get(organizationId);
  if (!org) return null;
  if (org.kinds.includes(input.kind)) return 'PARTICIPATION_EXISTS';
  if (org.inn) {
    const taken = Array.from(organizations.values()).some(
      (other) =>
        other.id !== org.id &&
        other.inn === org.inn &&
        other.kinds.includes(input.kind) &&
        verificationStatusOf(other.id, 'requisites') === 'verified',
    );
    if (taken) return 'INN_ALREADY_VERIFIED';
  }
  org.kinds = [...org.kinds, input.kind];
  let locationIds: string[] = [];
  if (input.kind === 'customer' && input.first_location) {
    const location = createLocation(org.id, {
      name: input.first_location.name,
      city_id: input.first_location.city_id,
      district_id: input.first_location.district_id,
      address: input.first_location.address,
      timezone: input.first_location.timezone,
    });
    locationIds = [location.id];
  }
  if (input.kind === 'provider' && !providerProfiles.has(org.id)) {
    const profile = createProviderProfile(org.id, 'draft');
    profile.providerKind = input.provider_kind ?? 'company';
  }
  const role: Role = input.kind === 'customer' ? 'customer_manager' : 'provider_admin';
  const membership = createMembership(userId, org.id, role, locationIds, 'active');
  return { organization: toOrganizationView(org), membership: toMembershipView(membership) };
}

export function listLocations(organizationId: string): Page<Location> {
  const items = Array.from(locations.values())
    .filter((l) => l.organization_id === organizationId)
    .map((l) => ({
      ...stripOrgId(l),
      equipment_count: Array.from(equipment.values()).filter((e) => e.location_id === l.id).length,
    }));
  return { items, next_cursor: null };
}

export function getLocation(id: string, organizationId: string): Location | null {
  const location = locations.get(id);
  if (!location || location.organization_id !== organizationId) return null;
  return stripOrgId(location);
}

export function createLocationForOrg(organizationId: string, input: LocationInput): Location {
  return stripOrgId(createLocation(organizationId, input));
}

export function updateLocation(
  id: string,
  organizationId: string,
  input: LocationUpdateInput,
): Location | null {
  const location = locations.get(id);
  if (!location || location.organization_id !== organizationId) return null;
  const updated = applyPatch(location, input);
  locations.set(id, updated);
  return stripOrgId(updated);
}

function locationIdsOfOrg(organizationId: string): Set<string> {
  return new Set(
    Array.from(locations.values())
      .filter((l) => l.organization_id === organizationId)
      .map((l) => l.id),
  );
}

export function listEquipment(organizationId: string, locationId?: string): Page<Equipment> {
  const orgLocationIds = locationIdsOfOrg(organizationId);
  const items = Array.from(equipment.values()).filter(
    (e) => orgLocationIds.has(e.location_id) && (!locationId || e.location_id === locationId),
  );
  return { items, next_cursor: null };
}

export function getEquipmentItem(id: string, organizationId: string): Equipment | null {
  const item = equipment.get(id);
  if (!item) return null;
  return locationIdsOfOrg(organizationId).has(item.location_id) ? item : null;
}

export function createEquipmentForOrg(organizationId: string, input: EquipmentInput): Equipment | null {
  if (!locationIdsOfOrg(organizationId).has(input.location_id)) return null;
  const item: Equipment = {
    id: nextId('eq'),
    location_id: input.location_id,
    equipment_category_id: input.equipment_category_id,
    brand: input.brand ?? null,
    model: input.model ?? null,
    serial_number: input.serial_number ?? null,
    notes: input.notes ?? null,
    created_at: new Date().toISOString(),
  };
  equipment.set(item.id, item);
  return item;
}

export function updateEquipmentItem(
  id: string,
  organizationId: string,
  input: EquipmentUpdateInput,
): Equipment | null {
  const item = getEquipmentItem(id, organizationId);
  if (!item) return null;
  const updated = applyPatch(item, input);
  equipment.set(id, updated);
  return updated;
}

export function listStaff(organizationId: string, side: Side): Page<StaffMember> {
  const items = Array.from(memberships.values())
    .filter((m) => m.organization_id === organizationId && m.status !== 'revoked' && sideOfRole(m.role) === side)
    .map((m) => {
      const user = users.get(m.user_id);
      if (!user) throw new Error('Пользователь не найден');
      return {
        id: m.id,
        user,
        role: m.role,
        side: sideOfRole(m.role),
        status: m.status,
        location_ids: m.location_ids,
        accepted_at: m.accepted_at ?? null,
        expected_name: m.expected_name ?? null,
      };
    });
  return { items, next_cursor: null };
}

export function hasActiveApiKey(organizationId: string): boolean {
  return Array.from(apiKeys.values()).some((k) => k.organizationId === organizationId && k.status === 'active');
}

export function confirmedContractNumber(
  equipmentId: string,
  customerOrgId: string,
  providerOrgId: string,
): string | null {
  const binding = Array.from(serviceBindings.values()).find(
    (b) =>
      b.equipmentId === equipmentId &&
      b.customerOrgId === customerOrgId &&
      b.providerOrgId === providerOrgId &&
      b.status === 'confirmed',
  );
  return binding ? (binding.contractNumber ?? binding.claimedContractNumber) : null;
}

export function getOrganizationName(organizationId: string): string | null {
  return organizations.get(organizationId)?.name ?? null;
}

export function integrationClientOrgName(clientId: string): string | null {
  const key = apiKeys.get(clientId);
  return key ? getOrganizationName(key.organizationId) : null;
}

export function activeApiKeyId(organizationId: string): string | null {
  return Array.from(apiKeys.values()).find((k) => k.organizationId === organizationId && k.status === 'active')?.id ?? null;
}

export function getOrganizationPhone(organizationId: string): string | null {
  return organizations.get(organizationId)?.contact_phone ?? null;
}

export function firstManagerName(organizationId: string): string | null {
  const manager = Array.from(memberships.values()).find(
    (m) => m.organization_id === organizationId && m.role === 'customer_manager' && m.status === 'active',
  );
  return manager ? (users.get(manager.user_id)?.display_name ?? null) : null;
}

export function approveMembership(organizationId: string, membershipId: string, side: Side): Membership | null {
  const membership = memberships.get(membershipId);
  if (
    !membership ||
    membership.organization_id !== organizationId ||
    sideOfRole(membership.role) !== side ||
    membership.status !== 'pending'
  ) {
    return null;
  }
  membership.status = 'active';
  return toMembershipView(membership);
}

export function revokeMembership(
  actor: DbMembership,
  membershipId: string,
): Membership | 'not_found' | 'already_revoked' | 'last_manager' | 'self' {
  const membership = memberships.get(membershipId);
  if (
    !membership ||
    membership.organization_id !== actor.organization_id ||
    sideOfRole(membership.role) !== sideOfRole(actor.role)
  ) {
    return 'not_found';
  }
  if (membership.status === 'revoked') return 'already_revoked';
  if (membership.role === actor.role) {
    const others = Array.from(memberships.values()).filter(
      (m) =>
        m.organization_id === actor.organization_id &&
        m.role === actor.role &&
        m.status === 'active' &&
        m.id !== membership.id,
    );
    if (others.length === 0) return 'last_manager';
  }
  if (membership.id === actor.id) return 'self';
  membership.status = 'revoked';
  membership.location_ids = [];
  return toMembershipView(membership);
}

export function setMembershipLocations(
  organizationId: string,
  membershipId: string,
  locationIds: string[],
): Membership | null {
  const membership = memberships.get(membershipId);
  if (!membership || membership.organization_id !== organizationId || membership.status === 'revoked') {
    return null;
  }
  membership.location_ids = locationIds;
  return toMembershipView(membership);
}

function invitationState(invitation: DbInvitation): InvitationState {
  if (invitation.dbStatus === 'accepted') return 'used';
  if (invitation.dbStatus === 'revoked') return 'revoked';
  if (new Date(invitation.expires_at).getTime() <= Date.now()) return 'expired';
  return 'active';
}

function toInvitationView(invitation: DbInvitation): Invitation {
  return {
    id: invitation.id,
    role: invitation.role,
    state: invitationState(invitation),
    expires_at: invitation.expires_at,
    location_ids: invitation.location_ids,
    token_prefix: invitation.token_prefix,
    created_at: invitation.created_at,
    named: invitation.recipient_max_user_id !== null,
    recipient_name: invitation.recipient_name,
  };
}

export function listInvitations(organizationId: string, side: Side): Page<Invitation> {
  const items = Array.from(invitations.values())
    .filter((i) => i.organization_id === organizationId && sideOfRole(i.role) === side)
    .map(toInvitationView);
  return { items, next_cursor: null };
}

export function createInvitation(
  organizationId: string,
  input: CreateInvitationInput,
  inviterName: string | null = null,
): InvitationIssued {
  const now = new Date();
  const expires = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const token = `${nextId('tkn')}${Math.random().toString(36).slice(2, 10)}`;
  const invitation: DbInvitation = {
    id: nextId('inv'),
    organization_id: organizationId,
    role: input.role,
    location_ids: PROVIDER_ROLES.includes(input.role) ? [] : (input.location_ids ?? []),
    token,
    token_prefix: token.slice(0, 6),
    expires_at: expires.toISOString(),
    inviter_name: inviterName,
    dbStatus: 'pending',
    created_at: now.toISOString(),
    recipient_max_user_id: input.recipient_max_user_id?.trim() || null,
    recipient_name: input.recipient_name?.trim() || null,
  };
  invitations.set(invitation.id, invitation);
  return {
    ...toInvitationView(invitation),
    token,
    webapp_link: `https://max.ru/repairbot/webapp?startapp=inv_${token}`,
    bot_link: `https://max.ru/repairbot?start=inv_${token}`,
  };
}

export function revokeInvitation(organizationId: string, id: string): Invitation | 'invalid' | null {
  const invitation = invitations.get(id);
  if (!invitation || invitation.organization_id !== organizationId) return null;
  if (invitation.dbStatus !== 'pending') return 'invalid';
  invitation.dbStatus = 'revoked';
  return toInvitationView(invitation);
}

function findInvitationByToken(token: string): DbInvitation | null {
  return Array.from(invitations.values()).find((i) => i.token === token) ?? null;
}

export function previewInvitation(token: string): InvitationPreview | null {
  const invitation = findInvitationByToken(token);
  if (!invitation) return null;
  const org = organizations.get(invitation.organization_id);
  if (!org) return null;
  const state = invitationState(invitation);
  if (state !== 'active') {
    return {
      organization_name: null,
      role: null,
      expires_at: null,
      state,
      inviter_name: null,
      location_names: [],
    };
  }
  return {
    organization_name: org.name,
    role: invitation.role,
    expires_at: invitation.expires_at,
    state: invitationState(invitation),
    inviter_name: invitation.inviter_name,
    location_names: invitation.location_ids
      .map((id) => locations.get(id))
      .filter((l) => l !== undefined && l.organization_id === invitation.organization_id)
      .map((l) => l!.name)
      .sort(),
  };
}

export function acceptInvitation(token: string, userId: string): Membership | 'invalid' | 'foreign' | null {
  const invitation = findInvitationByToken(token);
  if (!invitation) return null;
  if (invitationState(invitation) !== 'active') return 'invalid';
  const named = invitation.recipient_max_user_id !== null;
  if (named && invitation.recipient_max_user_id !== userId) return 'foreign';

  invitation.dbStatus = 'accepted';
  const role = invitation.role;
  const status: MembershipStatus = named ? 'active' : 'pending';
  const membership = createMembership(userId, invitation.organization_id, role, invitation.location_ids, status);
  membership.accepted_at = new Date().toISOString();
  membership.expected_name = invitation.recipient_name;
  return toMembershipView(membership);
}

const SPECIALIZATION_DISCLAIMER = 'Со слов исполнителя';

export const PORTFOLIO_MAX_IMAGES = 10;

const BADGE_TEXTS: Record<'requisites' | 'representative', [string, string, string]> = {
  requisites: [
    'Реквизиты проверены',
    'Организация, ИП или статус НПД найдены в официальном источнике на дату проверки',
    'Не подтверждает владение аккаунтом этой организацией',
  ],
  representative: [
    'Представитель подтверждён',
    'Установлена связь аккаунта с действительным представителем компании',
    'Не подтверждает право выполнять ремонт любого бренда',
  ],
};

const BINDING_STATUS_TEXTS: Record<BindingStatus, string> = {
  pending: 'Ожидает подтверждения второй стороной',
  confirmed: 'Обслуживание подтверждено компанией',
  rejected: 'Компания не подтвердила связь',
  revoked: 'Связь прекращена',
};

const CONTACT_ONLY_TEXT =
  'Личный контакт. Платформа не подтверждала обслуживание и не доставляет обращения этой компании';

function equipmentIdsOfOrg(organizationId: string): Set<string> {
  const orgLocationIds = locationIdsOfOrg(organizationId);
  return new Set(
    Array.from(equipment.values())
      .filter((e) => orgLocationIds.has(e.location_id))
      .map((e) => e.id),
  );
}

function getOrgVerificationCases(organizationId: string): DbVerificationCase[] {
  return Array.from(verificationCases.values()).filter((c) => c.organizationId === organizationId);
}

function toBadgeView(kind: 'requisites' | 'representative', dbCase: DbVerificationCase | undefined): VerificationBadge {
  const [title, explanation, limitation] = BADGE_TEXTS[kind];
  const confirmed = dbCase?.decision === 'approved';
  return {
    kind,
    confirmed,
    title,
    explanation,
    limitation,
    source: confirmed ? (dbCase?.source ?? null) : null,
    checked_at: confirmed ? (dbCase?.checkedAt ?? null) : null,
    valid_until: confirmed ? (dbCase?.expiresAt ?? null) : null,
    is_demo: confirmed ? Boolean(dbCase?.isDemo) : false,
  };
}

function getBadges(organizationId: string): VerificationBadge[] {
  const cases = getOrgVerificationCases(organizationId);
  const byKind = new Map(cases.map((c) => [c.checkKind, c]));
  return [
    toBadgeView('requisites', byKind.get('requisites')),
    toBadgeView('representative', byKind.get('representative')),
  ];
}

function toProviderCategoryViews(categoryIds: string[]): ProviderCategory[] {
  return categoryIds
    .map((id) => equipmentCategories.find((c) => c.id === id))
    .filter((c): c is EquipmentCategory => Boolean(c))
    .map((c) => ({ id: c.id, code: c.code, name: c.name }));
}

function toServiceAreaViews(areas: { city_id: string; district_ids: string[] }[]): ProviderServiceArea[] {
  const views: ProviderServiceArea[] = [];
  for (const area of areas) {
    const city = cities.find((c) => c.id === area.city_id);
    if (!city) continue;
    if (area.district_ids.length === 0) {
      views.push({ city_id: city.id, city_name: city.name, district_id: null, district_name: null });
      continue;
    }
    for (const districtId of area.district_ids) {
      const district = city.districts.find((d) => d.id === districtId);
      views.push({
        city_id: city.id,
        city_name: city.name,
        district_id: districtId,
        district_name: district?.name ?? null,
      });
    }
  }
  return views;
}

function toBrandRestrictionViews(
  restrictions: { equipment_category_id: string; brands: string[] }[],
): ProviderBrandRestriction[] {
  const views: ProviderBrandRestriction[] = [];
  for (const r of restrictions) {
    for (const brand of r.brands) views.push({ equipment_category_id: r.equipment_category_id, brand });
  }
  return views;
}

function toWarrantyView(w: DbWarrantyAuthorization): WarrantyAuthorization {
  return {
    id: w.id,
    guarantor_kind: w.guarantorKind,
    guarantor_name: w.guarantorName,
    provider_organization_id: w.providerOrgId,
    equipment_category_id: w.equipmentCategoryId,
    brands: w.brands,
    city_id: w.cityId,
    valid_from: w.validFrom,
    valid_until: w.validUntil,
    status: w.status,
    is_demo: w.isDemo,
  };
}

function getWarrantyAuthorizations(providerOrgId: string): DbWarrantyAuthorization[] {
  return Array.from(warrantyAuthorizations.values()).filter((w) => w.providerOrgId === providerOrgId);
}

export function listAllWarrantyAuthorizations(providerOrgId?: string): WarrantyAuthorization[] {
  return Array.from(warrantyAuthorizations.values())
    .filter((w) => !providerOrgId || w.providerOrgId === providerOrgId)
    .map(toWarrantyView);
}

export interface WarrantyAuthorizationCreateInput {
  provider_organization_id: string;
  guarantor_kind: GuarantorKind;
  guarantor_name: string | null;
  brands: string[];
  equipment_category_id: string | null;
  city_id: string | null;
  valid_until: string | null;
}

export function createWarrantyAuthorization(input: WarrantyAuthorizationCreateInput): WarrantyAuthorization {
  const record: DbWarrantyAuthorization = {
    id: nextId('wa'),
    guarantorKind: input.guarantor_kind,
    guarantorName: input.guarantor_name,
    providerOrgId: input.provider_organization_id,
    equipmentCategoryId: input.equipment_category_id,
    brands: input.brands,
    cityId: input.city_id,
    validFrom: null,
    validUntil: input.valid_until,
    status: 'active',
    isDemo: false,
  };
  warrantyAuthorizations.set(record.id, record);
  return toWarrantyView(record);
}

export function revokeWarrantyAuthorization(id: string): WarrantyAuthorization | null {
  const record = warrantyAuthorizations.get(id);
  if (!record) return null;
  record.status = 'revoked';
  return toWarrantyView(record);
}

function toProviderProfileView(profile: DbProviderProfile): ProviderProfile {
  const org = organizations.get(profile.organizationId);
  if (!org) throw new Error('Организация не найдена');
  return {
    id: profile.id,
    organization_id: profile.organizationId,
    name: org.name,
    provider_kind: profile.providerKind,
    legal_form: org.legal_form,
    inn: org.inn,
    contact_name: org.contact_name,
    representative_position: org.representative_position,
    contact_phone: org.contact_phone,
    contact_email: org.contact_email,
    status: profile.status,
    status_reason: profile.statusReason,
    accepting_new_requests: profile.acceptingNewRequests,
    visit_terms: profile.visitTerms,
    visit_price_from_minor: profile.visitPriceFromMinor,
    can_provide_documents: profile.canProvideDocuments,
    description: profile.description,
    specialization_disclaimer: SPECIALIZATION_DISCLAIMER,
    categories: toProviderCategoryViews(profile.categoryIds),
    service_areas: toServiceAreaViews(profile.serviceAreas),
    brand_restrictions: toBrandRestrictionViews(profile.brandRestrictions),
    verification: getBadges(profile.organizationId),
    portfolio_max_images: PORTFOLIO_MAX_IMAGES,
    rating: profile.ratingOverride,
    rating_label: profile.ratingOverride === null ? 'Мало отзывов' : null,
    reviews_count: profile.reviewsCountOverride,
    unique_customers: profile.uniqueCustomersOverride,
    appeal: profile.appeal,
    created_at: profile.createdAt,
    updated_at: profile.updatedAt,
  };
}

function toPublicProfileView(profile: DbProviderProfile): ProviderPublicProfile {
  const org = organizations.get(profile.organizationId);
  if (!org) throw new Error('Организация не найдена');
  return {
    id: profile.organizationId,
    name: org.name,
    provider_kind: profile.providerKind,
    legal_form: org.legal_form,
    categories: toProviderCategoryViews(profile.categoryIds),
    service_areas: toServiceAreaViews(profile.serviceAreas),
    brand_restrictions: toBrandRestrictionViews(profile.brandRestrictions),
    visit_terms: profile.visitTerms,
    visit_price_from_minor: profile.visitPriceFromMinor,
    can_provide_documents: profile.canProvideDocuments,
    description: profile.description,
    specialization_disclaimer: SPECIALIZATION_DISCLAIMER,
    accepting_new_requests: profile.acceptingNewRequests,
    verification: getBadges(profile.organizationId),
    warranty_authorizations: getWarrantyAuthorizations(profile.organizationId).map(toWarrantyView),
    rating: profile.ratingOverride,
    rating_label: profile.ratingOverride === null ? 'Мало отзывов' : null,
    reviews_count: profile.reviewsCountOverride,
    unique_customers: profile.uniqueCustomersOverride,
    gallery: profile.publishedGallery,
    gallery_items: profile.publishedGallery.map((id) => ({ id, caption: galleryCaptions.get(id) ?? null })),
  };
}

function toCatalogItemView(profile: DbProviderProfile): ProviderCatalogItem {
  const org = organizations.get(profile.organizationId);
  if (!org) throw new Error('Организация не найдена');
  const badges = getBadges(profile.organizationId);
  return {
    id: profile.organizationId,
    name: org.name,
    provider_kind: profile.providerKind,
    categories: toProviderCategoryViews(profile.categoryIds),
    service_areas: toServiceAreaViews(profile.serviceAreas),
    accepting_new_requests: profile.acceptingNewRequests,
    details_verified: badges.find((b) => b.kind === 'requisites')?.confirmed ?? false,
    representative_verified: badges.find((b) => b.kind === 'representative')?.confirmed ?? false,
    rating: profile.ratingOverride,
    rating_label: profile.ratingOverride === null ? 'Мало отзывов' : null,
    reviews_count: profile.reviewsCountOverride,
    unique_customers: profile.uniqueCustomersOverride,
  };
}

export function getProviderProfile(organizationId: string): ProviderProfile | null {
  const profile = providerProfiles.get(organizationId);
  return profile ? toProviderProfileView(profile) : null;
}

export interface OfferProviderSummary {
  id: string;
  display_name: string;
  verification_marks: string[];
  rating: number | null;
  rating_label: string | null;
  unique_reviewer_orgs_count: number;
  reviews_count: number;
}

export function getOfferProviderSummary(organizationId: string): OfferProviderSummary | null {
  const org = organizations.get(organizationId);
  const profile = providerProfiles.get(organizationId);
  if (!org || !profile) return null;
  return {
    id: organizationId,
    display_name: org.name,
    verification_marks: getBadges(organizationId)
      .filter((b) => b.confirmed)
      .map((b) => b.kind),
    rating: profile.ratingOverride,
    rating_label: profile.ratingOverride === null ? 'Мало отзывов' : null,
    unique_reviewer_orgs_count: profile.uniqueCustomersOverride,
    reviews_count: profile.reviewsCountOverride,
  };
}

export function updateProviderProfile(
  organizationId: string,
  patch: ProviderProfileUpdateInput,
): ProviderProfile | 'not_editable' | 'requisites_locked' | null {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return null;
  if (!canEditProfileFields(profile.status)) return 'not_editable';

  const touchesRequisites =
    patch.provider_kind != null ||
    patch.legal_form != null ||
    patch.inn != null ||
    patch.contact_name != null ||
    patch.representative_position != null ||
    patch.contact_phone != null ||
    patch.contact_email != null;
  if (touchesRequisites && !canEditRequisites(profile.status)) return 'requisites_locked';

  const org = organizations.get(organizationId);
  if (!org) return null;

  if (patch.provider_kind != null) profile.providerKind = patch.provider_kind as ProviderKind;
  if (patch.legal_form != null) org.legal_form = patch.legal_form;
  if (patch.inn != null) org.inn = patch.inn;
  if (patch.contact_name != null) org.contact_name = patch.contact_name;
  if (patch.representative_position !== undefined) {
    org.representative_position = patch.representative_position ?? null;
  }
  if (patch.contact_phone != null) org.contact_phone = patch.contact_phone;
  if (patch.contact_email != null) org.contact_email = patch.contact_email;
  if (patch.visit_terms != null) profile.visitTerms = patch.visit_terms;
  if (patch.visit_price_from_minor !== undefined) {
    profile.visitPriceFromMinor = patch.visit_price_from_minor ?? null;
  }
  if (patch.can_provide_documents != null) profile.canProvideDocuments = patch.can_provide_documents;
  if (patch.description != null) profile.description = patch.description;
  if (patch.category_ids != null) profile.categoryIds = patch.category_ids;
  if (patch.service_areas != null) {
    profile.serviceAreas = patch.service_areas.map((a) => ({
      city_id: a.city_id,
      district_ids: a.district_ids ?? [],
    }));
  }
  if (patch.brand_restrictions != null) {
    profile.brandRestrictions = patch.brand_restrictions.map((r) => ({
      equipment_category_id: r.equipment_category_id,
      brands: r.brands ?? [],
    }));
  }
  profile.updatedAt = new Date().toISOString();
  return toProviderProfileView(profile);
}

export function appealProviderProfile(
  organizationId: string,
  text: string,
): Complaint | 'not_allowed' | 'already_open' | null {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return null;
  if (profile.status !== 'suspended' && profile.status !== 'rejected') return 'not_allowed';
  if (profile.appeal?.status === 'pending') return 'already_open';
  const now = new Date().toISOString();
  const id = nextId('mc');
  profile.appeal = {
    id,
    status: 'pending',
    decision: null,
    decision_reason: null,
    created_at: now,
    resolved_at: null,
  };
  return {
    id,
    subject_type: 'provider_profile',
    status: 'pending',
    description: text,
    decision_reason: null,
    appeal_status: 'pending',
    created_at: now,
    updated_at: now,
  };
}

export function resolveProviderProfileAppeal(
  organizationId: string,
  appealId: string,
  decision: string,
  reason: string | null,
): void {
  const profile = providerProfiles.get(organizationId);
  if (!profile?.appeal || profile.appeal.id !== appealId) return;
  profile.appeal = {
    ...profile.appeal,
    status: 'resolved',
    decision,
    decision_reason: reason,
    resolved_at: new Date().toISOString(),
  };
}

export function submitProviderProfile(organizationId: string): ProviderProfile | 'invalid' | null {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return null;
  if (!canSubmitProfile(profile.status)) return 'invalid';
  profile.status = 'pending_review';
  profile.updatedAt = new Date().toISOString();
  ensureVerificationCase(organizationId, 'requisites');
  ensureVerificationCase(organizationId, 'representative');
  return toProviderProfileView(profile);
}

function ensureVerificationCase(
  organizationId: string,
  checkKind: 'requisites' | 'representative',
): DbVerificationCase {
  const existing = getOrgVerificationCases(organizationId).find((c) => c.checkKind === checkKind);
  if (existing) {
    if (existing.decision !== 'approved') existing.decision = 'pending';
    return existing;
  }
  return seedVerificationCase(organizationId, checkKind, 'pending');
}

export function setProviderAccepting(organizationId: string, accepting: boolean): ProviderProfile | 'invalid' | null {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return null;
  if (profile.status !== 'active') return 'invalid';
  profile.acceptingNewRequests = accepting;
  profile.updatedAt = new Date().toISOString();
  return toProviderProfileView(profile);
}

const SEARCH_PUNCTUATION = /[«»"'.,()/–—-]+/g;

function matchesSearch(profile: DbProviderProfile, q: string | undefined): boolean {
  if (!q) return true;
  const org = organizations.get(profile.organizationId);
  if (!org) return false;
  const value = q.trim();
  const digits = value.replace(/\D/g, '');
  if (digits && digits === value.replace(/ /g, '')) {
    return (digits.length === 10 || digits.length === 12) && org.inn === digits;
  }
  const words = value.toLowerCase().replace(SEARCH_PUNCTUATION, ' ').split(/\s+/).filter(Boolean);
  if (words.length === 0) return false;
  const name = ` ${org.name.toLowerCase().replace(SEARCH_PUNCTUATION, ' ')}`;
  return name.includes(` ${words.join(' ')}`);
}

export function listProviderCatalog(filters: {
  categoryId?: string;
  cityId?: string;
  districtId?: string;
  q?: string;
}): Page<ProviderCatalogItem> {
  const items = filterCatalog(filters).map(toCatalogItemView);
  return { items, next_cursor: null };
}

export function countProviderCatalog(filters: { categoryId?: string; cityId?: string; districtId?: string }): number {
  return filterCatalog(filters).filter((p) => p.acceptingNewRequests).length;
}

function filterCatalog(filters: {
  categoryId?: string;
  cityId?: string;
  districtId?: string;
  q?: string;
}): DbProviderProfile[] {
  return Array.from(providerProfiles.values())
    .filter((p) => p.status === 'active')
    .filter((p) => matchesSearch(p, filters.q))
    .filter((p) => !filters.categoryId || p.categoryIds.includes(filters.categoryId))
    .filter(
      (p) =>
        !filters.cityId ||
        p.serviceAreas.some(
          (a) =>
            a.city_id === filters.cityId &&
            (!filters.districtId || a.district_ids.length === 0 || a.district_ids.includes(filters.districtId)),
        ),
    );
}

export function listAllProviderProfilesForOperator(status?: string): ProviderProfile[] {
  return Array.from(providerProfiles.values())
    .filter((p) => !status || p.status === status)
    .map(toProviderProfileView);
}

export function operatorSetProfileStatus(
  organizationId: string,
  status: 'suspended' | 'active',
  reason: string,
): ProviderProfile | null {
  const profile = providerProfiles.get(organizationId);
  if (!profile) return null;
  profile.status = status;
  profile.statusReason = reason;
  profile.updatedAt = new Date().toISOString();
  return toProviderProfileView(profile);
}

export interface VerificationCaseOperatorRow extends VerificationCase {
  organization_id: string;
  organization_name: string;
  organization_inn: string | null;
}

export function listAllVerificationCasesForOperator(decision?: string): VerificationCaseOperatorRow[] {
  return Array.from(verificationCases.values())
    .filter((c) => !decision || c.decision === decision)
    .map((c) => {
      const org = organizations.get(c.organizationId);
      return {
        ...toVerificationCaseView(c),
        organization_id: c.organizationId,
        organization_name: org?.name ?? '',
        organization_inn: org?.inn ?? null,
      };
    });
}

export function getVerificationCaseForOperator(caseId: string): VerificationCaseOperatorRow | null {
  const c = verificationCases.get(caseId);
  if (!c) return null;
  const org = organizations.get(c.organizationId);
  return { ...toVerificationCaseView(c), organization_id: c.organizationId, organization_name: org?.name ?? '', organization_inn: org?.inn ?? null };
}

export function decideVerificationCaseByOperator(
  caseId: string,
  decision: 'approved' | 'rejected' | 'needs_information',
  reason: string,
  source: string | null,
  expiresAt: string | null,
): VerificationCaseOperatorRow | null {
  const c = verificationCases.get(caseId);
  if (!c) return null;
  c.decision = decision;
  c.decisionReason = reason;
  c.source = source;
  c.checkedAt = new Date().toISOString();
  c.expiresAt = expiresAt;
  if (c.checkKind !== 'customer_representative') {
    const cases = getOrgVerificationCases(c.organizationId);
    const allApproved = cases.length > 0 && cases.every((item) => item.decision === 'approved');
    const profile = providerProfiles.get(c.organizationId);
    if (profile) {
      if (allApproved && profile.status === 'pending_review') profile.status = 'active';
      if (decision === 'needs_information' && profile.status === 'pending_review') profile.status = 'needs_information';
      if (decision === 'rejected' && profile.status === 'pending_review') profile.status = 'rejected';
    }
  }
  const org = organizations.get(c.organizationId);
  return { ...toVerificationCaseView(c), organization_id: c.organizationId, organization_name: org?.name ?? '', organization_inn: org?.inn ?? null };
}

export function getPublicProviderProfile(organizationId: string): ProviderPublicProfile | null {
  const profile = providerProfiles.get(organizationId);
  return profile ? toPublicProfileView(profile) : null;
}

export function listProviderReviews(): Page<PublicReview> {
  return { items: [], next_cursor: null };
}

function toVerificationCaseView(c: DbVerificationCase): VerificationCase {
  return {
    id: c.id,
    subject_type: c.subjectType,
    check_kind: c.checkKind,
    decision: c.decision,
    decision_reason: c.decisionReason,
    source: c.source,
    evidence_note: c.evidenceNote,
    checked_at: c.checkedAt,
    expires_at: c.expiresAt,
    is_demo: c.isDemo && c.decision === 'approved',
    created_at: c.createdAt,
  };
}

export function listVerificationCases(organizationId: string): VerificationCase[] {
  return getOrgVerificationCases(organizationId).map(toVerificationCaseView);
}

export function submitVerificationInformation(organizationId: string, input: VerificationInformationInput): void {
  void input;
  for (const c of getOrgVerificationCases(organizationId)) {
    if (c.decision === 'needs_information') c.decision = 'pending';
  }
  const profile = providerProfiles.get(organizationId);
  if (profile && profile.status === 'needs_information') {
    profile.status = 'pending_review';
    profile.updatedAt = new Date().toISOString();
  }
}

function bindingStatusExplanation(b: DbServiceBinding): string {
  if (b.providerOrgId === null) return CONTACT_ONLY_TEXT;
  return BINDING_STATUS_TEXTS[b.status];
}

function toServiceBindingView(b: DbServiceBinding): ServiceBinding {
  const provider = b.providerOrgId ? (organizations.get(b.providerOrgId) ?? null) : null;
  const guarantor = b.guarantorOrgId ? (organizations.get(b.guarantorOrgId) ?? null) : null;
  const warranty = b.warrantyAuthorizationId ? warrantyAuthorizations.get(b.warrantyAuthorizationId) : undefined;
  return {
    id: b.id,
    equipment_id: b.equipmentId,
    status: b.status,
    status_explanation: bindingStatusExplanation(b),
    status_reason: b.statusReason,
    is_contact_only: b.providerOrgId === null,
    basis: b.basis,
    contract_number: b.contractNumber ?? b.claimedContractNumber,
    invitation_item_index: b.invitationItemIndex ?? null,
    provider: provider
      ? { organization_id: provider.id, name: provider.name, is_platform_member: true }
      : { organization_id: null, name: b.personalContactName ?? 'Контакт', is_platform_member: false },
    guarantor_kind: b.guarantorKind,
    guarantor_name: guarantor?.name ?? b.statedGuarantorName ?? null,
    guarantor_stated_by_provider: b.guarantorKind !== null && !b.warrantyAuthorizationId,
    warranty_authorization: warranty ? toWarrantyView(warranty) : null,
    valid_from: b.validFrom,
    valid_until: b.validUntil,
    customer_confirmed_at: b.customerConfirmedAt,
    provider_confirmed_at: b.providerConfirmedAt,
    created_at: b.createdAt,
    contact_name: b.providerOrgId === null ? b.personalContactName : null,
    contact_phone: b.providerOrgId === null ? b.personalContactPhone : null,
    invitation_item_description: b.invitationItemDescription ?? null,
  };
}

function toProviderBindingView(b: DbServiceBinding): ProviderBinding {
  const customer = organizations.get(b.customerOrgId);
  if (!customer) throw new Error('Организация не найдена');
  const item = equipment.get(b.equipmentId);
  return {
    id: b.id,
    status: b.status,
    status_explanation: bindingStatusExplanation(b),
    status_reason: b.statusReason,
    basis: b.basis,
    contract_number: b.contractNumber ?? b.claimedContractNumber,
    customer: { organization_id: customer.id, name: customer.name, is_platform_member: true },
    equipment: item
      ? {
          id: item.id,
          equipment_category_id: item.equipment_category_id,
          brand: item.brand,
          model: item.model,
          serial_number: item.serial_number,
        }
      : null,
    valid_from: b.validFrom,
    valid_until: b.validUntil,
    created_at: b.createdAt,
  };
}

export function listBindings(
  organizationId: string,
  side: 'customer' | 'provider',
  filters: { equipmentId?: string; status?: string },
): Page<ServiceBinding | ProviderBinding> {
  const all = Array.from(serviceBindings.values()).filter((b) =>
    side === 'customer' ? b.customerOrgId === organizationId : b.providerOrgId === organizationId,
  );
  const filtered = all
    .filter((b) => !filters.equipmentId || b.equipmentId === filters.equipmentId)
    .filter((b) => !filters.status || b.status === filters.status);
  const items = filtered.map((b) => (side === 'customer' ? toServiceBindingView(b) : toProviderBindingView(b)));
  return { items, next_cursor: null };
}

function getBindingForActor(
  actorOrgId: string,
  bindingId: string,
): { binding: DbServiceBinding; side: 'customer' | 'provider' } | null {
  const binding = serviceBindings.get(bindingId);
  if (!binding) return null;
  if (binding.customerOrgId === actorOrgId) return { binding, side: 'customer' };
  if (binding.providerOrgId === actorOrgId) return { binding, side: 'provider' };
  return null;
}

export function getBindingView(actorOrgId: string, bindingId: string): ServiceBinding | ProviderBinding | null {
  const found = getBindingForActor(actorOrgId, bindingId);
  if (!found) return null;
  return found.side === 'customer' ? toServiceBindingView(found.binding) : toProviderBindingView(found.binding);
}

const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000;
const RATE_LIMIT_MAX_ATTEMPTS = 5;

function checkRequestRate(
  customerOrgId: string,
  providerOrgId: string,
): { ok: true; remaining: number } | { ok: false; retryAfterSeconds: number } {
  const key = `${customerOrgId}:${providerOrgId}`;
  const now = Date.now();
  const attempts = (bindingRequestAttempts.get(key) ?? []).filter((t) => now - t < RATE_LIMIT_WINDOW_MS);
  if (attempts.length >= RATE_LIMIT_MAX_ATTEMPTS) {
    bindingRequestAttempts.set(key, attempts);
    const oldest = Math.min(...attempts);
    return { ok: false, retryAfterSeconds: Math.max(1, Math.ceil((oldest + RATE_LIMIT_WINDOW_MS - now) / 1000)) };
  }
  attempts.push(now);
  bindingRequestAttempts.set(key, attempts);
  return { ok: true, remaining: RATE_LIMIT_MAX_ATTEMPTS - attempts.length };
}

export function requestBinding(
  customerOrgId: string,
  input: BindingRequestInput,
): BindingRequestAccepted | { rateLimited: true; retryAfterSeconds: number } | 'not_found' {
  const providerProfile = providerProfiles.get(input.provider_organization_id);
  if (!providerProfile || providerProfile.status !== 'active') return 'not_found';
  const rate = checkRequestRate(customerOrgId, input.provider_organization_id);
  if (!rate.ok) return { rateLimited: true, retryAfterSeconds: rate.retryAfterSeconds };

  const validEquipmentIds = equipmentIdsOfOrg(customerOrgId);
  const now = new Date().toISOString();
  for (const eqId of input.equipment_ids) {
    if (!validEquipmentIds.has(eqId)) continue;
    const binding: DbServiceBinding = {
      id: nextId('sb'),
      equipmentId: eqId,
      customerOrgId,
      providerOrgId: input.provider_organization_id,
      status: 'pending',
      statusReason: null,
      basis: (input.basis as BindingBasis) || 'service_contract',
      contractNumber: null,
      claimedContractNumber: input.contract_number,
      personalContactName: null,
      personalContactPhone: null,
      guarantorKind: null,
      guarantorOrgId: null,
      warrantyAuthorizationId: null,
      validFrom: null,
      validUntil: null,
      customerConfirmedAt: now,
      providerConfirmedAt: null,
      createdAt: now,
    };
    serviceBindings.set(binding.id, binding);
  }
  return { status: 'submitted', message: 'Запрос отправлен на проверку', remaining_attempts: rate.remaining };
}

export function createContactBinding(customerOrgId: string, input: ContactBindingInput): ServiceBinding | 'not_found' {
  if (!equipmentIdsOfOrg(customerOrgId).has(input.equipment_id)) return 'not_found';
  const now = new Date().toISOString();
  const binding: DbServiceBinding = {
    id: nextId('sb'),
    equipmentId: input.equipment_id,
    customerOrgId,
    providerOrgId: null,
    status: 'pending',
    statusReason: null,
    basis: 'preferred_provider',
    contractNumber: null,
    claimedContractNumber: null,
    personalContactName: input.contact_name,
    personalContactPhone: input.contact_phone ?? null,
    guarantorKind: null,
    guarantorOrgId: null,
    warrantyAuthorizationId: null,
    validFrom: null,
    validUntil: null,
    customerConfirmedAt: now,
    providerConfirmedAt: null,
    createdAt: now,
  };
  serviceBindings.set(binding.id, binding);
  return toServiceBindingView(binding);
}

export function respondBinding(
  providerOrgId: string,
  bindingId: string,
  decision: string,
  reason: string | null | undefined,
): ProviderBinding | 'not_found' | 'invalid' {
  const binding = serviceBindings.get(bindingId);
  if (!binding || binding.providerOrgId !== providerOrgId) return 'not_found';
  if (binding.status !== 'pending') return 'invalid';
  if (decision === 'confirm') {
    binding.status = 'confirmed';
    binding.providerConfirmedAt = new Date().toISOString();
  } else if (decision === 'reject') {
    binding.status = 'rejected';
    binding.statusReason = reason ?? null;
  } else {
    return 'invalid';
  }
  return toProviderBindingView(binding);
}

export function revokeBinding(
  actorOrgId: string,
  bindingId: string,
  reason: string,
): ServiceBinding | 'not_found' | 'invalid' {
  const binding = serviceBindings.get(bindingId);
  if (!binding || (binding.customerOrgId !== actorOrgId && binding.providerOrgId !== actorOrgId)) return 'not_found';
  if (binding.status !== 'pending' && binding.status !== 'confirmed') return 'invalid';
  binding.status = 'revoked';
  binding.statusReason = reason;
  return toServiceBindingView(binding);
}

export interface OperatorBindingRow {
  id: string;
  status: BindingStatus;
  basis: BindingBasis;
  customer_organization_id: string;
  customer_name: string;
  provider_organization_id: string | null;
  provider_name: string | null;
  equipment_id: string;
  contract_number: string | null;
  status_reason: string | null;
  created_at: string;
}

export function listAllBindingsForOperator(status?: string): OperatorBindingRow[] {
  return Array.from(serviceBindings.values())
    .filter((b) => !status || status === 'all' || b.status === status)
    .map((b) => ({
      id: b.id,
      status: b.status,
      basis: b.basis,
      customer_organization_id: b.customerOrgId,
      customer_name: organizations.get(b.customerOrgId)?.name ?? b.customerOrgId,
      provider_organization_id: b.providerOrgId,
      provider_name: b.providerOrgId ? (organizations.get(b.providerOrgId)?.name ?? b.providerOrgId) : null,
      equipment_id: b.equipmentId,
      contract_number: b.contractNumber ?? b.claimedContractNumber,
      status_reason: b.statusReason,
      created_at: b.createdAt,
    }));
}

export function operatorRevokeBinding(bindingId: string, reason: string): ServiceBinding | null {
  const binding = serviceBindings.get(bindingId);
  if (!binding) return null;
  binding.status = 'revoked';
  binding.statusReason = reason;
  return toServiceBindingView(binding);
}

function invitationDbState(inv: DbBindingInvitation): InvitationState {
  if (inv.dbStatus === 'accepted') return 'used';
  if (inv.dbStatus === 'revoked') return 'revoked';
  if (inv.dbStatus === 'declined') return 'declined' as InvitationState;
  if (new Date(inv.expiresAt).getTime() <= Date.now()) return 'expired';
  return 'active';
}

function toInvitationItemViews(inv: DbBindingInvitation): BindingInvitationItem[] {
  return inv.equipmentItems.map((item, index) => ({
    index,
    description: item.description,
    serial_number: item.serial_number ?? null,
    model: item.model ?? null,
  }));
}

function toBindingInvitationView(inv: DbBindingInvitation): BindingInvitation {
  const state = invitationDbState(inv);
  return {
    id: inv.id,
    state,
    customer_organization_id: state === 'used' ? inv.targetOrgId : null,
    contract_number: inv.contractNumber,
    basis: inv.basis,
    equipment_ids: inv.equipmentIds,
    equipment_descriptions: inv.equipmentItems.map((item) => item.description),
    equipment_items: toInvitationItemViews(inv),
    expires_at: inv.expiresAt,
    token_prefix: inv.tokenPrefix,
    created_at: inv.createdAt,
    customer_name: inv.customerName,
    declined_at: inv.declinedAt ?? null,
    decline_reason: inv.declineReason ?? null,
    guarantor_kind: inv.guarantorKind ?? null,
    guarantor_name: inv.guarantorName ?? null,
  };
}

export function listBindingInvitations(providerOrgId: string): Page<BindingInvitation> {
  const items = Array.from(bindingInvitations.values())
    .filter((i) => i.providerOrgId === providerOrgId)
    .map(toBindingInvitationView);
  return { items, next_cursor: null };
}

export function createBindingInvitation(
  providerOrgId: string,
  input: {
    customer_inn: string;
    contract_number: string;
    basis?: string;
    valid_from?: string | null;
    valid_until?: string | null;
    customer_name?: string | null;
    guarantor_kind?: GuarantorKind | null;
    guarantor_name?: string | null;
    equipment_items: BindingInvitationItemInput[];
  },
): BindingInvitationIssued | 'provider_not_active' | 'self_binding' {
  const providerProfile = providerProfiles.get(providerOrgId);
  if (!providerProfile || providerProfile.status !== 'active') return 'provider_not_active';

  const normalizedInn = input.customer_inn.trim();
  const target = Array.from(organizations.values()).find(
    (o) => o.inn === normalizedInn && o.kinds.includes('customer'),
  );
  if (target?.id === providerOrgId) return 'self_binding';

  const now = new Date();
  const token = `${nextId('sbtok')}${Math.random().toString(36).slice(2, 10)}`;
  const invitation: DbBindingInvitation = {
    id: nextId('inv'),
    providerOrgId,
    targetOrgId: target ? target.id : null,
    token,
    tokenPrefix: token.slice(0, 8),
    contractNumber: input.contract_number,
    basis: (input.basis as BindingBasis) || 'service_contract',
    validFrom: input.valid_from ?? null,
    validUntil: input.valid_until ?? null,
    customerInn: normalizedInn,
    customerName: input.customer_name ?? null,
    guarantorKind: input.guarantor_kind ?? null,
    guarantorName: input.guarantor_name?.trim() || null,
    equipmentItems: input.equipment_items.map((item) => ({
      description: item.description.trim(),
      serial_number: item.serial_number?.trim() || null,
      model: item.model?.trim() || null,
    })),
    equipmentIds: [],
    dbStatus: 'pending',
    expiresAt: new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString(),
    createdAt: now.toISOString(),
  };
  bindingInvitations.set(invitation.id, invitation);
  const base = toBindingInvitationView(invitation);
  return {
    ...base,
    token,
    webapp_link: `https://max.ru/repairbot/webapp?startapp=sb_${token}`,
    bot_link: `https://max.ru/repairbot?start=sb_${token}`,
  };
}

export function revokeBindingInvitation(providerOrgId: string, id: string): BindingInvitation | 'invalid' | null {
  const invitation = bindingInvitations.get(id);
  if (!invitation || invitation.providerOrgId !== providerOrgId) return null;
  if (invitation.dbStatus !== 'pending') return 'invalid';
  invitation.dbStatus = 'revoked';
  return toBindingInvitationView(invitation);
}

function findBindingInvitationByToken(token: string): DbBindingInvitation | null {
  return Array.from(bindingInvitations.values()).find((i) => i.token === token) ?? null;
}

function isBindingAddressee(invitation: DbBindingInvitation, customerOrgId: string): boolean {
  if (invitation.targetOrgId && invitation.targetOrgId !== customerOrgId) return false;
  const customer = organizations.get(customerOrgId);
  return !!customer && (!customer.inn || customer.inn === invitation.customerInn);
}

export function previewBindingInvitation(
  token: string,
  viewer: { organizationId: string; role: string } | null = null,
): BindingInvitationPreview | null {
  const invitation = findBindingInvitationByToken(token);
  if (!invitation) return null;
  const provider = organizations.get(invitation.providerOrgId);
  if (!provider) return null;
  const state = invitationDbState(invitation);
  const requisitesVerified = getBadges(provider.id).find((b) => b.kind === 'requisites')?.confirmed ?? false;
  const representativeVerified =
    getBadges(provider.id).find((b) => b.kind === 'representative')?.confirmed ?? false;
  const disclose =
    state === 'active' &&
    viewer !== null &&
    viewer.role === 'customer_manager' &&
    isBindingAddressee(invitation, viewer.organizationId);
  if (!disclose) {
    return {
      provider_name: provider.name,
      contract_number: null,
      basis: null,
      equipment_descriptions: [],
      equipment_items: [],
      equipment_ids: [],
      valid_from: null,
      valid_until: null,
      expires_at: null,
      state,
      requisites_verified: requisitesVerified,
      representative_verified: representativeVerified,
      details_disclosed: false,
    };
  }
  return {
    provider_name: provider.name,
    contract_number: invitation.contractNumber,
    basis: invitation.basis,
    equipment_descriptions: invitation.equipmentItems.map((item) => item.description),
    equipment_items: toInvitationItemViews(invitation),
    equipment_ids: invitation.equipmentIds,
    valid_from: invitation.validFrom,
    valid_until: invitation.validUntil,
    expires_at: invitation.expiresAt,
    state,
    requisites_verified: requisitesVerified,
    representative_verified: representativeVerified,
    details_disclosed: true,
    guarantor_kind: invitation.guarantorKind ?? null,
    guarantor_name: invitation.guarantorName ?? null,
  };
}

export function declineBindingInvitation(
  customerOrgId: string,
  token: string,
  reason: string | null,
): BindingInvitationPreview | 'invalid' {
  const invitation = findBindingInvitationByToken(token);
  if (!invitation) return 'invalid';
  if (invitation.dbStatus === 'declined') {
    return invitation.targetOrgId === customerOrgId ? (previewBindingInvitation(token) ?? 'invalid') : 'invalid';
  }
  if (invitationDbState(invitation) !== 'active') return 'invalid';
  if (!isBindingAddressee(invitation, customerOrgId)) return 'invalid';
  invitation.dbStatus = 'declined';
  invitation.declinedAt = new Date().toISOString();
  invitation.declineReason = reason;
  invitation.targetOrgId = customerOrgId;
  return previewBindingInvitation(token) ?? 'invalid';
}

function normalizeSerial(value: string | null | undefined): string {
  return (value ?? '').replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();
}

export type BindingAcceptError =
  | { code: 'INVITATION_INVALID' }
  | { code: 'MATCHES_INVALID'; message: string }
  | { code: 'SERIAL_NUMBER_MISMATCH'; itemIndex: number }
  | { code: 'SELF_BINDING_FORBIDDEN' };

export function acceptBindingInvitation(
  customerOrgId: string,
  token: string,
  matches: BindingItemMatch[],
): ServiceBinding[] | BindingAcceptError {
  const invitation = findBindingInvitationByToken(token);
  if (!invitation || invitationDbState(invitation) !== 'active') return { code: 'INVITATION_INVALID' };
  if (invitation.targetOrgId && invitation.targetOrgId !== customerOrgId) return { code: 'INVITATION_INVALID' };
  if (invitation.providerOrgId === customerOrgId) return { code: 'SELF_BINDING_FORBIDDEN' };
  const customer = organizations.get(customerOrgId);
  if (!customer) return { code: 'INVITATION_INVALID' };

  const items = invitation.equipmentItems;
  if (items.length === 0) return { code: 'INVITATION_INVALID' };
  const indexes = matches.map((m) => m.item_index);
  const equipmentIds = matches.map((m) => m.equipment_id);
  if (new Set(indexes).size !== indexes.length || new Set(equipmentIds).size !== equipmentIds.length) {
    return { code: 'MATCHES_INVALID', message: 'Каждая позиция сопоставляется с одной карточкой оборудования' };
  }
  if ([...indexes].sort((a, b) => a - b).join(',') !== items.map((_, i) => i).join(',')) {
    return { code: 'MATCHES_INVALID', message: 'Сопоставьте каждую позицию приглашения со своим оборудованием' };
  }
  const orgEquipmentIds = equipmentIdsOfOrg(customerOrgId);
  if (equipmentIds.some((id) => !orgEquipmentIds.has(id))) {
    return { code: 'MATCHES_INVALID', message: 'Оборудование не найдено' };
  }
  for (const match of matches) {
    const expected = normalizeSerial(items[match.item_index]?.serial_number);
    const actual = normalizeSerial(equipment.get(match.equipment_id)?.serial_number);
    if (expected && actual && expected !== actual) {
      return { code: 'SERIAL_NUMBER_MISMATCH', itemIndex: match.item_index };
    }
  }

  invitation.dbStatus = 'accepted';
  invitation.targetOrgId = customerOrgId;
  invitation.equipmentIds = [...matches].sort((a, b) => a.item_index - b.item_index).map((m) => m.equipment_id);

  const now = new Date().toISOString();
  const created: DbServiceBinding[] = [];
  for (const match of [...matches].sort((a, b) => a.item_index - b.item_index)) {
    const binding: DbServiceBinding = {
      id: nextId('sb'),
      invitationItemIndex: match.item_index,
      invitationItemDescription: items[match.item_index]?.description ?? null,
      equipmentId: match.equipment_id,
      customerOrgId,
      providerOrgId: invitation.providerOrgId,
      status: 'pending',
      statusReason: null,
      basis: invitation.basis,
      contractNumber: invitation.contractNumber,
      claimedContractNumber: null,
      personalContactName: null,
      personalContactPhone: null,
      guarantorKind: invitation.guarantorKind ?? null,
      guarantorOrgId: null,
      statedGuarantorName: invitation.guarantorName ?? null,
      warrantyAuthorizationId: null,
      validFrom: invitation.validFrom,
      validUntil: invitation.validUntil,
      customerConfirmedAt: now,
      providerConfirmedAt: invitation.createdAt,
      createdAt: now,
    };
    serviceBindings.set(binding.id, binding);
    created.push(binding);
  }
  return created.map(toServiceBindingView);
}

function toApiKeyView(k: DbApiKey): ApiKey {
  return {
    id: k.id,
    name: k.name,
    scopes: k.scopes,
    status: k.status,
    key_prefix: k.keyPrefix,
    created_at: k.createdAt,
    rotated_at: k.rotatedAt,
    revoked_at: k.revokedAt,
    last_used_at: k.lastUsedAt,
    warnings: scopeConflicts(k.scopes).length > 0 ? ['service_bindings_write_shared'] : [],
  };
}

export function scopeConflicts(scopes: readonly string[]): string[] {
  if (!scopes.includes('service_bindings:write')) return [];
  return scopes.filter((scope) => scope === 'requests:write' || scope === 'marketplace:write').sort();
}

export function listApiKeys(organizationId: string): ApiKey[] {
  return Array.from(apiKeys.values())
    .filter((k) => k.organizationId === organizationId)
    .map(toApiKeyView);
}

function randomKeySecret(): string {
  return `key_live_${nextId('sec')}${Math.random().toString(36).slice(2, 10)}`;
}

export function createApiKey(organizationId: string, input: ApiKeyCreateInput): ApiKeyIssued {
  const fullKey = randomKeySecret();
  const key: DbApiKey = {
    id: nextId('ik'),
    organizationId,
    name: input.name,
    scopes: (input.scopes ?? []) as IntegrationScope[],
    status: 'active',
    keyPrefix: fullKey.slice(0, 14),
    fullKey,
    createdAt: new Date().toISOString(),
    rotatedAt: null,
    revokedAt: null,
    lastUsedAt: null,
  };
  apiKeys.set(key.id, key);
  return { ...toApiKeyView(key), key: fullKey };
}

export function revokeApiKey(organizationId: string, id: string): ApiKey | null {
  const key = apiKeys.get(id);
  if (!key || key.organizationId !== organizationId) return null;
  key.status = 'revoked';
  key.revokedAt = new Date().toISOString();
  return toApiKeyView(key);
}

export function rotateApiKey(organizationId: string, id: string): ApiKeyIssued | null {
  const key = apiKeys.get(id);
  if (!key || key.organizationId !== organizationId || key.status !== 'active') return null;
  const fullKey = randomKeySecret();
  key.fullKey = fullKey;
  key.keyPrefix = fullKey.slice(0, 14);
  key.rotatedAt = new Date().toISOString();
  return { ...toApiKeyView(key), key: fullKey };
}

function toSubscriptionView(s: DbWebhookSubscription): WebhookSubscription {
  return {
    id: s.id,
    url: s.url,
    events: s.events,
    status: s.status,
    created_at: s.createdAt,
    disabled_at: s.disabledAt,
  };
}

export function listWebhookSubscriptions(organizationId: string): WebhookSubscription[] {
  return Array.from(webhookSubscriptions.values())
    .filter((s) => s.organizationId === organizationId)
    .map(toSubscriptionView);
}

export function createWebhookSubscription(
  organizationId: string,
  input: { url: string; events?: string[]; client_id?: string | null },
): WebhookSubscriptionIssued | 'no_key' | 'client_required' | 'client_not_found' {
  const active = Array.from(apiKeys.values()).filter((k) => k.organizationId === organizationId && k.status === 'active');
  if (input.client_id) {
    if (!active.some((k) => k.id === input.client_id)) return 'client_not_found';
  } else if (active.length === 0) {
    return 'no_key';
  } else if (active.length > 1) {
    return 'client_required';
  }
  const subscription: DbWebhookSubscription = {
    id: nextId('whs'),
    organizationId,
    url: input.url,
    events: input.events?.length ? input.events : ['request.assigned', 'request.changed', 'message.created'],
    status: 'active',
    createdAt: new Date().toISOString(),
    disabledAt: null,
  };
  webhookSubscriptions.set(subscription.id, subscription);
  return { ...toSubscriptionView(subscription), secret: `whsec_${Math.random().toString(36).slice(2, 14)}` };
}

export function setWebhookSubscriptionEnabled(
  organizationId: string,
  id: string,
  enabled: boolean,
): WebhookSubscription | 'unchanged' | null {
  const subscription = webhookSubscriptions.get(id);
  if (!subscription || subscription.organizationId !== organizationId) return null;
  if ((subscription.status === 'active') === enabled) return 'unchanged';
  subscription.status = enabled ? 'active' : 'disabled';
  subscription.disabledAt = enabled ? null : new Date().toISOString();
  return toSubscriptionView(subscription);
}

export function rotateWebhookSecret(organizationId: string, id: string): WebhookSubscriptionIssued | null {
  const subscription = webhookSubscriptions.get(id);
  if (!subscription || subscription.organizationId !== organizationId) return null;
  return { ...toSubscriptionView(subscription), secret: `whsec_${Math.random().toString(36).slice(2, 14)}` };
}

export function integrationSummary(organizationId: string): IntegrationSummary {
  const keys = Array.from(apiKeys.values()).filter((k) => k.organizationId === organizationId && k.status === 'active');
  const subscriptions = Array.from(webhookSubscriptions.values())
    .filter((s) => s.organizationId === organizationId)
    .sort((a, b) => Number(b.status === 'active') - Number(a.status === 'active') || b.createdAt.localeCompare(a.createdAt));
  const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
  const recent = Array.from(deliveries.values()).filter(
    (d) => d.organizationId === organizationId && Date.parse(d.createdAt) >= dayAgo,
  );
  const count = (state: DeliveryState) => recent.filter((d) => d.state === state).length;
  const lastEvent = recent.map((d) => d.createdAt).sort().at(-1) ?? null;
  const lastUsed = keys.map((k) => k.lastUsedAt).filter((v): v is string => Boolean(v)).sort().at(-1) ?? null;
  const webhook = subscriptions[0];
  return {
    connected: keys.length > 0,
    api_keys_active: keys.length,
    last_key_used_at: lastUsed,
    webhook: webhook ? { id: webhook.id, url: webhook.url, status: webhook.status } : null,
    last_event_at: lastEvent,
    deliveries_24h: {
      total: recent.length,
      delivered: count('delivered'),
      failed: count('failed') + count('blocked'),
      retrying: count('retrying'),
      queued: count('queued'),
    },
  };
}

export function equipmentBindingSummary(equipmentId: string, customerOrgId: string): EquipmentBindingSummary | null {
  const rank = (b: DbServiceBinding) => (b.providerOrgId === null ? 1 : b.status === 'confirmed' ? 0 : 2);
  const best = Array.from(serviceBindings.values())
    .filter(
      (b) =>
        b.equipmentId === equipmentId &&
        b.customerOrgId === customerOrgId &&
        (b.status === 'confirmed' || b.status === 'pending'),
    )
    .sort((a, b) => rank(a) - rank(b) || b.createdAt.localeCompare(a.createdAt))[0];
  if (!best) return null;
  const guarantor = best.guarantorOrgId ? organizations.get(best.guarantorOrgId) : undefined;
  return {
    id: best.id,
    status: best.status,
    basis: best.basis,
    is_contact_only: best.providerOrgId === null,
    provider_name: best.providerOrgId
      ? (organizations.get(best.providerOrgId)?.name ?? null)
      : best.personalContactName,
    valid_until: best.validUntil,
    guarantor_kind: best.guarantorKind,
    guarantor_name:
      guarantor?.name ??
      (best.warrantyAuthorizationId ? warrantyAuthorizations.get(best.warrantyAuthorizationId)?.guarantorName : null) ??
      best.statedGuarantorName ??
      null,
    provider_has_crm:
      best.providerOrgId !== null &&
      Array.from(webhookSubscriptions.values()).some(
        (s) => s.organizationId === best.providerOrgId && s.status === 'active',
      ),
    contact_phone: best.providerOrgId === null ? best.personalContactPhone : null,
    guarantor_stated_by_provider: best.guarantorKind !== null && !best.warrantyAuthorizationId,
    warranty_authorization_id: best.warrantyAuthorizationId ?? null,
  };
}

export function membershipAuthor(membershipId: string): { name: string; organization: string } | null {
  const membership = memberships.get(membershipId);
  if (!membership) return null;
  return {
    name: users.get(membership.user_id)?.display_name ?? '',
    organization: organizations.get(membership.organization_id)?.name ?? '',
  };
}

export function cityAndDistrictNames(
  cityId: string | null | undefined,
  districtId: string | null | undefined,
): { city_name: string | null; district_name: string | null } {
  const city = cities.find((c) => c.id === cityId);
  return {
    city_name: city?.name ?? null,
    district_name: city?.districts.find((d) => d.id === districtId)?.name ?? null,
  };
}

export function categoryById(id: string): EquipmentCategory | undefined {
  return equipmentCategories.find((c) => c.id === id);
}

export function locationName(id: string): string | null {
  return locations.get(id)?.name ?? null;
}

function toDeliveryView(d: DbDelivery): Delivery {
  return {
    id: d.id,
    event_id: d.eventId,
    event_type: d.eventType,
    subscription_id: d.subscriptionId,
    state: d.state,
    in_flight: d.inFlight,
    attempt_count: d.attemptCount,
    delivery_id: d.id,
    last_http_status: d.lastHttpStatus,
    last_error: d.lastError,
    last_attempt_at: d.lastAttemptAt,
    next_attempt_at: d.nextAttemptAt,
    expires_at: d.expiresAt,
    created_at: d.createdAt,
  };
}

export function listDeliveries(organizationId: string): DeliveryPage {
  const items = Array.from(deliveries.values())
    .filter((d) => d.organizationId === organizationId)
    .map(toDeliveryView);
  return { items, next_cursor: null, has_more: false };
}

export function redeliverDelivery(organizationId: string, id: string): Delivery | null {
  const delivery = deliveries.get(id);
  if (!delivery || delivery.organizationId !== organizationId) return null;
  delivery.state = 'delivered';
  delivery.inFlight = false;
  delivery.attemptCount += 1;
  delivery.lastHttpStatus = 200;
  delivery.lastError = null;
  delivery.lastAttemptAt = new Date().toISOString();
  delivery.nextAttemptAt = null;
  return toDeliveryView(delivery);
}

export const demoSeed = {
  demoCustomer,
  demoDualOrg,
  demoProvider,
  demoActiveProvider,
  demoLocation1,
};
