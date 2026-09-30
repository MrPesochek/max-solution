CREATE TABLE users (
    id                  uuid primary key default uuidv7(),
    max_user_id         text not null,
    display_name        text not null,
    bot_available       boolean not null default false,
    bot_started_at      timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint ux_users_max_user_id unique (max_user_id)
);

CREATE TABLE organizations (
    id                              uuid primary key default uuidv7(),
    is_customer                     boolean not null default false,
    is_provider                     boolean not null default false,
    legal_name                      text not null,
    display_name                    text not null,
    legal_form                      text,
    inn_raw                         text,
    inn_normalized                  text,
    contact_name                    text,
    contact_phone                   text,
    contact_email                   text,
    details_verification_status     text not null default 'unverified',
    details_verified_at             timestamptz,
    representative_verification_status text not null default 'unverified',
    representative_verified_at      timestamptz,
    created_at                      timestamptz not null default now(),
    updated_at                      timestamptz not null default now(),
    constraint ck_organizations_participant_type check (is_customer or is_provider),
    constraint ck_organizations_legal_form check (legal_form is null or legal_form in ('ooo', 'ip', 'self_employed')),
    constraint ck_organizations_details_status check (details_verification_status in ('unverified', 'pending', 'verified', 'rejected')),
    constraint ck_organizations_representative_status check (representative_verification_status in ('unverified', 'pending', 'verified', 'rejected'))
);

CREATE UNIQUE INDEX ux_organizations_verified_provider_inn
    ON organizations (inn_normalized)
    WHERE is_provider AND details_verification_status = 'verified' AND inn_normalized IS NOT NULL;

CREATE INDEX ix_organizations_inn_normalized ON organizations (inn_normalized) WHERE inn_normalized IS NOT NULL;

CREATE TABLE memberships (
    id                      uuid primary key default uuidv7(),
    user_id                 uuid not null references users (id),
    organization_id         uuid not null references organizations (id),
    role                    text not null,
    status                  text not null default 'pending',
    invited_by_membership_id uuid references memberships (id),
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    constraint ux_memberships_user_org unique (user_id, organization_id),
    constraint ck_memberships_role check (role in ('customer_employee', 'customer_manager', 'provider_admin', 'provider_dispatcher')),
    constraint ck_memberships_status check (status in ('pending', 'active', 'revoked'))
);

CREATE INDEX ix_memberships_organization_id ON memberships (organization_id);
CREATE INDEX ix_memberships_user_id ON memberships (user_id);
CREATE INDEX ix_memberships_invited_by ON memberships (invited_by_membership_id);

CREATE TABLE membership_locations (
    id              uuid primary key default uuidv7(),
    membership_id   uuid not null references memberships (id),
    location_id     uuid not null,
    created_at      timestamptz not null default now(),
    constraint ux_membership_locations unique (membership_id, location_id)
);

CREATE INDEX ix_membership_locations_membership_id ON membership_locations (membership_id);

CREATE TABLE platform_roles (
    id                  uuid primary key default uuidv7(),
    user_id             uuid not null references users (id),
    role                text not null,
    granted_by_user_id  uuid references users (id),
    granted_at          timestamptz not null default now(),
    revoked_at          timestamptz,
    created_at          timestamptz not null default now(),
    constraint ck_platform_roles_role check (role in ('operator'))
);

CREATE UNIQUE INDEX ux_platform_roles_active ON platform_roles (user_id, role) WHERE revoked_at IS NULL;
CREATE INDEX ix_platform_roles_user_id ON platform_roles (user_id);

CREATE TABLE sessions (
    id                          uuid primary key default uuidv7(),
    user_id                     uuid not null references users (id),
    token_hash                  bytea not null,
    token_prefix                text not null,
    active_organization_id      uuid references organizations (id),
    active_membership_id        uuid references memberships (id),
    issued_at                   timestamptz not null default now(),
    expires_at                  timestamptz not null,
    last_seen_at                timestamptz not null default now(),
    revoked_at                  timestamptz,
    ip_address                  inet,
    user_agent                  text,
    created_at                  timestamptz not null default now(),
    constraint ux_sessions_token_hash unique (token_hash)
);

CREATE INDEX ix_sessions_user_id ON sessions (user_id);
CREATE INDEX ix_sessions_active_membership_id ON sessions (active_membership_id);
CREATE INDEX ix_sessions_expires_at ON sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE invitations (
    id                          uuid primary key default uuidv7(),
    kind                        text not null,
    organization_id             uuid not null references organizations (id),
    created_by_membership_id    uuid references memberships (id),
    target_organization_id      uuid references organizations (id),
    role                        text,
    location_ids                uuid[] not null default '{}',
    equipment_ids                uuid[] not null default '{}',
    service_contract_id         uuid,
    token_hash                  bytea not null,
    token_prefix                text not null,
    status                      text not null default 'pending',
    expires_at                  timestamptz not null,
    accepted_at                 timestamptz,
    accepted_by_user_id         uuid references users (id),
    revoked_at                  timestamptz,
    revoked_by_membership_id    uuid references memberships (id),
    created_at                  timestamptz not null default now(),
    constraint ux_invitations_token_hash unique (token_hash),
    constraint ck_invitations_kind check (kind in ('membership', 'service_binding')),
    constraint ck_invitations_status check (status in ('pending', 'accepted', 'revoked', 'expired')),
    constraint ck_invitations_role check (role is null or role in ('customer_employee', 'customer_manager', 'provider_admin', 'provider_dispatcher'))
);

CREATE INDEX ix_invitations_organization_id ON invitations (organization_id);
CREATE INDEX ix_invitations_target_organization_id ON invitations (target_organization_id);
CREATE INDEX ix_invitations_created_by ON invitations (created_by_membership_id);
CREATE INDEX ix_invitations_expires_at ON invitations (expires_at) WHERE status = 'pending';

CREATE TABLE cities (
    id          uuid primary key default uuidv7(),
    name        text not null,
    region      text,
    timezone    text not null default 'Europe/Moscow',
    created_at  timestamptz not null default now()
);

