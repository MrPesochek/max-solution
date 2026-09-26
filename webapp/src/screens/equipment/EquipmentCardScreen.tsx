import { useEffect, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useEquipmentCategories } from '../../api/hooks/useDirectories';
import { useEquipmentItem, useUpdateEquipment } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import { useRequestsList } from '../../api/hooks/useRequests';
import { useBindingsList } from '../../api/hooks/useBindings';
import { ApiError } from '../../api/errors';
import type { ServiceBinding } from '../../api/types';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { useSession } from '../../session/SessionContext';
import { canManageBindings, canManageLocationsAndEquipment, isCustomer } from '../../lib/roles';
import { Screen, BottomActions, type HeaderMenuItem } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note, PageTitle, TextCard } from '../../ui/blocks/Blocks';
import { TextAreaField, TextField } from '../../ui/FormField';
import { SegmentTabs } from '../../ui/Segmented';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { List, ListRow } from '../../ui/List';
import { equipmentIllustration } from '../../ui/illustrations';
import { requestNo } from '../../ui/format';
import { dayLabel } from '../../lib/datetime';
import { EquipmentBindingsSection } from '../bindings/EquipmentBindingsSection';
import { bindingName, equipmentTitle, serviceState } from '../bindings/bindingView';
import { listItemEquipmentName } from '../requests/components/equipmentName';
import { EquipmentPhotosSection } from './EquipmentPhotosSection';
import { equipmentDisplayName } from './equipmentView';
import './equipment.css';

const FORM_ID = 'equipment-edit-form';
type Tab = 'service' | 'history' | 'specs';
const TABS: Tab[] = ['service', 'history', 'specs'];
const TAB_PREFIX = 'eq-tabs';

function historyDate(iso: string, timeZone?: string | null): string {
  const label = dayLabel(iso, timeZone);
  if (!label) return '';
  if (label.kind === 'today') return strings.equipment.historyToday;
  if (label.kind === 'yesterday') return strings.equipment.historyYesterday;
  return label.date;
}

function longDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
    .format(date)
    .replace(/\s*г\.?$/, '');
}

