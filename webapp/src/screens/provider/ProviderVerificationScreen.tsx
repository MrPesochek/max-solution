import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canManageProviderProfile } from '../../lib/roles';
import { useProviderProfile } from '../../api/hooks/useProviderProfile';
import {
  useSubmitVerificationInformation,
  useUploadVerificationEvidence,
  useVerificationCases,
} from '../../api/hooks/useVerification';
import type {
  Attachment,
  ProviderProfile,
  ProviderProfileStatus,
  VerificationCase,
  VerificationCheckKind,
} from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption } from '../../ui/blocks/Blocks';
import { SceneBanner } from '../../ui/SceneBanner';
import { Stepper, type StepItem } from '../../ui/Stepper';
import { SkeletonBlock, SkeletonRows } from '../../ui/Skeleton';
import { TextAreaField } from '../../ui/FormField';
import type { IllustrationName } from '../../ui/illustrations';
import { shortDateTime } from '../../ui/format';
import { EvidenceTile } from './components/EvidenceTile';

const t = strings.organization.verification;

const SCENE: Record<ProviderProfileStatus, IllustrationName> = {
  draft: 'profile-missing',
  pending_review: 'profile-check',
  needs_information: 'profile-missing',
  active: 'profile-verified',
  suspended: 'profile-missing',
  rejected: 'status-cancel',
};

interface VerificationLocationState {
  pendingDocument?: File;
}

function caseStep(id: string, label: string, item: VerificationCase | undefined): StepItem {
  if (!item) return { id, label, sub: t.notStarted, state: 'todo' };
  const demo = item.is_demo && !/демонстрац/i.test(item.source ?? '') ? ` · ${t.demo}` : '';
  switch (item.decision) {
    case 'approved': {
      const when = item.checked_at ? t.approvedAt(shortDateTime(item.checked_at)) : t.approved;
      return {
        id,
        label,
        sub: [item.source, when].filter(Boolean).join(' · ') + demo,
        state: 'done',
      };
    }
    case 'needs_information':
      return { id, label, sub: (item.decision_reason ?? t.needsInfo) + demo, state: 'attention' };
    case 'rejected':
    case 'revoked':
      return {
        id,
        label,
        sub: [t.rejected, item.decision_reason].filter(Boolean).join(': ') + demo,
        state: 'attention',
      };
    default:
      return { id, label, sub: t.checking + demo, state: 'current' };
  }
}