CREATE TABLE districts (
    id          uuid primary key default uuidv7(),
    city_id     uuid not null references cities (id),
    name        text not null,
    created_at  timestamptz not null default now(),
    constraint ux_districts_city_name unique (city_id, name)
);

CREATE INDEX ix_districts_city_id ON districts (city_id);

CREATE TABLE equipment_categories (
    id              uuid primary key default uuidv7(),
    code            text not null,
    name            text not null,
    photo_template  jsonb not null default '[]'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint ux_equipment_categories_code unique (code)
);

CREATE TABLE locations (
    id                  uuid primary key default uuidv7(),
    customer_org_id     uuid not null references organizations (id),
    name                text not null,
    city_id             uuid not null references cities (id),
    district_id         uuid references districts (id),
    address             text not null,
    timezone            text not null default 'Europe/Moscow',
    contact_name        text,
    contact_phone       text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

CREATE INDEX ix_locations_customer_org_id ON locations (customer_org_id);
CREATE INDEX ix_locations_city_id ON locations (city_id);
CREATE INDEX ix_locations_district_id ON locations (district_id);

ALTER TABLE membership_locations
    ADD CONSTRAINT fk_membership_locations_location
    FOREIGN KEY (location_id) REFERENCES locations (id);

CREATE INDEX ix_membership_locations_location_id ON membership_locations (location_id);

CREATE TABLE equipment (
    id                      uuid primary key default uuidv7(),
    customer_org_id         uuid not null references organizations (id),
    location_id             uuid not null references locations (id),
    equipment_category_id   uuid not null references equipment_categories (id),
    brand                   text,
    model                   text,
    serial_number           text,
    notes                   text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

CREATE INDEX ix_equipment_customer_org_id ON equipment (customer_org_id);
CREATE INDEX ix_equipment_location_id ON equipment (location_id);
CREATE INDEX ix_equipment_category_id ON equipment (equipment_category_id);

CREATE TABLE provider_profiles (
    id                      uuid primary key default uuidv7(),
    organization_id         uuid not null references organizations (id),
    provider_kind           text not null,
    status                  text not null default 'draft',
    status_reason           text,
    accepting_new_requests  boolean not null default true,
    visit_terms             text,
    can_provide_documents   boolean not null default false,
    description             text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    constraint ux_provider_profiles_organization unique (organization_id),
    constraint ck_provider_profiles_kind check (provider_kind in ('company', 'independent_specialist')),
    constraint ck_provider_profiles_status check (status in ('draft', 'pending_review', 'needs_information', 'active', 'suspended', 'rejected'))
);

CREATE TABLE provider_categories (
    id                      uuid primary key default uuidv7(),
    provider_org_id         uuid not null references organizations (id),
    equipment_category_id   uuid not null references equipment_categories (id),
    created_at              timestamptz not null default now(),
    constraint ux_provider_categories unique (provider_org_id, equipment_category_id)
);

CREATE INDEX ix_provider_categories_provider_org_id ON provider_categories (provider_org_id);
CREATE INDEX ix_provider_categories_category_id ON provider_categories (equipment_category_id);

CREATE TABLE provider_service_areas (
    id              uuid primary key default uuidv7(),
    provider_org_id uuid not null references organizations (id),
    city_id         uuid not null references cities (id),
    district_id     uuid references districts (id),
    created_at      timestamptz not null default now()
);

CREATE INDEX ix_provider_service_areas_provider_org_id ON provider_service_areas (provider_org_id);
CREATE INDEX ix_provider_service_areas_city_id ON provider_service_areas (city_id);
CREATE UNIQUE INDEX ux_provider_service_areas_whole_city
    ON provider_service_areas (provider_org_id, city_id) WHERE district_id IS NULL;
CREATE UNIQUE INDEX ux_provider_service_areas_district
    ON provider_service_areas (provider_org_id, district_id) WHERE district_id IS NOT NULL;

CREATE TABLE provider_brand_restrictions (
    id                      uuid primary key default uuidv7(),
    provider_org_id         uuid not null references organizations (id),
    equipment_category_id   uuid not null references equipment_categories (id),
    brand                   text not null,
    created_at              timestamptz not null default now(),
    constraint ux_provider_brand_restrictions unique (provider_org_id, equipment_category_id, brand)
);

CREATE INDEX ix_provider_brand_restrictions_provider_org_id ON provider_brand_restrictions (provider_org_id);

CREATE TABLE verification_cases (
    id                  uuid primary key default uuidv7(),
    organization_id     uuid not null references organizations (id),
    membership_id       uuid references memberships (id),
    subject_type        text not null,
    check_kind          text not null,
    source               text,
    evidence_note        text,
    operator_user_id     uuid references users (id),
    decision             text not null default 'pending',
    decision_reason      text,
    checked_at           timestamptz,
    expires_at           timestamptz,
    supersedes_case_id   uuid references verification_cases (id),
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    constraint ck_verification_cases_subject_type check (subject_type in ('organization_details', 'representative', 'customer_representative')),
    constraint ck_verification_cases_decision check (decision in ('pending', 'approved', 'rejected', 'needs_information', 'revoked'))
);

CREATE INDEX ix_verification_cases_organization_id ON verification_cases (organization_id);
CREATE INDEX ix_verification_cases_membership_id ON verification_cases (membership_id);
CREATE INDEX ix_verification_cases_operator_user_id ON verification_cases (operator_user_id);
CREATE INDEX ix_verification_cases_pending ON verification_cases (organization_id) WHERE decision = 'pending';

CREATE TABLE warranty_authorizations (
    id                          uuid primary key default uuidv7(),
    guarantor_kind               text not null,
    guarantor_org_id             uuid references organizations (id),
    guarantor_name                text,
    authorized_provider_org_id    uuid not null references organizations (id),
    equipment_category_id         uuid references equipment_categories (id),
    brand_scope                   text[] not null default '{}',
    territory_city_id             uuid references cities (id),
    source_verification_case_id   uuid references verification_cases (id),
    valid_from                    date,
    valid_until                   date,
    status                        text not null default 'pending',
    created_at                    timestamptz not null default now(),
    updated_at                    timestamptz not null default now(),
    constraint ck_warranty_authorizations_guarantor_kind check (guarantor_kind in ('manufacturer', 'seller', 'service_org')),
    constraint ck_warranty_authorizations_status check (status in ('pending', 'active', 'expired', 'revoked'))
);

CREATE INDEX ix_warranty_authorizations_provider_org_id ON warranty_authorizations (authorized_provider_org_id);
CREATE INDEX ix_warranty_authorizations_guarantor_org_id ON warranty_authorizations (guarantor_org_id);
CREATE INDEX ix_warranty_authorizations_category_id ON warranty_authorizations (equipment_category_id);
CREATE INDEX ix_warranty_authorizations_source_case_id ON warranty_authorizations (source_verification_case_id);

CREATE TABLE service_contracts (
    id                          uuid primary key default uuidv7(),
    provider_org_id              uuid not null references organizations (id),
    customer_org_id               uuid not null references organizations (id),
    contract_number               text not null,
    basis                         text not null,
    valid_from                    date,
    valid_until                   date,
    created_by_membership_id      uuid references memberships (id),
    created_at                    timestamptz not null default now(),
    updated_at                    timestamptz not null default now(),
    constraint ux_service_contracts_provider_number unique (provider_org_id, contract_number),
    constraint ck_service_contracts_basis check (basis in ('warranty', 'service_contract', 'preferred_provider'))
);

CREATE INDEX ix_service_contracts_customer_org_id ON service_contracts (customer_org_id);
CREATE INDEX ix_service_contracts_created_by ON service_contracts (created_by_membership_id);

ALTER TABLE invitations
    ADD CONSTRAINT fk_invitations_service_contract
    FOREIGN KEY (service_contract_id) REFERENCES service_contracts (id);

CREATE INDEX ix_invitations_service_contract_id ON invitations (service_contract_id);

CREATE TABLE service_bindings (
    id                          uuid primary key default uuidv7(),
    equipment_id                 uuid not null references equipment (id),
    customer_org_id               uuid not null references organizations (id),
    provider_org_id                uuid references organizations (id),
    personal_contact_name          text,
    personal_contact_phone         text,
    contract_id                    uuid references service_contracts (id),
    basis                          text not null,
    guarantor_kind                  text,
    guarantor_org_id                 uuid references organizations (id),
    warranty_authorization_id        uuid references warranty_authorizations (id),
    valid_from                       date,
    valid_until                      date,
    status                           text not null default 'pending',
    customer_confirmed_at            timestamptz,
    provider_confirmed_at            timestamptz,
    source_invitation_id             uuid references invitations (id),
    created_by_membership_id         uuid not null references memberships (id),
    created_at                       timestamptz not null default now(),
    updated_at                       timestamptz not null default now(),
    constraint ck_service_bindings_provider_or_contact check ((provider_org_id is not null) <> (personal_contact_name is not null)),
    constraint ck_service_bindings_basis check (basis in ('warranty', 'service_contract', 'preferred_provider')),
    constraint ck_service_bindings_guarantor_kind check (guarantor_kind is null or guarantor_kind in ('manufacturer', 'seller', 'service_org')),
    constraint ck_service_bindings_status check (status in ('pending', 'confirmed', 'rejected', 'revoked'))
);

CREATE INDEX ix_service_bindings_equipment_id ON service_bindings (equipment_id);
CREATE INDEX ix_service_bindings_customer_org_id ON service_bindings (customer_org_id);
CREATE INDEX ix_service_bindings_provider_org_id ON service_bindings (provider_org_id);
CREATE INDEX ix_service_bindings_contract_id ON service_bindings (contract_id);
CREATE INDEX ix_service_bindings_warranty_authorization_id ON service_bindings (warranty_authorization_id);
CREATE INDEX ix_service_bindings_source_invitation_id ON service_bindings (source_invitation_id);
CREATE INDEX ix_service_bindings_pending ON service_bindings (provider_org_id) WHERE status = 'pending';

CREATE SEQUENCE request_number_seq AS bigint START WITH 1000;

CREATE TABLE repair_requests (
    id                          uuid primary key default uuidv7(),
    request_number               bigint not null default nextval('request_number_seq'),
    customer_org_id               uuid not null references organizations (id),
    location_id                   uuid not null references locations (id),
    equipment_id                   uuid not null references equipment (id),
    author_membership_id           uuid not null references memberships (id),
    route                          text not null,
    status                         text not null default 'draft',
    version                        integer not null default 1,
    urgency                        text not null default 'normal',
    symptom_description             text,
    error_code                      text,
    equipment_snapshot               jsonb not null default '{}'::jsonb,
    location_snapshot                 jsonb not null default '{}'::jsonb,
    closure_kind                      text,
    cancellation_reason                text,
    disputed                           boolean not null default false,
    submitted_at                        timestamptz,
    accepted_at                          timestamptz,
    scheduled_at                          timestamptz,
    work_started_at                        timestamptz,
    completion_reported_at                  timestamptz,
    closed_at                                timestamptz,
    cancelled_at                              timestamptz,
    created_at                                 timestamptz not null default now(),
    updated_at                                  timestamptz not null default now(),
    constraint ux_repair_requests_number unique (request_number),
    constraint ck_repair_requests_route check (route in ('own_service', 'marketplace')),
    constraint ck_repair_requests_status check (status in (
        'draft', 'approval_required', 'awaiting_provider', 'searching',
        'awaiting_assignment_confirmation', 'accepted', 'scheduled', 'in_progress',
        'completion_reported', 'closed', 'action_required', 'cancellation_pending', 'cancelled'
    )),
    constraint ck_repair_requests_urgency check (urgency in ('critical', 'urgent', 'normal')),
    constraint ck_repair_requests_closure_kind check (closure_kind is null or closure_kind in ('customer_confirmed', 'auto_timeout')),
    constraint ck_repair_requests_version check (version >= 1)
);

CREATE INDEX ix_repair_requests_customer_org_status ON repair_requests (customer_org_id, status);
CREATE INDEX ix_repair_requests_equipment_id ON repair_requests (equipment_id);
CREATE INDEX ix_repair_requests_location_id ON repair_requests (location_id);
CREATE INDEX ix_repair_requests_author_membership_id ON repair_requests (author_membership_id);
CREATE INDEX ix_repair_requests_status ON repair_requests (status);

CREATE TABLE request_public_cards (
    id                      uuid primary key default uuidv7(),
    request_id               uuid not null references repair_requests (id),
    equipment_category_id     uuid not null references equipment_categories (id),
    city_id                    uuid not null references cities (id),
    district_id                 uuid references districts (id),
    urgency                      text not null,
    published_description         text,
    status                        text not null default 'open',
    published_at                   timestamptz not null default now(),
    closed_at                       timestamptz,
    created_at                       timestamptz not null default now(),
    updated_at                        timestamptz not null default now(),
    constraint ux_request_public_cards_request unique (request_id),
    constraint ck_request_public_cards_urgency check (urgency in ('critical', 'urgent', 'normal')),
    constraint ck_request_public_cards_status check (status in ('open', 'closed'))
);

CREATE INDEX ix_request_public_cards_category_city ON request_public_cards (equipment_category_id, city_id) WHERE status = 'open';
CREATE INDEX ix_request_public_cards_district_id ON request_public_cards (district_id);

CREATE TABLE assignments (
    id                          uuid primary key default uuidv7(),
    request_id                   uuid not null references repair_requests (id),
    provider_org_id                uuid not null references organizations (id),
    route                           text not null,
    offer_id                        uuid,
    state                            text not null default 'pending',
    field_worker_membership_id        uuid references memberships (id),
    field_worker_display_name text,
    field_worker_contact_phone text,
    warranty_decision                  text not null default 'not_stated',
    warranty_decision_comment            text,
    decline_reason                        text,
    revoke_reason                          text,
    withdrawal_reason                       text,
    expires_at                               timestamptz,
    responded_at                              timestamptz,
    created_at                                 timestamptz not null default now(),
    updated_at                                  timestamptz not null default now(),
    constraint ck_assignments_route check (route in ('own_service', 'marketplace')),
    constraint ck_assignments_route_offer check ((route = 'marketplace') = (offer_id is not null)),
    constraint ck_assignments_state check (state in ('pending', 'accepted', 'declined', 'expired', 'revoked', 'withdrawn', 'completed')),
    constraint ck_assignments_warranty_decision check (warranty_decision in ('not_stated', 'warranty', 'not_warranty', 'undetermined'))
);

CREATE UNIQUE INDEX ux_assignments_one_active_per_request
    ON assignments (request_id) WHERE state IN ('pending', 'accepted');

CREATE INDEX ix_assignments_request_id ON assignments (request_id);
CREATE INDEX ix_assignments_provider_org_state ON assignments (provider_org_id, state);
CREATE INDEX ix_assignments_field_worker ON assignments (field_worker_membership_id);
CREATE INDEX ix_assignments_expires_at ON assignments (expires_at) WHERE state = 'pending';

CREATE TABLE offers (
    id                          uuid primary key default uuidv7(),
    request_id                   uuid not null references repair_requests (id),
    provider_org_id                uuid not null references organizations (id),
    version                         integer not null default 1,
    visit_window_start               timestamptz,
    visit_window_end                  timestamptz,
    visit_amount_minor                 bigint,
    currency                            char(3),
    vat_mode text check (vat_mode is null or vat_mode in ('included', 'excluded', 'not_applicable')),
    zero_cost_reason                     text,
    scope_description                     text,
    comment                                 text,
    access_requirements                     text,
    valid_until                              timestamptz not null,
    state                                     text not null default 'active',
    superseded_by_offer_id                     uuid references offers (id),
    created_by_membership_id                    uuid references memberships (id),
    created_at                                   timestamptz not null default now(),
    updated_at                                    timestamptz not null default now(),
    constraint ux_offers_request_provider_version unique (request_id, provider_org_id, version),
    constraint ck_offers_state check (state in ('active', 'selected', 'expired', 'withdrawn', 'closed')),
    constraint ck_offers_currency check (currency is null or currency = 'RUB'),
    constraint ck_offers_zero_cost check (visit_amount_minor is distinct from 0 or zero_cost_reason is not null)
);

CREATE INDEX ix_offers_request_id ON offers (request_id);
CREATE INDEX ix_offers_provider_org_id ON offers (provider_org_id);
CREATE INDEX ix_offers_created_by ON offers (created_by_membership_id);
CREATE INDEX ix_offers_valid_until ON offers (valid_until) WHERE state = 'active';

ALTER TABLE assignments
    ADD CONSTRAINT fk_assignments_offer
    FOREIGN KEY (offer_id) REFERENCES offers (id);

CREATE INDEX ix_assignments_offer_id ON assignments (offer_id);

CREATE TABLE visit_proposals (
    id                          uuid primary key default uuidv7(),
    request_id                   uuid not null references repair_requests (id),
    assignment_id                  uuid not null references assignments (id),
    version                          integer not null default 1,
    visit_window_start                timestamptz,
    visit_window_end                    timestamptz,
    visit_amount_minor                   bigint,
    currency                              char(3),
    vat_mode text check (vat_mode is null or vat_mode in ('included', 'excluded', 'not_applicable')),
    zero_cost_reason                       text,
    scope_description                       text,
    comment                                   text,
    access_requirements                       text,
    valid_until                                timestamptz not null,
    status                                      text not null default 'pending',
    responded_at                                 timestamptz,
    responded_by_membership_id                    uuid references memberships (id),
    response_comment                               text,
    created_by_membership_id                        uuid references memberships (id),
    created_at                                       timestamptz not null default now(),
    updated_at                                        timestamptz not null default now(),
    constraint ux_visit_proposals_request_assignment_version unique (request_id, assignment_id, version),
    constraint ck_visit_proposals_status check (status in ('pending', 'approved', 'rejected', 'expired', 'superseded')),
    constraint ck_visit_proposals_currency check (currency is null or currency = 'RUB'),
    constraint ck_visit_proposals_zero_cost check (visit_amount_minor is distinct from 0 or zero_cost_reason is not null)
);

CREATE INDEX ix_visit_proposals_request_id ON visit_proposals (request_id);
CREATE INDEX ix_visit_proposals_assignment_id ON visit_proposals (assignment_id);
CREATE INDEX ix_visit_proposals_responded_by ON visit_proposals (responded_by_membership_id);
CREATE INDEX ix_visit_proposals_created_by ON visit_proposals (created_by_membership_id);
CREATE INDEX ix_visit_proposals_valid_until ON visit_proposals (valid_until) WHERE status = 'pending';

CREATE TABLE repair_quotes (
    id                          uuid primary key default uuidv7(),
    request_id                   uuid not null references repair_requests (id),
    assignment_id                  uuid not null references assignments (id),
    version                          integer not null default 1,
    description_of_work               text not null,
    amount_minor                       bigint,
    currency                            char(3),
    vat_mode text check (vat_mode is null or vat_mode in ('included', 'excluded', 'not_applicable')),
    zero_cost_reason                     text,
    valid_until                           timestamptz not null,
    status                                 text not null default 'pending',
    responded_at                            timestamptz,
    responded_by_membership_id               uuid references memberships (id),
    response_comment                          text,
    created_by_membership_id                   uuid references memberships (id),
    created_at                                  timestamptz not null default now(),
    updated_at                                   timestamptz not null default now(),
    constraint ux_repair_quotes_request_assignment_version unique (request_id, assignment_id, version),
    constraint ck_repair_quotes_status check (status in ('pending', 'approved', 'rejected', 'expired', 'superseded')),
    constraint ck_repair_quotes_currency check (currency is null or currency = 'RUB'),
    constraint ck_repair_quotes_zero_cost check (amount_minor is distinct from 0 or zero_cost_reason is not null)
);

CREATE INDEX ix_repair_quotes_request_id ON repair_quotes (request_id);
CREATE INDEX ix_repair_quotes_assignment_id ON repair_quotes (assignment_id);
CREATE INDEX ix_repair_quotes_responded_by ON repair_quotes (responded_by_membership_id);
CREATE INDEX ix_repair_quotes_created_by ON repair_quotes (created_by_membership_id);
CREATE INDEX ix_repair_quotes_valid_until ON repair_quotes (valid_until) WHERE status = 'pending';

CREATE TABLE cancellation_requests (
    id                          uuid primary key default uuidv7(),
    request_id                   uuid not null references repair_requests (id),
    assignment_id                  uuid not null references assignments (id),
    target                          text not null,
    previous_status                  text not null,
    initiated_by_membership_id        uuid not null references memberships (id),
    reason                              text,
    status                               text not null default 'pending',
    provider_response                     text,
    disputed                               boolean not null default false,
    dispute_deadline_at                     timestamptz,
    resolution_kind                          text,
    resolved_at                                timestamptz,
    resolved_by_membership_id                   uuid references memberships (id),
    created_at                                   timestamptz not null default now(),
    updated_at                                    timestamptz not null default now(),
    constraint ck_cancellation_requests_target check (target in ('cancel_request', 'change_provider')),
    constraint ck_cancellation_requests_status check (status in ('pending', 'accepted', 'disputed', 'withdrawn', 'force_closed')),
    constraint ck_cancellation_requests_resolution_kind check (resolution_kind is null or resolution_kind in ('provider_confirmed', 'customer_unilateral', 'manual'))
);

CREATE INDEX ix_cancellation_requests_request_id ON cancellation_requests (request_id);
CREATE INDEX ix_cancellation_requests_assignment_id ON cancellation_requests (assignment_id);
CREATE INDEX ix_cancellation_requests_initiated_by ON cancellation_requests (initiated_by_membership_id);
CREATE INDEX ix_cancellation_requests_dispute_deadline ON cancellation_requests (dispute_deadline_at) WHERE status = 'disputed';

CREATE TABLE messages (
    id                              uuid primary key default uuidv7(),
    request_id                       uuid not null references repair_requests (id),
    visibility_scope                   text not null default 'all_participants',
    thread_provider_org_id               uuid references organizations (id),
    author_kind                           text not null,
    author_membership_id                   uuid references memberships (id),
    author_integration_client_id             uuid,
    body                                      text not null,
    created_at                                 timestamptz not null default now(),
    constraint ck_messages_visibility_scope check (visibility_scope in ('all_participants', 'pre_assignment_thread')),
    constraint ck_messages_thread_provider check ((visibility_scope = 'pre_assignment_thread') = (thread_provider_org_id is not null)),
    constraint ck_messages_author_kind check (author_kind in ('customer_membership', 'provider_membership', 'integration_client', 'system')),
    constraint ck_messages_author check (
        (author_kind in ('customer_membership', 'provider_membership') and author_membership_id is not null and author_integration_client_id is null)
        or (author_kind = 'integration_client' and author_integration_client_id is not null and author_membership_id is null)
        or (author_kind = 'system' and author_membership_id is null and author_integration_client_id is null)
    )
);

CREATE INDEX ix_messages_request_id ON messages (request_id);
CREATE INDEX ix_messages_thread_provider_org_id ON messages (thread_provider_org_id);
CREATE INDEX ix_messages_author_membership_id ON messages (author_membership_id);
CREATE INDEX ix_messages_created_at ON messages (request_id, created_at);

CREATE TABLE request_events (
    id                              uuid primary key default uuidv7(),
    request_id                       uuid not null references repair_requests (id),
    occurred_at                        timestamptz not null default now(),
    actor_kind                          text not null,
    actor_membership_id                  uuid references memberships (id),
    actor_integration_client_id            uuid,
    actor_user_id                           uuid references users (id),
    event_type                               text not null,
    from_status                               text,
    to_status                                  text,
    payload                                     jsonb not null default '{}'::jsonb,
    created_at                                   timestamptz not null default now(),
    constraint ck_request_events_actor_kind check (actor_kind in ('customer_membership', 'provider_membership', 'integration_client', 'system', 'operator'))
);

CREATE INDEX ix_request_events_request_id ON request_events (request_id, occurred_at);
CREATE INDEX ix_request_events_actor_membership_id ON request_events (actor_membership_id);

CREATE TABLE attachments (
    id                          uuid primary key default uuidv7(),
    owner_kind                   text not null,
    request_id                    uuid references repair_requests (id),
    message_id                     uuid references messages (id),
    provider_profile_id             uuid references provider_profiles (id),
    review_id                        uuid,
    verification_case_id              uuid references verification_cases (id),
    moderation_case_id                 uuid,
    uploaded_by_membership_id           uuid references memberships (id),
    uploaded_by_integration_client_id     uuid,
    uploaded_by_user_id                    uuid references users (id),
    purpose                                 text,
    visibility_class                         text not null,
    mime_type                                 text not null,
    byte_size                                  bigint not null,
    pixel_width                                 integer,
    pixel_height                                 integer,
    storage_key                                   text not null,
    processing_state                               text not null default 'quarantined',
    rejected_reason                                 text,
    content_hash                                     bytea,
    created_at                                        timestamptz not null default now(),
    updated_at                                         timestamptz not null default now(),
    constraint ck_attachments_owner_kind check (owner_kind in ('request', 'message', 'profile', 'review', 'verification', 'moderation')),
    constraint ck_attachments_owner_ref check (
        (owner_kind = 'request' and request_id is not null)
        or (owner_kind = 'message' and message_id is not null and request_id is not null)
        or (owner_kind = 'profile' and provider_profile_id is not null)
        or (owner_kind = 'review' and review_id is not null)
        or (owner_kind = 'verification' and verification_case_id is not null)
        or (owner_kind = 'moderation' and moderation_case_id is not null)
    ),
    constraint ck_attachments_visibility_class check (visibility_class in (
        'request_private', 'request_sensitive', 'public_card', 'profile_public', 'review_public', 'verification_evidence'
    )),
    constraint ck_attachments_processing_state check (processing_state in ('quarantined', 'ready', 'rejected'))
);

CREATE INDEX ix_attachments_request_id ON attachments (request_id);
CREATE INDEX ix_attachments_message_id ON attachments (message_id);
CREATE INDEX ix_attachments_provider_profile_id ON attachments (provider_profile_id);
CREATE INDEX ix_attachments_verification_case_id ON attachments (verification_case_id);
CREATE INDEX ix_attachments_content_hash ON attachments (content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX ix_attachments_processing_state ON attachments (processing_state) WHERE processing_state = 'quarantined';

CREATE TABLE attachment_variants (
    id              uuid primary key default uuidv7(),
    attachment_id   uuid not null references attachments (id),
    variant_kind    text not null,
    storage_key     text not null,
    mime_type       text not null,
    byte_size       bigint not null,
    pixel_width     integer,
    pixel_height    integer,
    exif_stripped   boolean not null default false,
    created_at      timestamptz not null default now(),
    constraint ux_attachment_variants unique (attachment_id, variant_kind),
    constraint ck_attachment_variants_kind check (variant_kind in ('original', 'safe_copy', 'preview', 'public_copy'))
);

CREATE INDEX ix_attachment_variants_attachment_id ON attachment_variants (attachment_id);

CREATE TABLE reviews (
    id                          uuid primary key default uuidv7(),
    assignment_id                 uuid not null references assignments (id),
    request_id                     uuid not null references repair_requests (id),
    customer_org_id                  uuid not null references organizations (id),
    provider_org_id                    uuid not null references organizations (id),
    author_membership_id                uuid not null references memberships (id),
    rating                                smallint not null,
    text_body                              text,
    show_customer_name                       boolean not null default false,
    moderation_status                         text not null default 'pending',
    moderation_reason                          text,
    suspected_fraud                             boolean not null default false,
    current_version                              integer not null default 1,
    order_occurred_at                             timestamptz not null,
    created_at                                     timestamptz not null default now(),
    updated_at                                      timestamptz not null default now(),
    constraint ux_reviews_assignment_customer unique (assignment_id, customer_org_id),
    constraint ck_reviews_rating check (rating between 1 and 5),
    constraint ck_reviews_moderation_status check (moderation_status in ('pending', 'published', 'rejected', 'removed'))
);

CREATE INDEX ix_reviews_provider_org_id ON reviews (provider_org_id, moderation_status);
CREATE INDEX ix_reviews_customer_org_id ON reviews (customer_org_id);
CREATE INDEX ix_reviews_request_id ON reviews (request_id);
CREATE INDEX ix_reviews_author_membership_id ON reviews (author_membership_id);

ALTER TABLE attachments
    ADD CONSTRAINT fk_attachments_review
    FOREIGN KEY (review_id) REFERENCES reviews (id);

CREATE INDEX ix_attachments_review_id ON attachments (review_id) WHERE review_id IS NOT NULL;

CREATE TABLE review_versions (
    id                      uuid primary key default uuidv7(),
    review_id               uuid not null references reviews (id),
    version                 integer not null,
    rating                  smallint not null,
    text_body               text,
    moderation_status       text not null,
    edited_by_membership_id uuid references memberships (id),
    created_at              timestamptz not null default now(),
    constraint ux_review_versions unique (review_id, version),
    constraint ck_review_versions_rating check (rating between 1 and 5)
);

CREATE INDEX ix_review_versions_review_id ON review_versions (review_id);

CREATE TABLE review_replies (
    id                  uuid primary key default uuidv7(),
    review_id           uuid not null references reviews (id),
    provider_org_id     uuid not null references organizations (id),
    author_membership_id uuid not null references memberships (id),
    body                text not null,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint ux_review_replies_review unique (review_id)
);

CREATE INDEX ix_review_replies_provider_org_id ON review_replies (provider_org_id);

CREATE TABLE moderation_cases (
    id                          uuid primary key default uuidv7(),
    subject_type                  text not null,
    provider_profile_id             uuid references provider_profiles (id),
    review_id                        uuid references reviews (id),
    attachment_id                     uuid references attachments (id),
    service_binding_id                 uuid references service_bindings (id),
    assignment_id                       uuid references assignments (id),
    filer_org_id                         uuid references organizations (id),
    filer_membership_id                   uuid references memberships (id),
    operator_user_id                       uuid references users (id),
    status                                  text not null default 'pending',
    evidence                                 jsonb not null default '{}'::jsonb,
    decision_reason                           text,
    appeal_status                              text,
    appeal_resolved_at                          timestamptz,
    created_at                                   timestamptz not null default now(),
    updated_at                                    timestamptz not null default now(),
    constraint ck_moderation_cases_subject_type check (subject_type in ('provider_profile', 'review', 'attachment', 'service_binding', 'no_show')),
    constraint ck_moderation_cases_status check (status in ('pending', 'published', 'rejected', 'removed'))
);

CREATE INDEX ix_moderation_cases_provider_profile_id ON moderation_cases (provider_profile_id);
CREATE INDEX ix_moderation_cases_review_id ON moderation_cases (review_id);
CREATE INDEX ix_moderation_cases_attachment_id ON moderation_cases (attachment_id);
CREATE INDEX ix_moderation_cases_service_binding_id ON moderation_cases (service_binding_id);
CREATE INDEX ix_moderation_cases_assignment_id ON moderation_cases (assignment_id);
CREATE INDEX ix_moderation_cases_filer_org_id ON moderation_cases (filer_org_id);
CREATE INDEX ix_moderation_cases_pending ON moderation_cases (status) WHERE status = 'pending';

ALTER TABLE attachments
    ADD CONSTRAINT fk_attachments_moderation_case
    FOREIGN KEY (moderation_case_id) REFERENCES moderation_cases (id);

CREATE INDEX ix_attachments_moderation_case_id ON attachments (moderation_case_id) WHERE moderation_case_id IS NOT NULL;

CREATE TABLE provider_rating_aggregates (
    id                          uuid primary key default uuidv7(),
    provider_org_id               uuid not null references organizations (id),
    average_rating                  numeric(2, 1),
    unique_reviewer_orgs_count        integer not null default 0,
    published_reviews_count            integer not null default 0,
    updated_at                          timestamptz not null default now(),
    constraint ux_provider_rating_aggregates_provider unique (provider_org_id),
    constraint ck_provider_rating_aggregates_rating check (average_rating is null or (average_rating >= 1.0 and average_rating <= 5.0))
);

CREATE TABLE integration_clients (
    id                      uuid primary key default uuidv7(),
    provider_org_id          uuid not null references organizations (id),
    name                       text not null,
    api_key_hash                bytea not null,
    api_key_prefix                text not null,
    scopes                          text[] not null default '{}',
    status                           text not null default 'active',
    created_by_membership_id          uuid references memberships (id),
    rotated_at                          timestamptz,
    revoked_at                           timestamptz,
    created_at                            timestamptz not null default now(),
    updated_at                             timestamptz not null default now(),
    constraint ux_integration_clients_api_key_hash unique (api_key_hash),
    constraint ck_integration_clients_status check (status in ('active', 'revoked'))
);

CREATE INDEX ix_integration_clients_provider_org_id ON integration_clients (provider_org_id);
CREATE INDEX ix_integration_clients_api_key_prefix ON integration_clients (api_key_prefix);

ALTER TABLE messages
    ADD CONSTRAINT fk_messages_author_integration_client
    FOREIGN KEY (author_integration_client_id) REFERENCES integration_clients (id);

CREATE INDEX ix_messages_author_integration_client_id ON messages (author_integration_client_id);

CREATE TABLE external_references (
    id                      uuid primary key default uuidv7(),
    integration_client_id    uuid not null references integration_clients (id),
    provider_org_id           uuid not null references organizations (id),
    request_id                 uuid not null references repair_requests (id),
    external_id                  text not null,
    created_at                     timestamptz not null default now(),
    constraint ux_external_references_client_external unique (integration_client_id, external_id),
    constraint ux_external_references_client_request unique (integration_client_id, request_id)
);

CREATE INDEX ix_external_references_provider_org_id ON external_references (provider_org_id);
CREATE INDEX ix_external_references_request_id ON external_references (request_id);

CREATE TABLE webhook_subscriptions (
    id                      uuid primary key default uuidv7(),
    integration_client_id    uuid not null references integration_clients (id),
    provider_org_id           uuid not null references organizations (id),
    url                        text not null,
    event_types                  text[] not null,
    secret_encrypted               bytea not null,
    status                          text not null default 'active',
    created_by_membership_id         uuid references memberships (id),
    created_at                        timestamptz not null default now(),
    updated_at                         timestamptz not null default now(),
    disabled_at                         timestamptz,
    constraint ck_webhook_subscriptions_status check (status in ('active', 'disabled'))
);

CREATE INDEX ix_webhook_subscriptions_integration_client_id ON webhook_subscriptions (integration_client_id);
CREATE INDEX ix_webhook_subscriptions_provider_org_id ON webhook_subscriptions (provider_org_id);

CREATE TABLE integration_events (
    id                  uuid primary key default uuidv7(),
    event_type          text not null,
    recipient_org_id    uuid not null references organizations (id),
    feed_seq            bigint,
    resource_kind       text not null,
    resource_id         uuid not null,
    resource_version    integer,
    occurred_at         timestamptz not null default now(),
    payload             jsonb not null,
    created_at          timestamptz not null default now(),
    constraint ck_integration_events_type check (event_type in (
        'request.assigned', 'request.changed', 'message.created', 'offer.selected',
        'assignment.revoked', 'visit_proposal.responded', 'repair_quote.responded',
        'cancellation.requested', 'request.closed', 'service_binding.changed',
        'marketplace.request.available', 'marketplace.request.closed'
    ))
);

CREATE UNIQUE INDEX ux_integration_events_recipient_feed_seq
    ON integration_events (recipient_org_id, feed_seq) WHERE feed_seq IS NOT NULL;
CREATE INDEX ix_integration_events_recipient_unassigned
    ON integration_events (created_at) WHERE feed_seq IS NULL;
CREATE INDEX ix_integration_events_resource ON integration_events (resource_kind, resource_id);
CREATE INDEX ix_integration_events_created_at ON integration_events (created_at);

CREATE TABLE webhook_deliveries (
    id                      uuid primary key default uuidv7(),
    integration_event_id     uuid not null references integration_events (id),
    webhook_subscription_id    uuid not null references webhook_subscriptions (id),
    provider_org_id              uuid not null references organizations (id),
    state                          text not null default 'queued',
    current_delivery_id              uuid not null default uuidv7(),
    attempt_count                      integer not null default 0,
    next_attempt_at                      timestamptz,
    last_attempt_at                        timestamptz,
    last_http_status                        integer,
    last_error                               text,
    expires_at                                timestamptz not null,
    created_at                                  timestamptz not null default now(),
    updated_at                                   timestamptz not null default now(),
    constraint ck_webhook_deliveries_state check (state in ('queued', 'delivered', 'retrying', 'failed'))
);

CREATE INDEX ix_webhook_deliveries_integration_event_id ON webhook_deliveries (integration_event_id);
CREATE INDEX ix_webhook_deliveries_subscription_id ON webhook_deliveries (webhook_subscription_id);
CREATE INDEX ix_webhook_deliveries_provider_org_id ON webhook_deliveries (provider_org_id);
CREATE INDEX ix_webhook_deliveries_outbox_queue ON webhook_deliveries (state, next_attempt_at) WHERE state IN ('queued', 'retrying');

CREATE TABLE bot_conversations (
    id                          uuid primary key default uuidv7(),
    user_id                       uuid not null references users (id),
    max_chat_id                    text not null,
    current_step                     text,
    context                             jsonb not null default '{}'::jsonb,
    active_organization_id               uuid references organizations (id),
    active_membership_id                   uuid references memberships (id),
    created_at                              timestamptz not null default now(),
    updated_at                               timestamptz not null default now(),
    constraint ux_bot_conversations_chat unique (max_chat_id)
);

CREATE INDEX ix_bot_conversations_user_id ON bot_conversations (user_id);
CREATE INDEX ix_bot_conversations_active_membership_id ON bot_conversations (active_membership_id);

CREATE TABLE bot_actions (
    id                          uuid primary key default uuidv7(),
    code                          text not null,
    action_type                    text not null,
    object_type                      text,
    object_id                          uuid,
    expected_version                     integer,
    proposal_version                       integer,
    created_by_bot_conversation_id           uuid references bot_conversations (id),
    expires_at                                 timestamptz not null,
    consumed_at                                  timestamptz,
    created_at                                    timestamptz not null default now(),
    constraint ux_bot_actions_code unique (code)
);

CREATE INDEX ix_bot_actions_conversation_id ON bot_actions (created_by_bot_conversation_id);
CREATE INDEX ix_bot_actions_object ON bot_actions (object_type, object_id);
CREATE INDEX ix_bot_actions_expires_at ON bot_actions (expires_at) WHERE consumed_at IS NULL;

CREATE TABLE max_updates (
    id                  uuid primary key default uuidv7(),
    max_update_id        text not null,
    update_type            text,
    raw_payload              jsonb not null,
    received_at                timestamptz not null default now(),
    processed_at                 timestamptz,
    processing_error               text,
    created_at                       timestamptz not null default now(),
    constraint ux_max_updates_update_id unique (max_update_id)
);

CREATE INDEX ix_max_updates_unprocessed ON max_updates (received_at) WHERE processed_at IS NULL;

CREATE TABLE notifications (
    id                          uuid primary key default uuidv7(),
    recipient_user_id             uuid not null references users (id),
    recipient_membership_id         uuid references memberships (id),
    organization_id                   uuid references organizations (id),
    request_id                          uuid references repair_requests (id),
    notification_type                     text not null,
    payload                                 jsonb not null default '{}'::jsonb,
    state                                    text not null default 'queued',
    attempt_count                              integer not null default 0,
    next_attempt_at                              timestamptz,
    sent_at                                        timestamptz,
    last_error                                       text,
    created_at                                         timestamptz not null default now(),
    constraint ck_notifications_state check (state in ('queued', 'sent', 'failed'))
);

CREATE INDEX ix_notifications_recipient_user_id ON notifications (recipient_user_id);
CREATE INDEX ix_notifications_organization_id ON notifications (organization_id);
CREATE INDEX ix_notifications_request_id ON notifications (request_id);
CREATE INDEX ix_notifications_outbox_queue ON notifications (state, next_attempt_at) WHERE state = 'queued';

CREATE TABLE idempotency_keys (
    id                      uuid primary key default uuidv7(),
    scope                     text not null,
    key                         text not null,
    organization_id               uuid references organizations (id),
    integration_client_id           uuid references integration_clients (id),
    membership_id                     uuid references memberships (id),
    request_path                        text not null,
    request_body_hash                     bytea not null,
    response_status                         integer,
    response_body                             jsonb,
    expires_at                                  timestamptz not null,
    created_at                                    timestamptz not null default now(),
    constraint ux_idempotency_keys_scope_key unique (scope, key)
);

CREATE INDEX ix_idempotency_keys_organization_id ON idempotency_keys (organization_id);
CREATE INDEX ix_idempotency_keys_integration_client_id ON idempotency_keys (integration_client_id);
CREATE INDEX ix_idempotency_keys_expires_at ON idempotency_keys (expires_at);

CREATE TABLE audit_entries (
    id                          uuid primary key default uuidv7(),
    actor_kind                    text not null,
    actor_user_id                   uuid references users (id),
    actor_integration_client_id       uuid references integration_clients (id),
    organization_id                     uuid references organizations (id),
    object_type                           text not null,
    object_id                               uuid,
    action                                    text not null,
    result                                     text not null,
    details                                      jsonb not null default '{}'::jsonb,
    occurred_at                                    timestamptz not null default now(),
    created_at                                       timestamptz not null default now(),
    constraint ck_audit_entries_actor_kind check (actor_kind in ('user', 'operator', 'integration_client', 'system')),
    constraint ck_audit_entries_result check (result in ('success', 'failure', 'denied'))
);

CREATE INDEX ix_audit_entries_organization_id ON audit_entries (organization_id, occurred_at);
CREATE INDEX ix_audit_entries_actor_user_id ON audit_entries (actor_user_id);
CREATE INDEX ix_audit_entries_actor_integration_client_id ON audit_entries (actor_integration_client_id);
CREATE INDEX ix_audit_entries_object ON audit_entries (object_type, object_id);

