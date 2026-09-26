import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRefreshRequest, useUpdateDetails } from '../../api/hooks/useRequests';
import { useCities } from '../../api/hooks/useDirectories';
import type { UpdateDetailsInput, Urgency } from '../../api/types';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { ChipGroup } from '../../ui/Chips';
import { SelectField, TextAreaField } from '../../ui/FormField';
import { StatusHero } from '../../ui/StatusHero';
import { equipmentIllustration } from '../../ui/illustrations';
import { requestFallback, useCustomerRequest } from './card/customerRequest';
import { equipmentName } from './card/cardFormat';
import '../../components/request/request.css';

const URGENCIES: Urgency[] = ['critical', 'urgent', 'normal'];

export function UpdateDetailsScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const cities = useCities();
  const updateDetails = useUpdateDetails(id ?? '');
  const refresh = useRefreshRequest(id);
  const runner = useActionRunner({ onStale: refresh, fallbackMessage: strings.requests.updateDetails.error });
  const u = strings.requests.updateDetails;
  const back = id ? `/requests/${id}` : undefined;

  const card = request?.search?.public_card ?? null;

  const [symptom, setSymptom] = useState('');
  const [urgency, setUrgency] = useState<Urgency>('normal');
  const [districtId, setDistrictId] = useState('');
  const [publishedDescription, setPublishedDescription] = useState('');
  const [initialised, setInitialised] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!request || initialised) return;
    setSymptom(request.symptom_description ?? '');
    setUrgency(request.urgency);
    setDistrictId(card?.district_id ?? '');
    setPublishedDescription(card?.published_description ?? '');
    setInitialised(true);
  }, [request, card, initialised]);

  if (!activeMembership || !id) return null;
  const fallback = requestFallback({
    query,
    request,
    title: u.title,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;
  if (cities.isPending) {
    return (
      <Screen title={u.title} back={back}>
        <Skeleton lines={5} />
      </Screen>
    );
  }
  if (cities.isError) {
    return (
      <Screen title={u.title} back={back}>
        <ErrorState error={cities.error} onRetry={() => void cities.refetch()} />
      </Screen>
    );
  }

  if (request.status !== 'action_required') {
    return (
      <Screen title={u.title} back={back}>
        <StatusHero illustration="status-waiting" top={40} title={u.title}>
          {u.notAvailable}
        </StatusHero>
      </Screen>
    );
  }

  const city = cities.data?.find((c) => c.id === request.location.city_id);

  const changes: Omit<UpdateDetailsInput, 'expected_version'> = {};
  if (symptom.trim() !== (request.symptom_description ?? '')) changes.symptom_description = symptom.trim() || null;
  if (urgency !== request.urgency) changes.urgency = urgency;
  if (card) {
    if (districtId !== (card.district_id ?? '')) changes.district_id = districtId || null;
    if (publishedDescription.trim() !== (card.published_description ?? '')) {
      changes.published_description = publishedDescription.trim() || null;
    }
  }
  const hasChanges = Object.keys(changes).length > 0;
  const symptomMissing = !symptom.trim();

  const handleSave = async () => {
    setSubmitted(true);
    if (!hasChanges || symptomMissing) return;
    const saved = await runner.run('updateDetails', () =>
      updateDetails.mutateAsync({ ...changes, expected_version: request.version }),
    );
    if (saved) navigate(`/requests/${id}`, { replace: true });
  };

  const equipment = equipmentName(request);

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      back={back}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('updateDetails')}
            disabled={runner.busy}
            onClick={() => void handleSave()}
          >
            {u.submit}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={u.hint}>{u.title}</PageTitle>
      <List>
        <ListRow
          media={equipmentIllustration(null, request.equipment_category_name ?? request.equipment.category_name)}
          title={equipment}
          subtitle={request.location.name}
        />
      </List>
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
      {submitted && !hasChanges && !symptomMissing && <Note role="status">{u.noChanges}</Note>}
      <TextAreaField
        label={u.symptomLabel}
        value={symptom}
        maxLength={4000}
        rows={4}
        onChange={setSymptom}
        required
        error={submitted && symptomMissing ? u.symptomRequired : undefined}
      />
      <SectionCaption>{u.urgencyLabel}</SectionCaption>
      <ChipGroup<Urgency>
        label={u.urgencyLabel}
        options={URGENCIES.map((option) => ({ value: option, label: u.urgencyOption[option] }))}
        value={urgency}
        onChange={setUrgency}
      />

      {card && (
        <>
          <SectionCaption>{u.publicCardTitle}</SectionCaption>
          {city && (
            <SelectField
              label={u.districtLabel}
              value={districtId}
              onChange={setDistrictId}
              placeholder={strings.requests.publish.districtPlaceholder}
              allowEmpty
              options={city.districts.map((d) => ({ value: d.id, label: d.name }))}
            />
          )}
          <TextAreaField
            label={u.publishedDescriptionLabel}
            value={publishedDescription}
            maxLength={4000}
            rows={3}
            onChange={setPublishedDescription}
          />
        </>
      )}
    </Screen>
  );
}
