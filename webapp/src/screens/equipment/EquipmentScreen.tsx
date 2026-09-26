import { useState } from 'react';
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { useSession } from '../../session/SessionContext';
import { canManageLocationsAndEquipment, isCustomer } from '../../lib/roles';
import { Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { PageTitle } from '../../ui/blocks/Blocks';
import { WorkspaceHeader } from '../../ui/WorkspaceHeader';
import { ChipGroup } from '../../ui/Chips';
import { StatusHero } from '../../ui/StatusHero';
import { EquipmentIcon } from '../../ui/EquipmentIcon';
import { equipmentDisplayName, equipmentLine, type EquipmentLine } from './equipmentView';
import { ChevronRightIcon, PlusIcon } from '../../ui/icons';
import './equipment.css';

const ALL = 'all';

export function EquipmentLocationRedirect() {
  const { locationId } = useParams<{ locationId: string }>();
  return <Navigate to={locationId ? `/equipment?location=${encodeURIComponent(locationId)}` : '/equipment'} replace />;
}

function EquipmentItem({
  id,
  title,
  code,
  line,
  open,
  onToggle,
  cardPath,
  canCreateRequest,
}: {
  id: string;
  title: string;
  code: string | null;
  line: EquipmentLine | null;
  open: boolean;
  onToggle: () => void;
  cardPath: string;
  canCreateRequest: boolean;
}) {
  const panelId = `eq-item-${id}`;
  return (
    <li className={`eq-item${open ? ' eq-item--open' : ''}`}>
      <button type="button" className="eq-item__row" aria-expanded={open} aria-controls={panelId} onClick={onToggle}>
        <EquipmentIcon code={code} name={title} width={52} />
        <span className="eq-item__main">
          <span className="eq-item__title">{title}</span>
          {line && <span className={`eq-item__sub eq-item__sub--${line.tone}`}>{line.text}</span>}
        </span>
        <ChevronRightIcon className="eq-item__chevron" />
      </button>
      {open && (
        <div id={panelId} className="eq-item__actions">
          {canCreateRequest && (
            <ActionButton compact to={`/requests/new?equipment=${encodeURIComponent(id)}`}>
              {strings.equipment.listNewRequest}
            </ActionButton>
          )}
          <ActionButton compact kind="s" to={cardPath} aria-label={`${strings.equipment.listCard}: ${title}`}>
            {strings.equipment.listCard}
          </ActionButton>
        </div>
      )}
    </li>
  );
}

export function EquipmentScreen() {
  const { activeMembership } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const locations = useLocations();
  const equipment = useOrgEquipment();
  const [openId, setOpenId] = useState<string | null>(null);

  if (!activeMembership) return null;

  if (activeMembership.side !== 'customer') {
    return (
      <Screen title={strings.ui.appTitle}>
        <PageTitle size="m">{strings.equipment.title}</PageTitle>
        <EmptyState title={strings.states.empty} description={strings.requests.equipmentCustomerOnly} />
      </Screen>
    );
  }

  const canManage = canManageLocationsAndEquipment(activeMembership.role);
  const own = new Set(activeMembership.location_ids ?? []);
  const visibleLocations = (locations.data ?? []).filter(
    (l) => canManage || own.size === 0 || own.has(l.id),
  );
  const requested = searchParams.get('location');
  const selected = visibleLocations.some((l) => l.id === requested) ? requested! : ALL;
  const selectLocation = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === ALL || !value) next.delete('location');
    else next.set('location', value);
    setSearchParams(next, { replace: true });
  };
  const addHref = selected === ALL ? '/equipment/new' : `/equipment/new?location=${encodeURIComponent(selected)}`;

  const loading = locations.isPending || equipment.isPending;
  const all = equipment.data ?? [];
  const items = all.filter((item) => selected === ALL || item.location_id === selected);

  const header = (
    <WorkspaceHeader
      title={strings.equipment.title}
      side={
        canManage && (
          <Link className="eq-head__add" to={addHref} aria-label={strings.equipment.addEquipment}>
            <PlusIcon />
          </Link>
        )
      }
    />
  );

  let content;
  let showHeader = true;
  if (loading) {
    content = <Skeleton lines={4} />;
  } else if (locations.isError) {
    content = <ErrorState error={locations.error} onRetry={() => void locations.refetch()} />;
  } else if (equipment.isError) {
    content = <ErrorState error={equipment.error} onRetry={() => void equipment.refetch()} />;
  } else if (visibleLocations.length === 0) {
    showHeader = false;
    content = (
      <StatusHero
        illustration="equipment-add"
        top={72}
        title={strings.equipment.noLocationsTitle}
        actions={
          canManage ? <ActionButton to="/locations/new">{strings.equipment.addLocation}</ActionButton> : undefined
        }
      >
        {canManage ? strings.equipment.noLocationsText : strings.requests.equipmentNeedsLocation}
      </StatusHero>
    );
  } else if (all.length === 0) {
    showHeader = false;
    content = (
      <StatusHero
        illustration="equipment-empty"
        top={72}
        title={canManage ? strings.equipment.emptyTitle : strings.equipment.emptyEmployeeTitle}
        actions={canManage ? <ActionButton to={addHref}>{strings.equipment.addEquipment}</ActionButton> : undefined}
      >
        {canManage ? strings.equipment.emptyText : strings.equipment.emptyEmployeeText}
      </StatusHero>
    );
  } else {
    content = (
      <>
        {visibleLocations.length > 1 && (
          <ChipGroup
            label={strings.equipment.locationFilter}
            variant="outline"
            size="s"
            scroll
            value={selected}
            onChange={selectLocation}
            options={[
              { value: ALL, label: strings.equipment.allLocations },
              ...visibleLocations.map((l) => ({ value: l.id, label: l.name })),
            ]}
          />
        )}
        {items.length === 0 ? (
          <EmptyState title={strings.equipment.emptyLocation} illustration="equipment-empty" />
        ) : (
          <ul className="eq-list" aria-label={strings.equipment.title}>
            {items.map((item) => {
              const title = equipmentDisplayName(item);
              const line = equipmentLine(item);
              return (
                <EquipmentItem
                  key={item.id}
                  id={item.id}
                  title={title}
                  code={item.category_code ?? null}
                  line={line}
                  open={openId === item.id}
                  onToggle={() => setOpenId((current) => (current === item.id ? null : item.id))}
                  cardPath={`/equipment/${item.location_id}/${item.id}`}
                  canCreateRequest={isCustomer(activeMembership.role)}
                />
              );
            })}
          </ul>
        )}
      </>
    );
  }

  return (
    <Screen title={strings.ui.appTitle}>
      {showHeader && header}
      {content}
    </Screen>
  );
}