function HistoryTab({ equipmentId }: { equipmentId: string }) {
  const list = useRequestsList({ equipmentId });
  const requests = list.data ?? [];

  if (list.isPending) return <Skeleton lines={3} />;
  if (list.isError && requests.length === 0) {
    return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  }
  if (requests.length === 0) {
    return <p className="eq-history__empty">{strings.equipment.historyEmpty}</p>;
  }
  const sorted = [...requests].sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <>
      <ul className="eq-history" aria-label={strings.equipment.tabs.history}>
        {sorted.map((request) => {
          const number = requestNo(request.request_number);
          const title = request.symptom_description?.trim() || listItemEquipmentName(request);
          const state = (strings.requests.tag as Record<string, string>)[request.status] ?? '';
          return (
            <li key={request.id}>
              <Link
                className="eq-history__row"
                to={`/requests/${request.id}`}
                aria-label={strings.equipment.historyRow(number, title)}
              >
                <span className="eq-history__date">{historyDate(request.created_at, request.timezone)}</span>
                <span className="eq-history__main">
                  <span className="eq-history__title">{title}</span>
                  <span className="eq-history__sub">{strings.equipment.historySub(state, number)}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.hasNextPage && (
        <List>
          <ListRow
            title={strings.requests.loadMore}
            action="accent"
            loading={list.isFetchingNextPage}
            onClick={() => void list.fetchNextPage()}
          />
        </List>
      )}
    </>
  );
}

export function EquipmentCardScreen() {
  const { equipmentId, locationId } = useParams<{ equipmentId: string; locationId: string }>();
  const routerLocation = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { activeMembership } = useSession();
  const item = useEquipmentItem(equipmentId);
  const categories = useEquipmentCategories();
  const locations = useLocations();
  const bindings = useBindingsList({ equipmentId });
  const updateEquipment = useUpdateEquipment(equipmentId ?? '');

  const [editing, setEditing] = useState(false);
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [serialNumber, setSerialNumber] = useState('');
  const [notes, setNotes] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const photoUploadFailed = Boolean(
    (routerLocation.state as { photoUploadFailed?: boolean } | null)?.photoUploadFailed,
  );

  const tabParam = searchParams.get('tab') as Tab | null;
  const tab: Tab = tabParam && TABS.includes(tabParam) ? tabParam : photoUploadFailed ? 'specs' : 'service';
  const selectTab = (next: Tab) => {
    const params = new URLSearchParams(searchParams);
    if (next === 'service') params.delete('tab');
    else params.set('tab', next);
    setSearchParams(params, { replace: true, state: routerLocation.state });
  };

  useEffect(() => {
    if (item.data) {
      setBrand(item.data.brand ?? '');
      setModel(item.data.model ?? '');
      setSerialNumber(item.data.serial_number ?? '');
      setNotes(item.data.notes ?? '');
    }
  }, [item.data]);

  if (!activeMembership || !equipmentId) return null;

  const headerTitle = strings.equipment.title;
  if (item.isPending || categories.isPending) {
    return (
      <Screen title={headerTitle}>
        <Skeleton lines={5} />
      </Screen>
    );
  }
  if (item.isError || categories.isError) {
    return (
      <Screen title={headerTitle}>
        <ErrorState
          error={item.error ?? categories.error}
          onRetry={() => {
            void item.refetch();
            void categories.refetch();
          }}
        />
      </Screen>
    );
  }

  const data = item.data;
  const canManage = canManageLocationsAndEquipment(activeMembership.role);
  const customer = isCustomer(activeMembership.role);
  const category = categories.data.find((c) => c.id === data.equipment_category_id);
  const title = equipmentDisplayName(data);
  const photoTitle = equipmentTitle(data);
  const locationName = locations.data?.find((l) => l.id === data.location_id)?.name ?? data.location_name ?? null;
  const cardPath = `/equipment/${locationId ?? data.location_id}/${equipmentId}`;

  if (editing) {
    const handleSubmit = async (event: FormEvent) => {
      event.preventDefault();
      setFormError(null);
      try {
        await updateEquipment.mutateAsync({
          brand: brand.trim() || null,
          model: model.trim() || null,
          serial_number: serialNumber.trim() || null,
          notes: notes.trim() || null,
        });
        setEditing(false);
      } catch (error) {
        setFormError(error instanceof ApiError ? error.message : strings.common.unknownError);
      }
    };
    return (
      <Screen
        title={strings.equipment.editTitle}
        back={() => setEditing(false)}
        actions={
          <BottomActions layout="row">
            <ActionButton kind="s" onClick={() => setEditing(false)}>
              {strings.common.cancel}
            </ActionButton>
            <ActionButton type="submit" form={FORM_ID} loading={updateEquipment.isPending}>
              {strings.common.save}
            </ActionButton>
          </BottomActions>
        }
      >
        <PageTitle size="m">{title}</PageTitle>
        <form id={FORM_ID} onSubmit={(event) => void handleSubmit(event)}>
          <TextField id="eq-brand" label={strings.equipment.brand} value={brand} onChange={setBrand} />
          <TextField id="eq-model" label={strings.equipment.model} value={model} onChange={setModel} />
          <TextField
            id="eq-serial"
            label={strings.equipment.serialNumber}
            placeholder={strings.equipment.optionalPlaceholder}
            value={serialNumber}
            onChange={setSerialNumber}
          />
          <TextAreaField
            id="eq-notes"
            label={strings.equipment.notes}
            placeholder={strings.equipment.optionalPlaceholder}
            value={notes}
            onChange={setNotes}
          />
          {formError && (
            <Note tone="error" role="alert">
              {formError}
            </Note>
          )}
        </form>
      </Screen>
    );
  }

  const items = bindings.isSuccess ? (bindings.data as ServiceBinding[]) : [];
  const state = bindings.isSuccess ? serviceState(items) : null;
  const confirmed = items.find((b) => !b.is_contact_only && b.status === 'confirmed');
  const newRequestPath = `/requests/new?equipment=${encodeURIComponent(equipmentId)}`;

  const hasNameplate = data.has_nameplate_photo ?? null;

  const menu: HeaderMenuItem[] = [
    ...(canManage ? [{ label: strings.equipment.editEquipment, onSelect: () => setEditing(true) }] : []),
    ...(canManageBindings(activeMembership.role)
      ? [{ label: strings.equipment.menuServices, onSelect: () => navigate('/bindings') }]
      : []),
  ];

  let actions;
  if (customer && state === 'confirmed' && confirmed) {
    actions = (
      <BottomActions>
        <ActionButton to={newRequestPath}>{strings.equipment.requestToService(bindingName(confirmed))}</ActionButton>
      </BottomActions>
    );
  } else if (customer && state === 'pending') {
    actions = (
      <BottomActions>
        <ActionButton to={newRequestPath}>{strings.equipment.newRequest}</ActionButton>
      </BottomActions>
    );
  } else if (customer && (state === 'none' || state === 'contact')) {
    actions = (
      <BottomActions>
        {canManage && (
          <ActionButton to={`/bindings/new?equipment=${encodeURIComponent(equipmentId)}`}>
            {strings.equipment.connectService}
          </ActionButton>
        )}
        <ActionButton kind={canManage ? 's' : 'p'} to={newRequestPath}>
          {strings.equipment.findProvider}
        </ActionButton>
      </BottomActions>
    );
  }

  const subtitle = [
    locationName,
    data.serial_number ? strings.equipment.serialShort(data.serial_number) : null,
  ]
    .filter(Boolean)
    .join(' · ');

  let panel;
  if (tab === 'service') {
    panel = bindings.isPending ? (
      <Skeleton lines={3} />
    ) : bindings.isError ? (
      <ErrorState error={bindings.error} onRetry={() => void bindings.refetch()} />
    ) : (
      <EquipmentBindingsSection bindings={items} warrantyPath={`${cardPath}/warranty`} />
    );
  } else if (tab === 'history') {
    panel = <HistoryTab equipmentId={equipmentId} />;
  } else {
    panel = (
      <>
        <KeyValueRows
          rows={[
            { label: strings.equipment.specs.category, value: data.category_name ?? strings.common.notSpecified },
            { label: strings.equipment.specs.brand, value: data.brand || strings.common.notSpecified },
            { label: strings.equipment.specs.model, value: data.model || strings.common.notSpecified },
            {
              label: strings.equipment.specs.serial,
              value: data.serial_number ?? strings.equipment.notSpecifiedSerial,
            },
            { label: strings.equipment.specs.location, value: locationName ?? strings.common.notSpecified },
            { label: strings.equipment.specs.created, value: longDate(data.created_at) },
            ...(hasNameplate === null
              ? []
              : [
                  {
                    label: strings.equipment.specs.nameplate,
                    value: hasNameplate ? strings.equipment.specs.nameplateYes : strings.equipment.specs.nameplateNo,
                  },
                ]),
          ]}
        />
        {data.notes && <TextCard>{data.notes}</TextCard>}
        <EquipmentPhotosSection
          equipmentId={equipmentId}
          title={photoTitle}
          canUpload={customer}
          slots={category?.photo_template}
        />
      </>
    );
  }

  return (
    <Screen title={headerTitle} menu={menu} actions={actions}>
      {photoUploadFailed && (
        <Banner tone="y" title={strings.equipment.photosUploadError} role="alert">
          {strings.equipment.photosAfterCreateError}
        </Banner>
      )}
      <SceneBanner
        name={equipmentIllustration(data.category_code, data.category_name ?? title)}
        height={170}
        width={175}
        align="center"
      />
      <PageTitle size="m" subtitle={subtitle || undefined}>
        {title}
      </PageTitle>
      <SegmentTabs
        label={strings.equipment.tabsLabel}
        idPrefix={TAB_PREFIX}
        value={tab}
        onChange={selectTab}
        items={TABS.map((id) => ({ id, label: strings.equipment.tabs[id] }))}
      />
      <div id={`${TAB_PREFIX}-panel`} role="tabpanel" aria-labelledby={`${TAB_PREFIX}-${tab}`}>
        {panel}
      </div>
    </Screen>
  );
}