function latestCase(cases: VerificationCase[], kind: VerificationCheckKind) {
  return cases
    .filter((item) => item.check_kind === kind)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

function categoriesStep(profile: ProviderProfile): StepItem {
  const names = profile.categories.map((category) => category.name).join(', ');
  if (profile.status === 'active') {
    return {
      id: 'categories',
      label: t.categories,
      sub: names || t.categoriesEmpty,
      state: 'done',
    };
  }
  return { id: 'categories', label: t.categories, sub: t.categoriesAfter, state: 'todo' };
}

export function ProviderVerificationScreen() {
  const { activeMembership } = useSession();
  const allowed = Boolean(activeMembership && canManageProviderProfile(activeMembership.role));

  if (!activeMembership) return null;
  if (!allowed) {
    return (
      <Screen title={strings.provider.verificationTitle}>
        <NoAccessState />
      </Screen>
    );
  }
  return <VerificationContent />;
}

function VerificationContent() {
  const location = useLocation();
  const cases = useVerificationCases();
  const profile = useProviderProfile();
  const submitInfo = useSubmitVerificationInformation();
  const uploadEvidence = useUploadVerificationEvidence();

  const [note, setNote] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [evidence, setEvidence] = useState<{ attachment: Attachment; file: File }[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const navigate = useNavigate();
  const pendingDocument = (location.state as VerificationLocationState | null)?.pendingDocument;
  const pendingStarted = useRef(false);

  const openCase =
    cases.data?.find((item) => item.decision === 'needs_information') ??
    cases.data?.find((item) => item.decision === 'pending') ??
    null;

  useEffect(() => {
    if (!pendingDocument || pendingStarted.current || !cases.isSuccess) return;
    pendingStarted.current = true;
    navigate(location.pathname, { replace: true, state: null });
    const open = cases.data.filter(
      (item) => item.decision === 'pending' || item.decision === 'needs_information',
    );
    const target = open.find((item) => item.check_kind === 'representative') ?? open[0];
    void (async () => {
      try {
        const attachment = await uploadEvidence.mutateAsync({
          file: pendingDocument,
          verificationCaseId: target?.id ?? null,
        });
        await submitInfo.mutateAsync({
          note: strings.orgForm.docEvidenceNote,
          attachment_refs: [attachment.id],
        });
        setSent(true);
      } catch {
        setUploadError(strings.orgForm.docUploadFailed);
      }
    })();
  }, [
    pendingDocument,
    cases.isSuccess,
    cases.data,
    navigate,
    location.pathname,
    uploadEvidence,
    submitInfo,
  ]);

  const handleEvidence = async (file: File) => {
    setUploadError(null);
    try {
      const attachment = await uploadEvidence.mutateAsync({
        file,
        verificationCaseId: openCase?.id ?? null,
      });
      setEvidence((current) => [...current, { attachment, file }]);
    } catch (error) {
      setUploadError(actionErrorMessage(error, strings.provider.verificationEvidenceUploadError));
    }
  };

  const handleSubmit = async () => {
    setFormError(null);
    if (!note.trim()) return;
    try {
      await submitInfo.mutateAsync({
        note: note.trim(),
        attachment_refs: evidence.map((item) => item.attachment.id),
      });
      setNote('');
      setEvidence([]);
      setSent(true);
    } catch (error) {
      setFormError(actionErrorMessage(error, strings.common.unknownError));
    }
  };

  const status = profile.data?.status;
  const ready = cases.isSuccess && profile.isSuccess;

  let actions = null;
  if (ready && openCase) {
    actions = (
      <BottomActions>
        <ActionButton
          loading={submitInfo.isPending}
          disabled={!note.trim() || uploadEvidence.isPending}
          onClick={() => void handleSubmit()}
        >
          {strings.provider.verificationSubmit}
        </ActionButton>
        {status === 'pending_review' && (
          <ActionButton kind="s" to="/provider/profile">
            {t.fillProfile}
          </ActionButton>
        )}
      </BottomActions>
    );
  } else if (ready) {
    actions = (
      <BottomActions>
        {status === 'active' ? (
          <ActionButton to="/provider/requests">{t.toRequests}</ActionButton>
        ) : status === 'draft' ? (
          <ActionButton to="/provider/profile/edit">{t.fillProfile}</ActionButton>
        ) : (
          <ActionButton kind="s" to="/provider/profile">
            {t.toProfile}
          </ActionButton>
        )}
      </BottomActions>
    );
  }

  const failed = cases.isError ? cases : profile.isError ? profile : null;

  return (
    <Screen title={strings.provider.verificationTitle} back="/provider/profile" actions={actions}>
      {!ready && !failed && (
        <div className="ui-pad" role="status" aria-label={strings.common.loading}>
          <SkeletonBlock height={150} radius={24} />
          <SkeletonRows rows={3} />
        </div>
      )}
      {failed && <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />}

      {ready && (
        <>
          <SceneBanner name={SCENE[profile.data.status]} height={150} />
          <PageTitle
            subtitle={
              (profile.data.status !== 'active' && profile.data.status_reason) ||
              t.scene[profile.data.status]?.text
            }
          >
            {t.scene[profile.data.status]?.title}
          </PageTitle>
          <Stepper
            aria-label={t.stepsLabel}
            steps={[
              caseStep(
                'requisites',
                profile.data.provider_kind === 'company' ? t.requisitesCompany : t.requisitesSelf,
                latestCase(cases.data, 'requisites'),
              ),
              caseStep(
                'representative',
                t.representative,
                latestCase(cases.data, 'representative'),
              ),
              categoriesStep(profile.data),
            ]}
          />

          {openCase ? (
            <>
              <SectionCaption>{strings.provider.verificationNoteLabel}</SectionCaption>
              <TextAreaField
                aria-label={strings.provider.verificationNoteLabel}
                placeholder={strings.provider.verificationNotePlaceholder}
                value={note}
                onChange={(value) => {
                  setSent(false);
                  setNote(value);
                }}
                rows={4}
              />
              <SectionCaption>{t.evidenceCaption}</SectionCaption>
              <EvidenceTile
                files={evidence.map((item) => item.file)}
                inputLabel={strings.provider.verificationEvidenceUpload}
                onPick={(file) => void handleEvidence(file)}
                onRemove={(index) =>
                  setEvidence((current) => current.filter((_, position) => position !== index))
                }
                busy={
                  uploadEvidence.isPending ? strings.provider.verificationEvidenceUploading : null
                }
              />
              <Note>{strings.provider.verificationEvidenceHint}</Note>
            </>
          ) : (
            <Note>{strings.provider.verificationEvidenceNoOpenCase}</Note>
          )}
          {uploadError && (
            <Note tone="error" role="alert">
              {uploadError}
            </Note>
          )}
          {formError && (
            <Note tone="error" role="alert">
              {formError}
            </Note>
          )}
          {sent && !formError && (
            <Note role="status">{strings.provider.verificationSubmitted}</Note>
          )}
        </>
      )}
    </Screen>
  );
}
