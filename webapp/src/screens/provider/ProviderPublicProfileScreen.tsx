import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canManageRequestApprovals } from '../../lib/roles';
import { useProviderPublicProfile } from '../../api/hooks/useProviders';
import { useProviderReviewsInfinite } from '../../api/hooks/useReviews';
import type {
  ProviderPublicProfile,
  VerificationBadge,
  WarrantyAuthorization,
} from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Avatar, Note, SectionCaption, Tag, TextCard } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { PhotoGrid, PhotoTile } from '../../ui/PhotoGrid';
import { ComplaintButton } from '../reviews/ComplaintButton';
import { countLabel, hasRating, ratingValue, shortDate } from '../reviews/reputation';
import './components/workspace.css';
import './components/profile.css';

const GALLERY_PREVIEW = 6;

function areaNames(p: ProviderPublicProfile): string[] {
  return Array.from(new Set(p.service_areas.map((a) => a.district_name ?? a.city_name)));
}

function areasText(p: ProviderPublicProfile): string {
  const cities = Array.from(new Set(p.service_areas.map((a) => a.city_name)));
  const districts = p.service_areas.map((a) => a.district_name).filter(Boolean) as string[];
  if (districts.length === 0) return cities.join(', ');
  return strings.provider.publicProfileAreasText(cities.join(', '), districts);
}

function badgeSubtitle(badge: VerificationBadge): string {
  if (!badge.confirmed) return strings.provider.publicProfileNotConfirmed;
  const date = badge.checked_at ? shortDate(badge.checked_at, true) : null;
  const head =
    badge.source && date
      ? strings.provider.publicProfileCheckSource(badge.source, date)
      : (badge.source ?? date ?? strings.provider.publicProfileConfirmed);
  return badge.valid_until
    ? `${head}, ${strings.provider.publicProfileCheckValidUntil(shortDate(badge.valid_until, true))}`
    : head;
}

function BadgeRow({ badge }: { badge: VerificationBadge }) {
  const [open, setOpen] = useState(false);
  return (
    <ListRow
      title={badge.title}
      subtitle={badgeSubtitle(badge)}
      marker={badge.confirmed ? 'ok' : '-'}
      tag={badge.is_demo ? { label: strings.provider.demoBadgeLabel, tone: 'y' } : undefined}
      expanded={open}
      aria-label={`${badge.title}: ${badgeSubtitle(badge)}. ${strings.provider.publicProfileCheckDetails}`}
      onClick={() => setOpen((v) => !v)}
      extra={
        open ? (
          <span className="ui-row__sub">
            {strings.provider.publicProfileConfirmed}: {badge.explanation}
            <br />
            {strings.provider.publicProfileNotConfirmed}: {badge.limitation}
          </span>
        ) : undefined
      }
    />
  );
}

function WarrantyRow({ warranty }: { warranty: WarrantyAuthorization }) {
  const active = warranty.status === 'active';
  const brands = warranty.brands.join(', ');
  const guarantor = warranty.guarantor_name ?? strings.common.notSpecified;
  return (
    <ListRow
      title={
        brands
          ? strings.provider.publicProfileWarrantyRowBrands(brands)
          : strings.provider.publicProfileWarrantyRow
      }
      subtitle={
        !active
          ? strings.provider.publicProfileWarrantyPending
          : warranty.valid_until
            ? strings.provider.publicProfileWarrantyUntil(
                guarantor,
                shortDate(warranty.valid_until, true),
              )
            : guarantor
      }
      marker={active ? 'ok' : '-'}
      tag={warranty.is_demo ? { label: strings.provider.demoBadgeLabel, tone: 'y' } : undefined}
    />
  );
}

function BrandsRow({ brands }: { brands: string[] }) {
  return (
    <ListRow
      title={strings.provider.publicProfileBrandsCheck}
      subtitle={
        brands.length > 0
          ? strings.provider.publicProfileBrandsStated
          : strings.provider.publicProfileNoRestrictions
      }
      marker="-"
      extra={
        brands.length > 0 ? (
          <span className="pw-brands">
            {brands.map((brand) => (
              <span key={brand} className="pw-brand">
                {brand}
              </span>
            ))}
          </span>
        ) : undefined
      }
    />
  );
}

function StatTiles({ p }: { p: ProviderPublicProfile }) {
  const rated = hasRating(p.rating) && !p.rating_label;
  const areas = areaNames(p).length;
  return (
    <div className="pw-stats">
      <div className="pw-stat">
        <span className="pw-stat__value">{rated ? ratingValue(p.rating!) : '—'}</span>
        <span className="pw-stat__label">
          {rated
            ? countLabel(p.reviews_count, strings.provider.ratingForms)
            : (p.rating_label ?? strings.provider.reviewsFewTitle)}
        </span>
      </div>
      <div className="pw-stat">
        <span className="pw-stat__value">{p.unique_customers}</span>
        <span className="pw-stat__label">
          {countLabel(p.unique_customers, strings.provider.customerForms).replace(/^\d+\s/, '')}
        </span>
      </div>
      <div className="pw-stat">
        <span className="pw-stat__value">{areas}</span>
        <span className="pw-stat__label">
          {countLabel(areas, strings.provider.areaForms).replace(/^\d+\s/, '')}
        </span>
      </div>
    </div>
  );
}

function ReviewPreview({ providerId }: { providerId: string }) {
  const reviews = useProviderReviewsInfinite(providerId);
  const first = reviews.data?.pages[0]?.items[0];
  if (!first) return null;
  return (
    <div className="pw-review">
      <div className="pw-review__head">
        <span className="pw-review__author">{first.author_display_name}</span>
        <span className="pw-review__meta">
          {strings.provider.reviewPreviewMeta(first.rating, shortDate(first.published_at))}
        </span>
      </div>
      {first.text && <p className="pw-review__text">{first.text}</p>}
    </div>
  );
}

