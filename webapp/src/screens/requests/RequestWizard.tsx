import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { useOrgEquipment } from '../../api/hooks/useEquipment';
import { useLocations } from '../../api/hooks/useLocations';
import { useEquipmentCategories } from '../../api/hooks/useDirectories';
import {
  useCancelDraft,
  useEquipmentServiceBinding,
  useRequestApproval,
  useRequestHistory,
  useSubmitToOwnService,
  useUpdateDraft,
} from '../../api/hooks/useRequests';
import { useRequestAttachments } from '../../api/hooks/useAttachments';
import type { Attachment, PhotoTemplateSlot, RequestCustomer, Urgency } from '../../api/types';
import { ErrorState } from '../../components/states/ErrorState';
import { useOnlineStatus } from '../../lib/useOnlineStatus';
import { formatTime } from '../../lib/datetime';
import { useSession } from '../../session/SessionContext';
import { FlowExitGuard } from '../../components/layout/FlowNavigation';
import { useConfirm } from '../../components/useConfirm';
import { actionErrorMessage, isOfflineError } from '../../components/actions/actionErrors';
import { closeApp, haptics, isBridgeAvailable } from '../../max/bridge';
import { Screen, BottomActions, type HeaderMenuItem } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { StatusHero } from '../../ui/StatusHero';
import { StepProgress } from '../../ui/Stepper';
import { EquipmentIcon } from '../../ui/EquipmentIcon';
import { STEP_DETAILS, STEP_REVIEW, STEP_TOTAL } from './wizard/steps';
import { DetailsStep } from './wizard/DetailsStep';
import { PhotosStep } from './wizard/PhotosStep';
import { NoPhotoStep } from './wizard/NoPhotoStep';
import { ReviewStep } from './wizard/ReviewStep';
import { EquipmentSheet } from './wizard/EquipmentSheet';
import {
  SCREEN_SLOT,
  deliverableBinding,
  equipmentTitle,
  joinSymptoms,
  noPhotoReason,
  parseNoPhotoReason,
  splitSymptoms,
  symptomPresets,
} from './wizard/helpers';
import { returnedToDraft } from './card/cardFormat';
import { equipmentFullName } from './components/equipmentName';
import './wizard/wizard.css';

const t = strings.requests.wizard;
const DRAFT_EVENTS = new Set(['RequestDrafted', 'RequestDraftUpdated']);

type View = 'step' | 'noPhoto' | 'offline';

