import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useProvidersCatalog } from '../../api/hooks/useProviders';
import { useCities, useEquipmentCategories } from '../../api/hooks/useDirectories';
import type { ProviderCatalogItem } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { Screen } from '../../ui/layout/Screen';
import { Chips, FilterChip } from '../../ui/Chips';
import { List, ListRow } from '../../ui/List';
import { StatusHero } from '../../ui/StatusHero';
import { initials } from '../../ui/format';
import { countLabel, gradientFor, hasRating, ratingValue } from '../reviews/reputation';

function subtitleOf(item: ProviderCatalogItem): string {
  const kind = strings.provider.catalogKind[item.provider_kind];
  const categories = item.categories.map((c) => c.name.toLowerCase()).join(', ');
  return categories ? `${kind} · ${categories}` : kind;
}

const MIN_RATED_CUSTOMERS = 3;

function ratingTagOf(item: ProviderCatalogItem): string {
  if (item.rating_label) return item.rating_label;
  if (!hasRating(item.rating) || item.unique_customers < MIN_RATED_CUSTOMERS) {
    return strings.provider.publicProfileRatingFew;
  }
  return strings.provider.ratingTagWithOrgs(
    ratingValue(item.rating),
    countLabel(item.unique_customers, strings.provider.orgForms),
  );
}

export function ProviderCatalogScreen() {
  const [categoryId, setCategoryId] = useState('');
  const [cityId, setCityId] = useState('');
  const [districtId, setDistrictId] = useState('');

  const cities = useCities();
  const categories = useEquipmentCategories();
  const catalog = useProvidersCatalog({
    categoryId: categoryId || undefined,
    cityId: cityId || undefined,
    districtId: districtId || undefined,
  });

  const selectedCity = cities.data?.find((c) => c.id === cityId);
  const filtered = Boolean(categoryId || cityId || districtId);

  return (
    <Screen title={strings.provider.catalogHeader}>
      <Chips label={strings.provider.catalogFiltersLabel}>
        <FilterChip
          label={strings.provider.catalogFilterCategory}
          allLabel={strings.provider.catalogAllCategories}
          value={categoryId}
          options={(categories.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          onChange={setCategoryId}
        />
        <FilterChip
          label={strings.provider.catalogFilterCity}
          allLabel={strings.provider.catalogAllCities}
          value={cityId}
          options={(cities.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          onChange={(value) => {
            setCityId(value);
            setDistrictId('');
          }}
        />
        {selectedCity && selectedCity.districts.length > 0 && (
          <FilterChip
            label={strings.provider.catalogFilterDistrict}
            allLabel={strings.provider.catalogAllDistricts}
            value={districtId}
            options={selectedCity.districts.map((d) => ({ value: d.id, label: d.name }))}
            onChange={setDistrictId}
          />
        )}
      </Chips>

      {catalog.isPending ? (
        <Skeleton lines={4} />
      ) : catalog.isError ? (
        <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} />
      ) : catalog.data.length === 0 ? (
        <>
          <StatusHero icon="—" top={40} title={strings.provider.catalogEmpty} />
          {filtered && (
            <List>
              <ListRow
                title={strings.requests.resetFilters}
                action="accent"
                onClick={() => {
                  setCategoryId('');
                  setCityId('');
                  setDistrictId('');
                }}
              />
            </List>
          )}
        </>
      ) : (
        <List>
          {catalog.data.map((item) => (
            <ListRow
              key={item.id}
              icon={initials(item.name)}
              gradient={gradientFor(item.id)}
              title={item.name}
              subtitle={subtitleOf(item)}
              tag={{ label: ratingTagOf(item), tone: 'w' }}
              value={item.accepting_new_requests ? undefined : strings.provider.catalogNotAccepting}
              valueTone="secondary"
              to={`/providers/${item.id}`}
              chevron
            />
          ))}
        </List>
      )}
    </Screen>
  );
}
