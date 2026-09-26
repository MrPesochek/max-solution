import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useCreateDraft } from '../../api/hooks/useRequests';
import { useSession } from '../../session/SessionContext';
import { canManageLocationsAndEquipment, canPublishExternalSearch } from '../../lib/roles';
import { useLocations } from '../../api/hooks/useLocations';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import type { RequestRoute } from '../../api/types';
import { ErrorState } from '../../components/states/ErrorState';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { haptics, isBridgeAvailable } from '../../max/bridge';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { SkeletonRows } from '../../ui/Skeleton';
import { StatusHero } from '../../ui/StatusHero';
import { StepProgress } from '../../ui/Stepper';
import { equipmentIllustration } from '../../ui/illustrations';
import { equipmentFullName } from './components/equipmentName';
import { bindingSummary, equipmentService, serviceName } from './components/equipmentService';
import { STEP_EQUIPMENT, STEP_TOTAL } from './wizard/steps';

const t = strings.requests.routePicker;

export function NewRequestScreen() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { activeMembership } = useSession();
  const createDraft = useCreateDraft();
  const locations = useLocations();
  const equipment = useOrgEquipment();
  const [selectedId, setSelectedId] = useState<string | null>(params.get('equipment'));
  const [route, setRoute] = useState<RequestRoute | null>(
    params.get('route') === 'marketplace' ? 'marketplace' : null,
  );
  const [error, setError] = useState<string | null>(null);

  if (!activeMembership) return null;
  const isEmployee = !canPublishExternalSearch(activeMembership.role);
  const canAddEquipment = canManageLocationsAndEquipment(activeMembership.role);
  const title = strings.ui.stepOf(STEP_EQUIPMENT + 1, STEP_TOTAL);
  const header = {
    title,
    back: isBridgeAvailable() ? undefined : (false as const),
    onClose: () => navigate('/'),
  };

  if (locations.isPending || equipment.isPending) {
    return (
      <Screen {...header}>
        <StepProgress current={STEP_EQUIPMENT + 1} total={STEP_TOTAL} />
        <SkeletonRows rows={4} />
      </Screen>
    );
  }
  if (locations.isError || equipment.isError) {
    const failed = locations.isError ? locations : equipment;
    return (
      <Screen {...header}>
        <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />
      </Screen>
    );
  }

  const addEquipmentPath =
    locations.data.length === 1 ? `/equipment/${locations.data[0]!.id}/new` : '/equipment';
  const locationById = new Map(locations.data.map((l) => [l.id, l]));
  const order = new Map(locations.data.map((l, index) => [l.id, index]));
  const items = equipment.data
    .filter((e) => locationById.has(e.location_id))
    .sort((a, b) => (order.get(a.location_id) ?? 0) - (order.get(b.location_id) ?? 0));

  if (locations.data.length === 0 || items.length === 0) {
    return (
      <Screen {...header}>
        {locations.data.length === 0 ? (
          <StatusHero illustration="equipment-empty" top={40} title={t.noLocationsTitle}>
            {t.noLocations}
          </StatusHero>
        ) : (
          <StatusHero
            illustration="equipment-empty"
            top={40}
            title={t.noEquipmentTitle}
            actions={
              canAddEquipment ? (
                <ActionButton to={addEquipmentPath}>{t.addEquipment}</ActionButton>
              ) : undefined
            }
          >
            {t.noEquipmentText}
          </StatusHero>
        )}
      </Screen>
    );
  }

  const selected = items.find((e) => e.id === selectedId) ?? (items.length === 1 ? items[0]! : null);
  const service = selected ? equipmentService(selected) : undefined;
  const own = service?.deliverable ?? null;
  const chosen: RequestRoute | null = selected
    ? (route ?? (own ? 'own_service' : 'marketplace'))
    : route;

  const serviceShort = (item: (typeof items)[number]): string => bindingSummary(item).text;

  const ownCard = (() => {
    if (!selected) return { title: strings.home.myService, subtitle: t.pickEquipmentFirst };
    if (own) {
      return {
        title: serviceName(own),
        subtitle: t.ownServiceSubtitle[own.basis] ?? t.ownServiceSubtitle.preferred,
      };
    }
    if (service?.contact) {
      return {
        title: t.contactTitle(serviceName(service.contact)),
        subtitle: t.contactHint(service.contact.contact_phone),
      };
    }
    return { title: t.ownServiceNoneTitle, subtitle: t.ownServiceNoneHint };
  })();

  const startWizard = async () => {
    if (!selected || !chosen) return;
    setError(null);
    try {
      const draft = await createDraft.mutateAsync({
        equipment_id: selected.id,
        route: chosen,
        urgency: 'normal',
      });
      haptics.selection();
      navigate(`/requests/${draft.id}`, { replace: true, state: { wizard: true } });
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  return (
    <Screen
      {...header}
      actions={
        <BottomActions>
          <ActionButton
            loading={createDraft.isPending}
            disabled={!selected || !chosen || (chosen === 'own_service' && !own)}
            onClick={() => void startWizard()}
          >
            {t.next}
          </ActionButton>
        </BottomActions>
      }
    >
      <StepProgress current={STEP_EQUIPMENT + 1} total={STEP_TOTAL} />
      <PageTitle>{t.pickTitle}</PageTitle>

      <List role="radiogroup" aria-label={t.equipmentLabel}>
        {items.map((item) => {
          return (
            <ListRow
              key={item.id}
              media={equipmentIllustration(item.category_code, item.category_name)}
              title={equipmentFullName({ category: item.category_name, brand: item.brand, model: item.model })}
              subtitle={t.equipmentSubtitle(locationById.get(item.location_id)?.name, serviceShort(item))}
              control={{ type: 'radio', checked: selected?.id === item.id }}
              onToggle={() => {
                haptics.selection();
                setSelectedId(item.id);
                setRoute(null);
                setError(null);
              }}
            />
          );
        })}
      </List>
      {canAddEquipment && (
        <List>
          <ListRow title={t.equipmentMissing} action="accent" to={addEquipmentPath} />
        </List>
      )}

      <SectionCaption id="new-request-route">{t.routeTitle}</SectionCaption>
      <ChoiceGroup label={t.routeTitle}>
        <ChoiceCard
          title={ownCard.title}
          subtitle={ownCard.subtitle}
          selected={chosen === 'own_service'}
          disabled={!own}
          onSelect={() => setRoute('own_service')}
        />
        <ChoiceCard
          title={t.marketplaceTitle}
          subtitle={isEmployee ? t.marketplaceDescriptionEmployee : t.marketplaceDescription}
          selected={chosen === 'marketplace'}
          onSelect={() => setRoute('marketplace')}
        />
      </ChoiceGroup>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Screen>
  );
}