export function RequestWizard({
  request,
  initialStep = STEP_DETAILS,
}: {
  request: RequestCustomer;
  initialStep?: number;
}) {
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const online = useOnlineStatus();

  const [step, setStep] = useState(() => Math.min(Math.max(initialStep, STEP_DETAILS), STEP_REVIEW));
  const [view, setView] = useState<View>('step');
  const { confirm, dialog } = useConfirm();
  const [locationId, setLocationId] = useState(request.location.id ?? '');
  const [equipmentId, setEquipmentId] = useState(request.equipment.id ?? '');
  const [equipmentSheetOpen, setEquipmentSheetOpen] = useState(false);
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [details, setDetails] = useState(request.symptom_description ?? '');
  const [symptomsParsed, setSymptomsParsed] = useState(false);
  const [errorCode, setErrorCode] = useState(request.error_code ?? '');
  const [urgency, setUrgency] = useState<Urgency>(request.urgency);
  const [noScreen, setNoScreen] = useState(false);
  const [noPhotoChoice, setNoPhotoChoice] = useState<string | null>(null);
  const [noPhotoOther, setNoPhotoOther] = useState('');
  const [confirmIncomplete, setConfirmIncomplete] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [showRequired, setShowRequired] = useState(false);
  const versionRef = useRef(request.version);
  const currentVersion = () => Math.max(versionRef.current, request.version);

  const locations = useLocations();
  const allEquipment = useOrgEquipment();
  const categories = useEquipmentCategories();
  const attachments = useRequestAttachments(request.id);
  const history = useRequestHistory(request.id, true);
  const binding = useEquipmentServiceBinding(
    request.route === 'own_service' ? equipmentId || undefined : undefined,
  );

  const updateDraft = useUpdateDraft(request.id);
  const submitOwnService = useSubmitToOwnService(request.id);
  const requestApproval = useRequestApproval(request.id);
  const cancelDraft = useCancelDraft(request.id);

  const attachmentsBySlot = useMemo(() => {
    const map = new Map<string, Attachment[]>();
    for (const a of attachments.data ?? []) {
      if (!a.slot) continue;
      const list = map.get(a.slot) ?? [];
      list.push(a);
      map.set(a.slot, list);
    }
    return map;
  }, [attachments.data]);

  const categoryCode = categories.data?.find((c) => c.id === request.equipment.category_id)?.code;
  const presets = symptomPresets(categoryCode);
  useEffect(() => {
    if (symptomsParsed || !categories.isSuccess) return;
    setSymptomsParsed(true);
    if (details !== (request.symptom_description ?? '')) return;
    const parsed = splitSymptoms(request.symptom_description, presets);
    setSymptoms(parsed.chips);
    setDetails(parsed.text);
    if (request.photos_incomplete_reason) {
      const slots = categories.data?.find((c) => c.id === request.equipment.category_id)?.photo_template ?? [];
      const saved = parseNoPhotoReason(
        request.photos_incomplete_reason,
        slots.map((slot) => slot.label),
      );
      setNoScreen(saved.noScreen);
      setNoPhotoChoice(saved.choice);
      setNoPhotoOther(saved.otherText);
    }
  }, [categories.isSuccess]);
  const symptomDescription = joinSymptoms(symptoms, details, presets);

  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const heading = bodyRef.current?.querySelector<HTMLElement>('h2');
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView?.({ block: 'nearest' });
  }, [step, view]);

  if (!activeMembership) return null;
  const isEmployee = activeMembership.role === 'customer_employee';

  const category = categories.data?.find((c) => c.id === request.equipment.category_id);
  const photoTemplate = category?.photo_template ?? [];
  const selectedEquipment = allEquipment.data?.find((e) => e.id === equipmentId);
  const location = locations.data?.find((l) => l.id === locationId);
  const locationName = location?.name ?? request.location.name ?? undefined;
  const ownService = request.route === 'own_service' ? deliverableBinding(binding.data) : null;
  const ownServiceMissing = request.route === 'own_service' && binding.isSuccess && !ownService;
  const title = equipmentTitle(selectedEquipment ?? request.equipment);
  const categoryName = category?.name ?? request.equipment.category_name;
  const shortTitle = selectedEquipment
    ? equipmentFullName({ category: categoryName, brand: selectedEquipment.brand, model: selectedEquipment.model })
    : equipmentFullName({
        category: categoryName,
        brand: request.equipment.brand,
        model: request.equipment.model,
      });

  const lastDraftEvent = (history.data ?? [])
    .filter((e) => DRAFT_EVENTS.has(e.event_type))
    .map((e) => e.occurred_at)
    .sort()
    .pop();
  const serverSavedAt = savedAt ?? lastDraftEvent ?? request.created_at;
  const returned = returnedToDraft(history.data);

  const photoReason = noPhotoReason(noPhotoChoice, noPhotoOther);
  const reasonFor = (slot: PhotoTemplateSlot): string | null => {
    if (slot.code === SCREEN_SLOT && noScreen) return t.noScreen;
    return photoReason;
  };
  const requiredSlotsWithoutPhoto = photoTemplate.filter(
    (slot) => slot.required && !attachmentsBySlot.get(slot.code)?.length,
  );
  const unresolvedRequiredSlots = requiredSlotsWithoutPhoto.filter((slot) => !reasonFor(slot));
  const isUrgent = urgency === 'critical' || urgency === 'urgent';
  const filledSlots = photoTemplate.filter((slot) => attachmentsBySlot.get(slot.code)?.length).length;
  const photosValue = photoTemplate.length
    ? t.reviewPhotosCount(filledSlots, photoTemplate.length)
    : String(attachments.data?.length ?? 0);

  const combinedIncompleteReason = () => {
    const parts = requiredSlotsWithoutPhoto
      .map((slot) => ({ slot, reason: reasonFor(slot) }))
      .filter(({ reason }) => reason)
      .map(({ slot, reason }) => `${slot.label}: ${reason}`);
    return parts.join('; ') || null;
  };

  const saveDetails = async (): Promise<boolean> => {
    setStepError(null);
    try {
      let version = currentVersion();
      let saved = false;
      if (equipmentId !== request.equipment.id) {
        version = (await updateDraft.mutateAsync({ equipment_id: equipmentId, expected_version: version })).version;
        versionRef.current = version;
        saved = true;
      }
      const photosKnown = categories.isSuccess && attachments.isSuccess;
      const incompleteReason = combinedIncompleteReason();
      const photosIncomplete = requiredSlotsWithoutPhoto.length > 0 && Boolean(incompleteReason);
      const photosChanged =
        photosKnown &&
        (photosIncomplete !== request.photos_incomplete ||
          incompleteReason !== (request.photos_incomplete_reason ?? null));
      if (
        symptomDescription !== (request.symptom_description ?? '') ||
        errorCode !== (request.error_code ?? '') ||
        urgency !== request.urgency ||
        photosChanged
      ) {
        version = (
          await updateDraft.mutateAsync({
            symptom_description: symptomDescription || null,
            error_code: errorCode || null,
            urgency,
            ...(photosChanged
              ? { photos_incomplete: photosIncomplete, photos_incomplete_reason: incompleteReason }
              : {}),
            expected_version: version,
          })
        ).version;
        versionRef.current = version;
        saved = true;
      }
      if (saved) setSavedAt(new Date().toISOString());
      return true;
    } catch (error) {
      setStepError(actionErrorMessage(error, t.draftSaveError));
      return false;
    }
  };

  const goToStep = (next: number) => {
    setStepError(null);
    setView('step');
    setStep(next);
  };

  const handleNext = async () => {
    if (!online) {
      setStepError(t.offlineNotice);
      return;
    }
    if (step === STEP_DETAILS) {
      if (!equipmentId) {
        setStepError(t.noEquipment);
        return;
      }
      if (!symptomDescription.trim()) {
        setShowRequired(true);
        document.getElementById('wizard-symptoms')?.focus();
        return;
      }
      const ok = await saveDetails();
      if (!ok) return;
    }
    haptics.selection();
    goToStep(Math.min(step + 1, STEP_REVIEW));
  };

  const handleNoPhotoNext = async () => {
    if (!photoReason) {
      setStepError(t.noPhotoReasonRequired);
      return;
    }
    setStepError(null);
    setView('step');
    await handleNext();
  };

  const submitting = submitOwnService.isPending || requestApproval.isPending;

  const handleSubmit = async () => {
    setStepError(null);
    if (!online) {
      setView('offline');
      return;
    }
    const photosIncomplete = requiredSlotsWithoutPhoto.length > 0;
    if (unresolvedRequiredSlots.length > 0 && !isUrgent) {
      setStepError(t.photosIncompleteNotice);
      return;
    }
    if (unresolvedRequiredSlots.length > 0 && !confirmIncomplete) return;
    if (step === STEP_DETAILS && !(await saveDetails())) return;
    try {
      if (request.route === 'own_service') {
        await submitOwnService.mutateAsync({
          photos_incomplete: photosIncomplete,
          photos_incomplete_reason: photosIncomplete
            ? (combinedIncompleteReason() ?? strings.common.notSpecified)
            : null,
          expected_version: currentVersion(),
        });
      } else if (isEmployee) {
        await requestApproval.mutateAsync({ expected_version: currentVersion() });
      } else {
        navigate(`/requests/${request.id}/publish`);
        return;
      }
      haptics.notification('success');
      navigate(`/requests/${request.id}`, { replace: true, state: { sent: true } });
    } catch (error) {
      haptics.notification('error');
      if (isOfflineError(error)) {
        setView('offline');
      } else if (error instanceof ApiError && error.code === 'SERVICE_BINDING_REQUIRED') {
        setStepError(t.serviceBindingRequiredError);
      } else {
        setStepError(actionErrorMessage(error, t.submitError));
      }
    }
  };

  const handleCancelDraft = async () => {
    if (!(await confirm({ title: t.cancelDraftConfirm }))) return;
    try {
      await cancelDraft.mutateAsync({ expected_version: currentVersion() });
      navigate('/requests', { replace: true });
    } catch (error) {
      setStepError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  const back =
    view !== 'step'
      ? () => {
          setStepError(null);
          setView('step');
        }
      : step > STEP_DETAILS
        ? () => goToStep(step - 1)
        : undefined;

  const menu: HeaderMenuItem[] = [
    { label: t.cancelDraft, danger: true, onSelect: () => void handleCancelDraft() },
  ];

  const submitLabel =
    request.route === 'own_service'
      ? t.submitOwnService
      : isEmployee
        ? t.submitApproval
        : t.submitPublish;

  let actions;
  if (view === 'offline') {
    actions = (
      <BottomActions>
        <ActionButton loading={submitting} onClick={() => void handleSubmit()}>
          {t.offlineRetry}
        </ActionButton>
        {isBridgeAvailable() && (
          <ActionButton kind="s" onClick={() => closeApp()}>
            {t.offlineBot}
          </ActionButton>
        )}
      </BottomActions>
    );
  } else if (view === 'noPhoto') {
    actions = (
      <BottomActions>
        <ActionButton
          loading={updateDraft.isPending}
          disabled={uploading}
          onClick={() => void handleNoPhotoNext()}
        >
          {t.noPhotoNext}
        </ActionButton>
      </BottomActions>
    );
  } else if (step < STEP_REVIEW) {
    actions = (
      <BottomActions
        note={updateDraft.isPending ? t.draftSaving : t.draftSavedAt(formatTime(serverSavedAt))}
      >
        <ActionButton
          loading={updateDraft.isPending}
          disabled={uploading}
          onClick={() => void handleNext()}
        >
          {t.next}
        </ActionButton>
      </BottomActions>
    );
  } else {
    actions = (
      <BottomActions>
        <ActionButton
          loading={submitting}
          disabled={
            ownServiceMissing ||
            (request.route === 'own_service' && !ownService) ||
            (unresolvedRequiredSlots.length > 0 && (!isUrgent || !confirmIncomplete))
          }
          onClick={() => void handleSubmit()}
        >
          {submitLabel}
        </ActionButton>
      </BottomActions>
    );
  }

  const errorNote = stepError && (
    <Note tone="error" role="alert">
      {stepError}
    </Note>
  );

  const equipmentLine = (
    <button
      type="button"
      className="wizard-equipment"
      aria-label={`${t.changeEquipment}: ${shortTitle}`}
      onClick={() => setEquipmentSheetOpen(true)}
    >
      <EquipmentIcon code={categoryCode} name={categoryName ?? title} width={28} />
      <span className="wizard-equipment__text">{shortTitle}</span>
    </button>
  );

  return (
    <Screen
      title={view === 'offline' ? t.routeTitle[request.route] : t.stepOf(step + 1, STEP_TOTAL)}
      back={back}
      menu={menu}
      actions={actions}
    >
      {view !== 'offline' && <StepProgress current={step + 1} total={STEP_TOTAL} />}
      <FlowExitGuard
        save={async () => {
          if (submitting || updateDraft.isPending || uploading) return false;
          return step === STEP_DETAILS ? saveDetails() : true;
        }}
      />
      <div ref={bodyRef} style={{ display: 'contents' }}>
        {view === 'offline' && (
          <StatusHero icon="!" top={120} role="alert" title={t.offlineTitle}>
            {t.offlineText(formatTime(serverSavedAt))}
          </StatusHero>
        )}

        {view === 'noPhoto' && (
          <>
            <NoPhotoStep
              choice={noPhotoChoice}
              otherText={noPhotoOther}
              onChoiceChange={setNoPhotoChoice}
              onOtherTextChange={setNoPhotoOther}
            />
            {errorNote}
          </>
        )}

        {view === 'step' && step === STEP_DETAILS && (
          <>
            <DetailsStep
              equipmentLine={equipmentLine}
              notice={
                <>
                  {returned && (
                    <Banner title={t.returnedTitle} tone="w">
                      {t.returnedText(returned.comment, returned.by)}
                    </Banner>
                  )}
                  {ownServiceMissing && (
                    <Banner title={t.ownServiceMissing} tone="x">
                      {t.ownServiceMissingHint}
                    </Banner>
                  )}
                </>
              }
              descriptionError={showRequired && !symptomDescription.trim() ? t.descriptionRequired : undefined}
              presets={presets}
              symptoms={symptoms}
              onSymptomsChange={setSymptoms}
              details={details}
              onDetailsChange={setDetails}
              errorCode={errorCode}
              onErrorCodeChange={setErrorCode}
              urgency={urgency}
              onUrgencyChange={setUrgency}
              photos={
                <>
                  <PhotosStep
                    requestId={request.id}
                    template={photoTemplate}
                    templateLoading={categories.isPending}
                    attachments={attachments.data ?? []}
                    attachmentsBySlot={attachmentsBySlot}
                    noScreen={noScreen}
                    onNoScreenChange={setNoScreen}
                    onCannotPhoto={() => {
                      setStepError(null);
                      setView('noPhoto');
                    }}
                    onError={setStepError}
                    onBusyChange={setUploading}
                  />
                  {attachments.isError && (
                    <ErrorState error={attachments.error} onRetry={() => void attachments.refetch()} />
                  )}
                  {categories.isError && (
                    <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
                  )}
                </>
              }
            />
            {errorNote}
          </>
        )}

        {view === 'step' && step === STEP_REVIEW && (
          <>
            <ReviewStep
              route={request.route}
              isEmployee={isEmployee}
              approverName={request.approver_name}
              binding={ownService}
              equipmentTitle={shortTitle}
              locationName={locationName}
              urgency={urgency}
              errorCode={errorCode}
              symptomDescription={symptomDescription}
              photosValue={photosValue}
              onEdit={() => goToStep(STEP_DETAILS)}
              noPhotoReason={requiredSlotsWithoutPhoto.length > 0 ? photoReason : null}
              hasUnresolvedSlots={unresolvedRequiredSlots.length > 0}
              isUrgent={isUrgent}
              confirmIncomplete={confirmIncomplete}
              onConfirmIncompleteChange={setConfirmIncomplete}
            />
            {ownServiceMissing && (
              <Banner title={t.ownServiceMissing} tone="x">
                {t.ownServiceMissingHint}
              </Banner>
            )}
            {binding.isError && <ErrorState error={binding.error} onRetry={() => void binding.refetch()} />}
            {errorNote}
          </>
        )}
      </div>

      <EquipmentSheet
        open={equipmentSheetOpen}
        onClose={() => setEquipmentSheetOpen(false)}
        locationId={locationId}
        equipmentId={equipmentId}
        onLocationChange={(value) => {
          setLocationId(value);
          setEquipmentId('');
        }}
        onEquipmentChange={setEquipmentId}
      />
      {dialog}
    </Screen>
  );
}