export function ProviderPublicProfileScreen() {
  const { providerId } = useParams<{ providerId: string }>();
  const [search] = useSearchParams();
  const { activeMembership } = useSession();
  const profile = useProviderPublicProfile(providerId);
  const [galleryOpen, setGalleryOpen] = useState(false);

  if (profile.isPending) {
    return (
      <Screen title={strings.provider.publicProfileHeader}>
        <Skeleton lines={8} />
      </Screen>
    );
  }
  if (profile.isError) {
    return (
      <Screen title={strings.provider.publicProfileHeader}>
        <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
      </Screen>
    );
  }

  const p = profile.data;
  const categories = p.categories.map((c) => c.name).join(', ');
  const areas = areasText(p);
  const brands = Array.from(new Set(p.brand_restrictions.map((b) => b.brand)));
  const requestId = search.get('request');
  const offerId = search.get('offer');
  const canPick =
    Boolean(requestId && offerId) &&
    Boolean(activeMembership && canManageRequestApprovals(activeMembership.role));
  const galleryItems = p.gallery_items ?? p.gallery.map((id) => ({ id, caption: null }));
  const gallery = galleryOpen ? galleryItems : galleryItems.slice(0, GALLERY_PREVIEW);

  return (
    <Screen
      title={strings.provider.publicProfileHeader}
      actions={
        canPick ? (
          <BottomActions>
            <ActionButton to={`/requests/${requestId}/offers/${offerId}`}>
              {strings.provider.publicProfilePick}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      <div className="pw-profile-head">
        <Avatar name={p.name} size={68} />
        <div className="pw-profile-head__main">
          <h2 className="pw-profile-head__name">{p.name}</h2>
          <span className="pw-profile-head__sub">
            {strings.workspace.rowSubtitle(
              categories || strings.provider.catalogKind[p.provider_kind],
              areas,
            )}
          </span>
          <span>
            <Tag tone={p.accepting_new_requests ? 'ok' : 'w'}>
              {p.accepting_new_requests
                ? strings.provider.acceptingBadge
                : strings.provider.notAcceptingBadge}
            </Tag>
          </span>
        </div>
      </div>

      <StatTiles p={p} />

      <SectionCaption>{strings.provider.publicProfileChecksTitle}</SectionCaption>
      <List className="pw-checks">
        {p.verification.map((badge) => (
          <BadgeRow key={badge.kind} badge={badge} />
        ))}
        {p.warranty_authorizations.length === 0 ? (
          <ListRow
            title={strings.provider.publicProfileWarrantyRow}
            subtitle={strings.provider.publicProfileWarrantyNone}
            marker="-"
          />
        ) : (
          p.warranty_authorizations.map((w) => <WarrantyRow key={w.id} warranty={w} />)
        )}
        <BrandsRow brands={brands} />
      </List>

      <SectionCaption
        action={
          galleryItems.length > GALLERY_PREVIEW ? (
            <button type="button" onClick={() => setGalleryOpen((v) => !v)}>
              {galleryOpen
                ? strings.provider.publicProfileGalleryLess
                : strings.provider.publicProfileGalleryAll(galleryItems.length)}
            </button>
          ) : undefined
        }
      >
        {strings.provider.publicProfileWorksRow}
      </SectionCaption>
      {galleryItems.length > 0 ? (
        <PhotoGrid label={strings.provider.publicProfileGalleryTitle}>
          {gallery.map((item, index) => (
            <PhotoTile
              key={item.id}
              attachmentId={item.id}
              alt={item.caption ?? strings.provider.publicProfileGalleryPhotoAlt(index + 1)}
              label={item.caption ?? undefined}
            />
          ))}
        </PhotoGrid>
      ) : (
        <p className="pw-muted">{strings.provider.publicProfileGalleryEmpty}</p>
      )}

      <SectionCaption
        action={
          <Link
            to={`/providers/${p.id}/reviews`}
            aria-label={`${
              hasRating(p.rating) && !p.rating_label
                ? strings.provider.publicProfileReviewsRow(ratingValue(p.rating))
                : strings.provider.publicProfileReviewsTitle
            }, ${strings.provider.publicProfileReviewsAll(p.reviews_count).toLowerCase()}`}
          >
            {strings.provider.publicProfileReviewsAll(p.reviews_count)}
          </Link>
        }
      >
        {strings.provider.publicProfileReviewsTitle}
      </SectionCaption>
      {p.reviews_count > 0 ? (
        <ReviewPreview providerId={p.id} />
      ) : (
        <p className="pw-muted">{strings.provider.publicProfileReviewsEmpty}</p>
      )}

      <SectionCaption>{strings.provider.publicProfileSpecializationCaption}</SectionCaption>
      <List>
        <ListRow
          title={strings.provider.publicProfileCategoriesRow}
          subtitle={categories || strings.common.notSpecified}
        />
        {areas && <ListRow title={strings.provider.publicProfileAreasRow} subtitle={areas} />}
        {p.visit_terms && <ListRow title={strings.provider.visitTerms} subtitle={p.visit_terms} />}
      </List>
      <Note>{p.specialization_disclaimer}</Note>
      {p.description && (
        <>
          <SectionCaption>{strings.provider.publicProfileDescriptionCaption}</SectionCaption>
          <TextCard>{p.description}</TextCard>
        </>
      )}

      <List>
        <ComplaintButton variant="row" subjectType="provider_profile" targetId={p.id} />
      </List>
    </Screen>
  );
}
