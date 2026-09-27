import { lazy, Suspense, useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import {
  canAccessIntegration,
  canManageProviderProfile,
  canRespondToBindings,
} from '../../lib/roles';
import { canEditProfileFields, canEditRequisites, canToggleAccepting } from '../../lib/trust';
import {
  usePortfolio,
  useProviderProfile,
  useSetAcceptingNewRequests,
  useUpdateProviderProfile,
} from '../../api/hooks/useProviderProfile';
import { useCities, useEquipmentCategories } from '../../api/hooks/useDirectories';
import { useStaff } from '../../api/hooks/useMemberships';
import { useIntegrationSummary } from '../../api/hooks/useIntegration';
import type { Attachment, City, EquipmentCategory, ProviderProfile } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { SectionLinks } from '../../components/layout/SectionLinks';
import { ThemeSwitcher } from '../../ui/theme/ThemeSwitcher';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { useLayout } from '../../ui/layout/layoutContext';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { ChipGroup } from '../../ui/Chips';
import { PhotoGrid, PhotoTile, type PhotoState } from '../../ui/PhotoGrid';
import { ToggleTrack } from '../../ui/Toggle';
import { formatAmountMinor } from '../../lib/money';
import { countLabel, hasRating, ratingValue } from '../reviews/reputation';
import { WorkspaceHeader } from '../../ui/WorkspaceHeader';
import './components/profile.css';
import { ProfileStatusBlock } from './profile/ProfileStatusBlock';
import { ProviderRegistrationForm } from './profile/ProviderRegistrationForm';
import { ProviderTermsForm } from './profile/ProviderTermsForm';
import { draftFromProfile, payloadFromDraft, type ProfileDraft } from './profile/profileDraft';

const ProviderPortfolioSection = lazy(() =>
  import('./ProviderPortfolioSection').then((m) => ({ default: m.ProviderPortfolioSection })),
);

type Section = 'edit' | 'terms' | 'portfolio';
const PORTFOLIO_FALLBACK_LIMIT = 10;
const SECTIONS = new Set<string>(['edit', 'terms', 'portfolio']);

function heroSubtitle(profile: ProviderProfile, cities: City[] | undefined): string {
  const kind =
    profile.provider_kind === 'company'
      ? strings.provider.kindCompany
      : profile.legal_form === 'self_employed'
        ? strings.provider.kindSelfEmployed
        : strings.provider.kindIp;
  const places = profile.service_areas.map((area) => {
    const city = cities?.find((c) => c.id === area.city_id);
    return area.district_id
      ? (city?.districts.find((d) => d.id === area.district_id)?.name ?? null)
      : (city?.name ?? null);
  });
  return [kind, Array.from(new Set(places.filter(Boolean))).join(', ')].filter(Boolean).join(' · ');
}

function reviewsValue(profile: ProviderProfile): string | undefined {
  if (hasRating(profile.rating) && !profile.rating_label) return `★ ${ratingValue(profile.rating)}`;
  if (profile.rating_label) return profile.rating_label;
  return profile.unique_customers > 0 ? strings.offers.providerFewReviews : undefined;
}

export function ProviderProfileScreen() {
  const { section } = useParams<{ section?: string }>();
  const { activeMembership } = useSession();
  const profile = useProviderProfile();
  const cities = useCities();
  const categories = useEquipmentCategories();

  if (!activeMembership) return null;
  if (section && !SECTIONS.has(section)) return <Navigate to="/provider/profile" replace />;

  const isAdmin = canManageProviderProfile(activeMembership.role);
  const sub = section as Section | undefined;

  if (sub === 'portfolio') {
    if (!isAdmin) return <NoAccessState />;
    return (
      <Suspense fallback={<Skeleton lines={2} />}>
        <ProviderPortfolioSection />
      </Suspense>
    );
  }

  if (profile.isPending || cities.isPending || categories.isPending) {
    return (
      <Screen title={strings.nav.providerProfile}>
        <Skeleton lines={6} />
      </Screen>
    );
  }
  const failed = profile.isError
    ? profile
    : cities.isError
      ? cities
      : categories.isError
        ? categories
        : null;
  if (failed) {
    return (
      <Screen title={strings.nav.providerProfile}>
        <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />
      </Screen>
    );
  }
  const data = profile.data!;

  if (sub === 'edit' || sub === 'terms') {
    if (!isAdmin || !canEditProfileFields(data.status))
      return <Navigate to="/provider/profile" replace />;
    return sub === 'edit' ? (
      <ProviderRegistrationForm
        profile={data}
        cities={cities.data!}
        categories={categories.data!}
      />
    ) : (
      <ProviderTermsForm profile={data} />
    );
  }

  return (
    <ProfileMain
      profile={data}
      cities={cities.data}
      categories={categories.data ?? []}
      isAdmin={isAdmin}
    />
  );
}

function ProfileMain({
  profile,
  cities,
  categories,
  isAdmin,
}: {
  profile: ProviderProfile;
  cities: City[] | undefined;
  categories: EquipmentCategory[];
  isAdmin: boolean;
}) {
  const { activeMembership } = useSession();
  const setAccepting = useSetAcceptingNewRequests();
  const updateProfile = useUpdateProviderProfile();
  const [error, setError] = useState<string | null>(null);
  const role = activeMembership!.role;
  const status = profile.status;
  const acceptingEditable = isAdmin && canToggleAccepting(status);
  const editable = isAdmin && canEditProfileFields(status);
  const draft = status === 'draft';
  const p = strings.provider;

  const handleToggleAccepting = async (checked: boolean) => {
    setError(null);
    try {
      await setAccepting.mutateAsync(checked);
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const save = async (change: Partial<ProfileDraft>) => {
    setError(null);
    try {
      const next = { ...draftFromProfile(profile), ...change };
      await updateProfile.mutateAsync(payloadFromDraft(next, canEditRequisites(status)));
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const areas = draftFromProfile(profile).areas;
  const selectedCategories = profile.categories.map((c) => c.id);

  return (
    <Screen
      title={strings.nav.providerProfile}
      actions={
        draft && isAdmin ? (
          <BottomActions>
            <ActionButton to="/provider/profile/edit">{p.fillProfile}</ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      {status === 'active' ? (
        <WorkspaceHeader
          title={profile.name}
          subtitle={heroSubtitle(profile, cities)}
          side={
            <Link className="pw-head__link" to={`/providers/${profile.organization_id}`}>
              {p.openPublicProfile}
            </Link>
          }
        />
      ) : (
        <ProfileStatusBlock profile={profile} isAdmin={isAdmin} />
      )}

      <button
        type="button"
        role="switch"
        className="pw-switch-card"
        aria-checked={profile.accepting_new_requests}
        aria-label={p.acceptingLabel}
        disabled={!acceptingEditable || setAccepting.isPending}
        onClick={() => void handleToggleAccepting(!profile.accepting_new_requests)}
      >
        <span className="pw-switch-card__main">
          <span className="pw-switch-card__title">{p.acceptingLabel}</span>
          <span className="pw-switch-card__sub">
            {!canToggleAccepting(status)
              ? p.acceptingHintLocked
              : !isAdmin
                ? p.acceptingHintAdmin
                : profile.accepting_new_requests
                ? p.acceptingOnSub
                : p.acceptingPausedSub}
          </span>
        </span>
        <ToggleTrack checked={profile.accepting_new_requests} size="l" />
      </button>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      {editable && !draft && (
        <List>
          <ListRow title="Изменить города и районы" to="/provider/profile/edit" chevron />
          <ListRow title="Изменить виды техники" to="/provider/profile/edit" chevron />
        </List>
      )}
      {!isAdmin && <Note>Города и виды техники изменяет администратор вашей организации.</Note>}

      {!draft && (
        <>
          <section className="pw-section" aria-labelledby="pf-categories">
            <div className="pw-section__head">
              <h3 className="pw-section__title" id="pf-categories">
                {p.categoriesCaptionSettings}
              </h3>
            </div>
            {editable ? (
              <ChipGroup
                multiple
                label={p.categoriesCaptionSettings}
                options={categories.map((c) => ({ value: c.id, label: c.name }))}
                value={selectedCategories}
                disabled={updateProfile.isPending}
                onChange={(next) => {
                  if (next.length > 0) void save({ categoryIds: next });
                }}
              />
            ) : (
              <StaticChips
                labels={profile.categories.map((c) => c.name)}
                empty={p.categoriesEmpty}
              />
            )}
          </section>

          {areas.map((area) => {
            const city = cities?.find((c) => c.id === area.city_id);
            const districts = city?.districts ?? [];
            return (
              <section
                key={area.city_id}
                className="pw-section"
                aria-labelledby={`pf-area-${area.city_id}`}
              >
                <div className="pw-section__head">
                  <h3 className="pw-section__title" id={`pf-area-${area.city_id}`}>
                    {areas.length > 1 && city
                      ? p.areasCaptionCity(city.name)
                      : p.areasCaptionSettings}
                  </h3>
                  <span className="pw-section__count">
                    {area.district_ids.length === 0
                      ? p.areasWholeCity
                      : countLabel(area.district_ids.length, p.districtForms)}
                  </span>
                </div>
                {editable && districts.length > 0 ? (
                  <ChipGroup
                    multiple
                    label={p.areasCaptionSettings}
                    options={districts.map((d) => ({ value: d.id, label: d.name }))}
                    value={area.district_ids}
                    disabled={updateProfile.isPending}
                    onChange={(next) =>
                      void save({
                        areas: areas.map((a) =>
                          a.city_id === area.city_id ? { ...a, district_ids: next } : a,
                        ),
                      })
                    }
                  />
                ) : (
                  <StaticChips
                    labels={
                      area.district_ids.length === 0
                        ? [city?.name ?? p.areasWholeCity]
                        : districts
                            .filter((d) => area.district_ids.includes(d.id))
                            .map((d) => d.name)
                    }
                    empty={p.areasWholeCity}
                  />
                )}
                {editable && area.district_ids.length === 0 && (
                  <p className="pw-section__note">{p.areasWholeCityHint}</p>
                )}
              </section>
            );
          })}

          {isAdmin && status !== 'rejected' && (
            <PortfolioPreview limit={profile.portfolio_max_images || PORTFOLIO_FALLBACK_LIMIT} />
          )}
        </>
      )}

      <List>
        {editable && (
          <ListRow
            title={p.requisitesRow}
            subtitle={p.categoriesCount(profile.categories.length)}
            to="/provider/profile/edit"
            chevron
          />
        )}
        <ListRow
          title={p.visitTerms}
          value={
            profile.visit_price_from_minor
              ? p.visitPriceFrom(formatAmountMinor(profile.visit_price_from_minor))
              : profile.visit_terms
                ? undefined
                : p.notFilled
          }
          valueTone={profile.visit_price_from_minor ? undefined : 'secondary'}
          subtitle={profile.visit_price_from_minor ? undefined : (profile.visit_terms ?? undefined)}
          to={editable ? '/provider/profile/terms' : undefined}
          chevron={editable}
        />
        {isAdmin && <StaffRow />}
        <ListRow
          title={p.reviewsNavTitle}
          value={reviewsValue(profile)}
          valueTone={hasRating(profile.rating) && !profile.rating_label ? undefined : 'secondary'}
          to="/provider/reviews"
          chevron
        />
        {isAdmin && <IntegrationRow allowed={canAccessIntegration(role)} />}
      </List>

      <List>
        {isAdmin && <ListRow title={p.verificationTitle} to="/provider/verification" chevron />}
        {canRespondToBindings(role) && (
          <>
            <ListRow title={strings.bindings.incomingTitle} to="/bindings/incoming" chevron />
            <ListRow title={strings.bindings.invitationsTitle} to="/bindings/invitations" chevron />
          </>
        )}
        <ListRow title={strings.complaints.myTitle} to="/complaints" chevron />
      </List>

      <SwitchOrganizationRow />
      <SectionLinks hideIntegration />
      <ThemeSwitcher />
    </Screen>
  );
}

function SwitchOrganizationRow() {
  const layout = useLayout();
  if (!layout.inLayout) return null;
  return (
    <List>
      <ListRow
        title={strings.header.switchOrganization}
        subtitle={layout.activeContext?.organization}
        action="accent"
        onClick={layout.switchOrganization}
      />
    </List>
  );
}

function StaticChips({ labels, empty }: { labels: string[]; empty: string }) {
  return (
    <span className="pw-brands">
      {(labels.length > 0 ? labels : [empty]).map((label) => (
        <span key={label} className="pw-brand">
          {label}
        </span>
      ))}
    </span>
  );
}

function PortfolioPreview({ limit }: { limit: number }) {
  const navigate = useNavigate();
  const portfolio = usePortfolio();
  const items = portfolio.data ?? [];
  const p = strings.provider;
  const open = () => navigate('/provider/profile/portfolio');
  return (
    <section className="pw-section" aria-labelledby="pf-portfolio">
      <div className="pw-section__head">
        <h3 className="pw-section__title" id="pf-portfolio">
          <Link to="/provider/profile/portfolio" className="pw-section__title-link">
            {p.portfolioScreenTitle}
          </Link>
        </h3>
        {portfolio.data && (
          <span className="pw-section__count">{p.portfolioCount(items.length, limit)}</span>
        )}
      </div>
      <PhotoGrid label={p.portfolioTitle} columns={4}>
        {items.length < limit && (
          <PhotoTile state="add" actionLabel={p.portfolioUpload} onClick={open} />
        )}
        {items.slice(0, 7).map((item, index) => (
          <PhotoTile
            key={item.id}
            state={PORTFOLIO_TILE[item.processing_state]}
            attachmentId={item.id}
            alt={strings.attachments.portfolioAlt(index + 1)}
            actionLabel={p.portfolioOpen(index + 1)}
            onClick={open}
          />
        ))}
      </PhotoGrid>
      <p className="pw-section__note">{p.portfolioHintLimit(limit)}</p>
    </section>
  );
}

const PORTFOLIO_TILE: Record<Attachment['processing_state'], PhotoState> = {
  ready: 'ok',
  quarantined: 'q',
  rejected: 'e',
};

function StaffRow() {
  const staff = useStaff();
  return (
    <ListRow
      title={strings.provider.staffRow}
      value={staff.data ? String(staff.data.length) : undefined}
      to="/organization"
      chevron
    />
  );
}

function IntegrationRow({ allowed }: { allowed: boolean }) {
  const summary = useIntegrationSummary(allowed);
  if (!allowed) return null;
  const connected = summary.data?.connected;
  return (
    <ListRow
      title={strings.provider.integrationRow}
      tag={
        summary.data
          ? connected
            ? { label: strings.integration.connected, tone: 'ok' }
            : { label: strings.integration.notConnected, tone: 'w' }
          : undefined
      }
      to="/integration"
      chevron
    />
  );
}
