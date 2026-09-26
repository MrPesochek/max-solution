import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import {
  useCancelDraft,
  useEquipmentServiceBinding,
  useRefreshRequest,
  useRequestHistory,
} from '../../../api/hooks/useRequests';
import { useEquipmentCategories } from '../../../api/hooks/useDirectories';
import type { RequestCustomer } from '../../../api/types';
import { useConfirm } from '../../../components/useConfirm';
import { actionErrorMessage, isStaleError } from '../../../components/actions/actionErrors';
import { Screen, BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Banner, Note, PageTitle } from '../../../ui/blocks/Blocks';
import { List, ListRow, type RowMarker } from '../../../ui/List';
import { SceneBanner } from '../../../ui/SceneBanner';
import { relativeDay } from '../../../ui/format';
import { STEP_DETAILS, STEP_PHOTOS, STEP_REVIEW } from '../wizard/steps';
import { deliverableBinding } from '../wizard/helpers';
import { equipmentName, returnedToDraft } from './cardFormat';

const t = strings.requests.wizard;
const d = t.draftCard;
const DRAFT_EVENTS = new Set(['RequestDrafted', 'RequestDraftUpdated']);

export function DraftCard({
  request,
  onContinue,
}: {
  request: RequestCustomer;
  onContinue: (step: number) => void;
}) {
  const navigate = useNavigate();
  const { confirm, dialog } = useConfirm();
  const refresh = useRefreshRequest(request.id);
  const cancelDraft = useCancelDraft(request.id);
  const history = useRequestHistory(request.id, true);
  const categories = useEquipmentCategories();
  const binding = useEquipmentServiceBinding(
    request.route === 'own_service' ? (request.equipment.id ?? undefined) : undefined,
  );
  const [error, setError] = useState<string | null>(null);

  const savedAt =
    (history.data ?? [])
      .filter((e) => DRAFT_EVENTS.has(e.event_type))
      .map((e) => e.occurred_at)
      .sort()
      .pop() ?? request.created_at;

  const returned = returnedToDraft(history.data);

  const hasDescription = Boolean(request.symptom_description?.trim());
  const photos = request.attachments.filter((a) => !a.message_id);
  const template =
    categories.data?.find((c) => c.id === request.equipment.category_id)?.photo_template ?? [];
  const filledSlots = template.filter((slot) => photos.some((a) => a.slot === slot.code));
  const missingRequired = template.some((slot) => slot.required && !filledSlots.includes(slot));
  const photosMarker: RowMarker = photos.length === 0 ? '-' : missingRequired ? 'w' : 'ok';
  const photosValue =
    photos.length === 0
      ? d.photosNone
      : template.length
        ? t.reviewPhotosCount(filledSlots.length, template.length)
        : String(photos.length);

  const ownService = request.route === 'own_service' ? deliverableBinding(binding.data) : null;
  const recipientKnown = request.route === 'marketplace' || Boolean(ownService);
  const recipient =
    request.route === 'marketplace'
      ? t.routeTitle.marketplace
      : (ownService?.provider.name ??
        (binding.isLoading ? undefined : binding.isError ? strings.common.unknownError : d.recipientNone));

  const nextStep =
    !hasDescription || !request.equipment.id
      ? STEP_DETAILS
      : photos.length === 0 || missingRequired
        ? STEP_PHOTOS
        : STEP_REVIEW;

  const handleDelete = async () => {
    setError(null);
    const ok = await confirm({
      title: d.deleteConfirm,
      description: d.deleteConfirmText,
      confirmLabel: d.deleteConfirmButton,
      destructive: true,
    });
    if (!ok) return;
    try {
      await cancelDraft.mutateAsync({ expected_version: request.version });
      navigate('/requests', { replace: true });
    } catch (e) {
      if (isStaleError(e)) void refresh();
      setError(actionErrorMessage(e, d.deleteError));
    }
  };

  return (
    <Screen
      title={d.title}
      actions={
        <BottomActions layout="stack">
          <ActionButton disabled={cancelDraft.isPending} onClick={() => onContinue(nextStep)}>
            {d.continue}
          </ActionButton>
          <ActionButton
            kind="d"
            loading={cancelDraft.isPending}
            onClick={() => void handleDelete()}
          >
            {d.delete}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="request-temperature" height={140} />
      <PageTitle
        subtitle={[
          request.location.name,
          d.savedOnServer(relativeDay(savedAt, request.location.timezone)),
        ]
          .filter(Boolean)
          .join(' · ')}
      >
        {equipmentName(request)}
      </PageTitle>
      {returned ? (
        <Banner tone="w" title={t.returnedTitle}>
          {t.returnedText(returned.comment, returned.by)}
        </Banner>
      ) : (
        <Banner tone="w" title={d.bannerTitle}>
          {d.bannerText}
        </Banner>
      )}
      <List>
        <ListRow
          marker={hasDescription ? 'ok' : '-'}
          title={d.description}
          value={hasDescription ? undefined : d.descriptionEmpty}
          valueTone="secondary"
        />
        <ListRow
          marker={photosMarker}
          title={d.photos}
          value={photosValue}
          valueTone={photos.length === 0 ? 'secondary' : undefined}
        />
        <ListRow
          marker={recipientKnown ? 'ok' : '-'}
          title={d.recipient}
          value={recipient}
          valueTone={recipientKnown ? undefined : 'secondary'}
        />
      </List>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
      {dialog}
    </Screen>
  );
}
