import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import {
  usePreviewPublicCard,
  usePublishSearch,
  useRefreshRequest,
  useSubmitToOwnService,
} from '../../api/hooks/useRequests';
import { useCities } from '../../api/hooks/useDirectories';
import { useAttachmentBlobUrl } from '../../api/hooks/useAttachments';
import { ApiError } from '../../api/errors';
import type { Attachment, PublicCardPreview } from '../../api/types';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { SelectField, TextAreaField } from '../../ui/FormField';
import { StatusHero } from '../../ui/StatusHero';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { urgencyLabel } from '../../lib/status';
import { requestFallback, useCustomerRequest } from './card/customerRequest';
import { equipmentName } from './card/cardFormat';
import { useSlotLabels } from './card/useSlotLabels';

function PhotoThumb({ attachment, alt }: { attachment: Attachment; alt: string }) {
  const { url } = useAttachmentBlobUrl(attachment.id, 'thumb');
  return url ? <img className="request-thumb" src={url} alt={alt} /> : <span aria-hidden="true">▣</span>;
}

export function PublishSearchScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const cities = useCities();
  const preview = usePreviewPublicCard();
  const publish = usePublishSearch(id ?? '');
  const submitToOwnService = useSubmitToOwnService(id ?? '');
  const refresh = useRefreshRequest(id);
  const runner = useActionRunner({ onStale: refresh, fallbackMessage: strings.requests.publish.publishError });
  const slotLabels = useSlotLabels(request?.equipment.category_id);
  const p = strings.requests.publish;
  const back = id ? `/requests/${id}` : undefined;

  const [description, setDescription] = useState('');
  const [districtId, setDistrictId] = useState('');
  const [initialDistrictId, setInitialDistrictId] = useState('');
  const [selectedPhotoIds, setSelectedPhotoIds] = useState<Set<string>>(new Set());
  const [confirmSensitive, setConfirmSensitive] = useState(false);
  const [previewResult, setPreviewResult] = useState<PublicCardPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [initialised, setInitialised] = useState(false);
  const [bindingAcknowledged, setBindingAcknowledged] = useState(false);

  useEffect(() => {
    if (request && !initialised) {
      const previous = request.search?.public_card;
      const district = previous?.district_id ?? request.location.district_id ?? '';
      setDistrictId(district);
      setInitialDistrictId(district);
      setDescription(previous?.published_description ?? '');
      const available = new Set(
        request.attachments.filter((a) => a.processing_state === 'ready' && !a.message_id).map((a) => a.id),
      );
      const previousPhotos = request.search?.published_source_attachment_ids ?? [];
      setSelectedPhotoIds(new Set(previousPhotos.filter((photoId) => available.has(photoId))));
      setInitialised(true);
    }
  }, [request, initialised]);

  useEffect(() => {
    if (!id || !initialised) return;
    const timer = window.setTimeout(() => {
      preview
        .mutateAsync({
          id,
          input: {
            published_description: description || null,
            district_id: districtId || null,
            attachment_ids: Array.from(selectedPhotoIds),
            confirm_sensitive: confirmSensitive,
          },
        })
        .then((result) => {
          setPreviewResult(result);
          setPreviewError(null);
        })
        .catch((e: unknown) => setPreviewError(e instanceof ApiError ? e.message : strings.common.unknownError));
    }, 300);
    return () => window.clearTimeout(timer);
    // `preview` (объект мутации) намеренно не в зависимостях — он новый на каждый рендер,
    // добавление вызвало бы бесконечный цикл пересоздания эффекта.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, initialised, description, districtId, selectedPhotoIds, confirmSensitive]);

  if (!activeMembership || !id) return null;
  const fallback = requestFallback({
    query,
    request,
    title: p.screenTitle,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;
  if (cities.isError) {
    return (
      <Screen title={p.screenTitle} back={back}>
        <ErrorState error={cities.error} onRetry={() => void cities.refetch()} />
      </Screen>
    );
  }
  if (cities.isPending || (!previewResult && !previewError && request.status !== 'searching')) {
    return (
      <Screen title={p.screenTitle} back={back}>
        <Skeleton lines={6} />
      </Screen>
    );
  }

  if (request.status === 'searching') {
    return (
      <Screen
        title={p.screenTitle}
        back={back}
        actions={
          <BottomActions>
            <ActionButton to={`/requests/${id}`}>{strings.common.close}</ActionButton>
          </BottomActions>
        }
      >
        <StatusHero illustration="status-search" top={48} title={p.publishedTitle}>
          {p.publishedDescription}
        </StatusHero>
      </Screen>
    );
  }

  const equipment = equipmentName(request);
  const binding = previewResult?.existing_binding ?? null;
  const bindingName = binding?.provider_name ?? p.ownServiceFallback;

  if (binding && !bindingAcknowledged) {
    return (
      <Screen
        title={p.screenTitle}
        back={back}
        actions={
          <BottomActions>
            <ActionButton disabled={runner.busy} onClick={() => setBindingAcknowledged(true)}>
              {p.searchAnyway}
            </ActionButton>
            <ActionButton
              kind="s"
              loading={runner.isRunning('own')}
              disabled={runner.busy}
              onClick={async () => {
                const done = await runner.run('own', () =>
                  submitToOwnService.mutateAsync({
                    photos_incomplete: request.photos_incomplete,
                    photos_incomplete_reason: request.photos_incomplete
                      ? request.photos_incomplete_reason || strings.common.notSpecified
                      : null,
                    expected_version: request.version,
                  }),
                );
                if (done) navigate(`/requests/${id}`, { replace: true });
              }}
            >
              {p.sendTo(bindingName)}
            </ActionButton>
          </BottomActions>
        }
      >
        <SceneBanner name="service-linked" height={150} />
        <Banner tone="y" title={p.bindingTitle}>
          {p.bindingText(equipment, bindingName)}
        </Banner>
        <Note>{p.bindingNote}</Note>
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
      </Screen>
    );
  }

  const city = cities.data?.find((c) => c.id === request.location.city_id);
  const readyPhotos = request.attachments.filter((a) => a.processing_state === 'ready' && !a.message_id);
  const hasSensitiveSelected = readyPhotos.some(
    (a) => a.visibility_class === 'request_sensitive' && selectedPhotoIds.has(a.id),
  );
  const card = previewResult?.public_card;
  const equipmentLine =
    [card?.equipment_category_name, card?.brand, card?.model].filter(Boolean).join(' ') || equipment;
  const hidden = (previewResult?.withheld_fields ?? []).map(
    (field) => (p.hiddenFieldLabel as Record<string, string>)[field] ?? field,
  );

  const togglePhoto = (photoId: string, on: boolean) => {
    setSelectedPhotoIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(photoId);
      else next.delete(photoId);
      return next;
    });
  };

  const handlePublish = async () => {
    const done = await runner.run('publish', () =>
      publish.mutateAsync({
        published_description: description || null,
        district_id: districtId !== initialDistrictId ? districtId || null : null,
        attachment_ids: Array.from(selectedPhotoIds),
        confirm_sensitive: confirmSensitive,
        expected_version: request.version,
      }),
    );
    if (done) navigate(`/requests/${id}`, { replace: true });
  };

  return (
    <Screen
      title={p.screenTitle}
      back={back}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('publish')}
            disabled={runner.busy || (hasSensitiveSelected && !confirmSensitive)}
            onClick={() => void handlePublish()}
          >
            {p.publishButton}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="status-search" height={130} />
      <PageTitle subtitle={p.subtitle}>{p.title}</PageTitle>
      <SectionCaption>{p.previewCaption}</SectionCaption>
      <KeyValueRows
        aria-label={p.previewCaption}
        rows={[
          { label: p.previewEquipment, value: equipmentLine },
          {
            label: p.previewDistrict,
            value:
              (city && city.districts.find((d) => d.id === (card?.district_id ?? districtId))?.name) ??
              (city ? p.previewCityOnly(city.name) : strings.common.notSpecified),
          },
          { label: p.previewUrgency, value: urgencyLabel(request.urgency) },
          {
            label: p.previewDescription,
            value: card?.published_description?.trim() || description.trim() || strings.common.notSpecified,
          },
          {
            label: p.previewPhotos,
            value: p.previewPhotosCount(card?.published_attachment_ids.length ?? selectedPhotoIds.size),
          },
        ]}
      />
      {city && (
        <SelectField
          label={p.districtLabel}
          value={districtId}
          onChange={setDistrictId}
          placeholder={p.districtPlaceholder}
          allowEmpty
          options={city.districts.map((d) => ({ value: d.id, label: `${city.name}, ${d.name}` }))}
        />
      )}
      <TextAreaField
        id="publish-description"
        label={p.descriptionLabel}
        value={description}
        onChange={setDescription}
        placeholder={p.descriptionPlaceholder}
        rows={3}
      />

      <SectionCaption>{p.photosLabel}</SectionCaption>
      {readyPhotos.length === 0 ? (
        <Note>{p.noPhotos}</Note>
      ) : (
        <List aria-label={p.photosLabel}>
          {readyPhotos.map((a, index) => {
            const label = (a.slot && slotLabels[a.slot]) || p.photoFallback(index + 1);
            const sensitive = a.visibility_class === 'request_sensitive';
            return (
              <ListRow
                key={a.id}
                icon={<PhotoThumb attachment={a} alt={label} />}
                gradient="n"
                title={label}
                subtitle={sensitive ? p.photoSensitiveSubtitle : undefined}
                subtitleTone={sensitive ? 'error' : undefined}
                control={{ type: 'switch', checked: selectedPhotoIds.has(a.id) }}
                onToggle={(on) => togglePhoto(a.id, on)}
              />
            );
          })}
        </List>
      )}
      {hasSensitiveSelected && (
        <>
          <Banner tone="y" title={p.sensitiveBannerTitle}>
            {p.sensitiveBannerText}
          </Banner>
          <List>
            <ListRow
              title={p.confirmSensitiveLabel}
              control={{ type: 'checkbox', checked: confirmSensitive }}
              onToggle={setConfirmSensitive}
            />
          </List>
        </>
      )}
      <Note>{p.photosHint}</Note>

      {previewResult && previewResult.matched_providers === 0 ? (
        <Banner tone="w" title={p.noProvidersTitle}>
          {p.noProvidersDescription}
        </Banner>
      ) : (
        previewResult && <Note>{p.matchedCount(previewResult.matched_providers)}</Note>
      )}
      {hidden.length > 0 && <Note>{p.notPublished(hidden.join(', ').toLowerCase())}</Note>}
      {previewError && <Note tone="error">{previewError}</Note>}
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
    </Screen>
  );
}
