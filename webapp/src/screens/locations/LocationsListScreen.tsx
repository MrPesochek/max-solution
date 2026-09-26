import { strings } from '../../strings/ru';
import { useLocations } from '../../api/hooks/useLocations';
import { useCities } from '../../api/hooks/useDirectories';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { useSession } from '../../session/SessionContext';
import { canManageLocationsAndEquipment } from '../../lib/roles';
import { List, ListRow } from '../../ui/List';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import type { City, Location } from '../../api/types';
import { countLabel } from '../reviews/reputation';

function placeSubtitle(location: Location, cities: City[] | undefined): string {
  const city = cities?.find((c) => c.id === location.city_id);
  const district = city?.districts.find((d) => d.id === location.district_id);
  const area = [city?.name, district?.name].filter(Boolean).join(', ');
  const count =
    typeof location.equipment_count === 'number'
      ?
        countLabel(location.equipment_count, strings.locations.equipmentForms).replace(
          ' ',
          '\u00a0',
        )
      : location.address;
  return [area, count].filter(Boolean).join(' · ');
}

export function LocationsListScreen() {
  const { activeMembership } = useSession();
  const locations = useLocations();
  const cities = useCities();

  if (!activeMembership) return null;
  const canManage = canManageLocationsAndEquipment(activeMembership.role);

  if (activeMembership.side !== 'customer') {
    return (
      <Screen title={strings.locations.title}>
        <EmptyState title={strings.states.empty} description={strings.locations.customerOnly} />
      </Screen>
    );
  }

  return (
    <Screen
      title={strings.locations.title}
      actions={
        canManage ? (
          <BottomActions>
            <ActionButton kind="s" to="/locations/new">
              {strings.locations.add}
            </ActionButton>
          </BottomActions>
        ) : undefined
      }
    >
      {locations.isPending && <Skeleton lines={4} />}
      {locations.isError && (
        <ErrorState error={locations.error} onRetry={() => void locations.refetch()} />
      )}
      {locations.isSuccess && locations.data.length === 0 && (
        <EmptyState
          title={strings.locations.empty}
          description={canManage ? strings.locations.emptyText : undefined}
        />
      )}
      {locations.isSuccess && locations.data.length > 0 && (
        <List>
          {locations.data.map((location) => (
            <ListRow
              key={location.id}
              title={location.name}
              subtitle={placeSubtitle(location, cities.data)}
              to={canManage ? `/locations/${location.id}` : undefined}
              chevron={canManage}
            />
          ))}
        </List>
      )}
    </Screen>
  );
}
