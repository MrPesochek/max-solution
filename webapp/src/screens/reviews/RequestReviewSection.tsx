import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import {
  useAppealReview,
  useRequestReviewState,
  useSubmitReview,
} from '../../api/hooks/useReviews';
import { useRequest } from '../../api/hooks/useRequests';
import { getActiveScope } from '../../api/orgStore';
import { queryKeys } from '../../api/queryKeys';
import type { Attachment, MyReview, RequestCustomer, RequestReviewState } from '../../api/types';
import { useSession } from '../../session/SessionContext';
import { canManageRequestApprovals } from '../../lib/roles';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption, TextCard, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { StarRating } from '../../ui/Stars';
import { TextAreaField } from '../../ui/FormField';
import { PhotoGrid, PhotoTile } from '../../ui/PhotoGrid';
import { MessageBubble } from '../../ui/MessageBubble';
import { StatusHero } from '../../ui/StatusHero';
import { SceneBanner } from '../../ui/SceneBanner';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { requestNo } from '../../ui/format';
import '../../components/request/request.css';
import { TextActionSheet } from './TextActionSheet';
import { shortDate } from './reputation';

const RELEVANT_STATUSES = ['completion_reported', 'closed', 'cancelled'];

const NOT_ALLOWED_MESSAGE: Record<string, string> = {
  NO_ASSIGNMENT: strings.reviews.notAllowedNoAssignment,
  REVIEW_NOT_ALLOWED: strings.reviews.notAllowedCancelledBeforeWork,
};

const MODERATION_LABEL: Record<string, string> = {
  pending: strings.reviews.moderationPending,
  published: strings.reviews.moderationPublished,
  rejected: strings.reviews.moderationRejected,
  removed: strings.reviews.moderationRemoved,
};

const STATUS_TONE: Record<string, Tone> = {
  pending: 'a',
  published: 'ok',
  rejected: 'x',
  removed: 'x',
};

function notAllowedText(state: RequestReviewState): string {
  return (
    NOT_ALLOWED_MESSAGE[state.eligibility.reason_code ?? ''] ??
    state.eligibility.reason_message ??
    strings.reviews.notAllowedNoAssignment
  );
}

export function RequestReviewSection({
  request,
  isManager,
  leaveInBottom = false,
}: {
  request: RequestCustomer;
  isManager: boolean;
  leaveInBottom?: boolean;
}) {
  const relevant = isManager && RELEVANT_STATUSES.includes(request.status);
  const state = useRequestReviewState(relevant ? request.id : undefined);

  if (!relevant) return null;
  if (leaveInBottom && state.isSuccess && !state.data.review && state.data.eligibility.can_submit) return null;

  const to = `/requests/${request.id}/review`;
  const review = state.data?.review;

  return (
    <>
      <SectionCaption>{strings.reviews.sectionTitle}</SectionCaption>
      {state.isPending && <Skeleton lines={1} />}
      {state.isError && <ErrorState error={state.error} onRetry={() => void state.refetch()} />}
      {state.isSuccess && !review && !state.data.eligibility.can_submit && (
        <Note>{notAllowedText(state.data)}</Note>
      )}
      {state.isSuccess && !review && state.data.eligibility.can_submit && (
        <List>
          <ListRow
            title={strings.reviews.cardRowLeave}
            subtitle={strings.reviews.photosRowHint}
            to={to}
            chevron
          />
        </List>
      )}
      {review && (
        <List>
          <ListRow
            title={MODERATION_LABEL[review.moderation_status]}
            subtitle={review.text ?? strings.reviews.ratingValue(review.rating)}
            tag={{
              label:
                strings.reviews.statusTag[review.moderation_status] ?? review.moderation_status,
              tone: STATUS_TONE[review.moderation_status] ?? 'w',
            }}
            to={to}
            chevron
          />
        </List>
      )}
    </>
  );
}

function ReviewPhotos({
  attachments,
  selectedIds,
  confirmedSensitiveIds,
  onToggle,
  onToggleSensitiveConfirm,
}: {
  attachments: Attachment[];
  selectedIds: string[];
  confirmedSensitiveIds: Set<string>;
  onToggle: (id: string) => void;
  onToggleSensitiveConfirm: (id: string, confirmed: boolean) => void;
}) {
  const ready = attachments.filter((a) => a.processing_state === 'ready' && !a.message_id);
  const sensitiveSelected = ready.filter(
    (a) => a.visibility_class === 'request_sensitive' && selectedIds.includes(a.id),
  );
  if (ready.length === 0) return null;

  return (
    <section aria-label={strings.reviews.photosLabel}>
      <div className="review-photos__head">
        <span className="review-photos__title">{strings.reviews.photosSection}</span>
        <span className="review-photos__hint">{strings.reviews.photosSectionHint}</span>
      </div>
      <PhotoGrid label={strings.reviews.photosLabel}>
        {ready.map((a, index) => (
          <PhotoTile
            key={a.id}
            attachmentId={a.id}
            alt={strings.attachments.photoAlt(index + 1)}
            actionLabel={strings.attachments.photoAlt(index + 1)}
            selected={selectedIds.includes(a.id)}
            label={a.visibility_class === 'request_sensitive' ? strings.reviews.photoSensitiveTag : undefined}
            onClick={() => onToggle(a.id)}
          />
        ))}
      </PhotoGrid>
      {sensitiveSelected.length > 0 && (
        <List>
          {sensitiveSelected.map((a) => (
            <ListRow
              key={a.id}
              title={strings.reviews.confirmSensitiveLabel}
              subtitle={
                confirmedSensitiveIds.has(a.id)
                  ? strings.reviews.sensitivePhotoWarning
                  : strings.reviews.photosSensitiveBlockedHint
              }
              aria-label={strings.reviews.confirmSensitiveLabel}
              control={{ type: 'checkbox', checked: confirmedSensitiveIds.has(a.id) }}
              onToggle={(next) => onToggleSensitiveConfirm(a.id, next)}
            />
          ))}
        </List>
      )}
    </section>
  );
}

interface ReviewFormProps {
  request: RequestCustomer;
  assignmentId: string | null;
  initial?: { rating: number; text: string | null; showCustomerName: boolean; photoIds: string[] };
  isEdit: boolean;
  needsAdmission: boolean;
  onDone: () => void;
  onCancel?: () => void;
}

function reviewSubtitle(request: RequestCustomer): string {
  const provider = request.assignment?.provider_display_name;
  const master = request.assignment?.field_worker?.display_name;
  const equipment =
    [request.equipment.brand, request.equipment.model].filter(Boolean).join(' ') || strings.common.notSpecified;
  return [provider, master].filter(Boolean).join(' · ') || strings.reviews.screenSubtitle(requestNo(request.request_number), equipment);
}

function ReviewForm({
  request,
  assignmentId,
  initial,
  isEdit,
  needsAdmission,
  onDone,
  onCancel,
}: ReviewFormProps) {
  const [rating, setRating] = useState(initial?.rating ?? 0);
  const [text, setText] = useState(initial?.text ?? '');
  const [showName, setShowName] = useState(initial?.showCustomerName ?? false);
  const [photoIds, setPhotoIds] = useState<string[]>(initial?.photoIds ?? []);
  const [confirmedSensitive, setConfirmedSensitive] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const submit = useSubmitReview(request.id);
  const attachments = request.attachments;

  const togglePhoto = (id: string) => {
    setPhotoIds((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  };

  const toggleSensitiveConfirm = (id: string, confirmed: boolean) => {
    setConfirmedSensitive((prev) => {
      const next = new Set(prev);
      if (confirmed) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const byId = new Map(attachments.map((a) => [a.id, a]));
  const effectivePhotoIds = photoIds.filter((id) => {
    const attachment = byId.get(id);
    if (!attachment || attachment.visibility_class !== 'request_sensitive') return true;
    return confirmedSensitive.has(id);
  });
  const blockedCount = photoIds.length - effectivePhotoIds.length;
  const hasSensitive = effectivePhotoIds.some(
    (id) => byId.get(id)?.visibility_class === 'request_sensitive',
  );

  const handleSubmit = async () => {
    if (rating < 1) return;
    setError(null);
    try {
      await submit.mutateAsync({
        rating,
        assignment_id: assignmentId,
        text: text.trim() || null,
        show_customer_name: showName,
        photo_attachment_ids: effectivePhotoIds,
        confirm_sensitive: hasSensitive,
      });
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'REVIEW_ALREADY_EXISTS') {
        onDone();
        return;
      }
      if (e instanceof ApiError && e.code === 'SENSITIVE_PHOTO_NOT_CONFIRMED') {
        setConfirmedSensitive(new Set());
      }
      setError(e instanceof ApiError ? e.message : strings.reviews.submitError);
    }
  };

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      actions={
        <BottomActions layout={onCancel ? 'row' : 'stack'}>
          {onCancel && (
            <ActionButton kind="s" disabled={submit.isPending} onClick={onCancel}>
              {strings.common.cancel}
            </ActionButton>
          )}
          <ActionButton loading={submit.isPending} disabled={rating < 1} onClick={() => void handleSubmit()}>
            {isEdit ? strings.reviews.submitEdit : strings.reviews.submit}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="review" height={130} />
      <PageTitle subtitle={reviewSubtitle(request)}>{strings.reviews.formTitle}</PageTitle>
      {isEdit && <Note>{strings.reviews.editNotice}</Note>}
      {needsAdmission && <Note>{strings.reviews.needsAdmission}</Note>}

      <StarRating value={rating} onChange={setRating} label={strings.reviews.ratingLabel} captions />

      <TextAreaField
        id="review-text"
        label={strings.reviews.fieldLabel}
        value={text}
        maxLength={4000}
        rows={4}
        onChange={setText}
        placeholder={strings.reviews.formPlaceholder}
        hint={strings.reviews.textLimitHint}
      />

      <ReviewPhotos
        attachments={attachments}
        selectedIds={photoIds}
        confirmedSensitiveIds={confirmedSensitive}
        onToggle={togglePhoto}
        onToggleSensitiveConfirm={toggleSensitiveConfirm}
      />
      {blockedCount > 0 && <Note>{strings.reviews.photosSensitiveBlockedHint}</Note>}

      <List>
        <ListRow
          title={strings.reviews.showCompanyLabel}
          subtitle={strings.reviews.showNameHintShort}
          aria-label={strings.reviews.showCompanyLabel}
          control={{ type: 'switch', checked: showName }}
          onToggle={setShowName}
        />
      </List>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
    </Screen>
  );
}

function ReviewStatus({
  review,
  requestNumber,
  onEdit,
  onChanged,
  onDone,
}: {
  review: MyReview;
  requestNumber: number;
  onEdit: () => void;
  onChanged: () => void;
  onDone: () => void;
}) {
  const [appealOpen, setAppealOpen] = useState(false);
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  const appeal = useAppealReview(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.myComplaints(scope) });
  });
  const status = review.moderation_status;
  const declined = status === 'rejected' || status === 'removed';

  return (
    <Screen
      title={strings.ui.requestTitle(requestNumber)}
      actions={
        <BottomActions layout="row">
          {declined ? (
            <>
              <ActionButton kind="s" onClick={() => setAppealOpen(true)}>
                {strings.reviews.appealShort}
              </ActionButton>
              <ActionButton onClick={onEdit}>{strings.reviews.fixButton}</ActionButton>
            </>
          ) : (
            <>
              <ActionButton kind="s" onClick={onEdit}>
                {strings.reviews.editButton}
              </ActionButton>
              <ActionButton kind="s" onClick={onDone}>
                {strings.reviews.photosDone}
              </ActionButton>
            </>
          )}
        </BottomActions>
      }
    >
      {status === 'pending' ? (
        <StatusHero illustration="thanks" top={24} title={strings.reviews.thanksTitle} role="status">
          {strings.reviews.thanksText}
        </StatusHero>
      ) : declined ? (
        <>
          <SceneBanner name="status-dispute" height={130} />
          <PageTitle subtitle={review.moderation_reason ?? strings.reviews.rejectedFallback}>
            {status === 'rejected' ? strings.reviews.rejectedTitle : MODERATION_LABEL[status]}
          </PageTitle>
        </>
      ) : (
        <>
          <SceneBanner name="review" height={130} />
          <PageTitle>{MODERATION_LABEL[status]}</PageTitle>
        </>
      )}

      <KeyValueRows
        rows={[
          { label: strings.reviews.ratingLabel, value: <StarRating value={review.rating} label={strings.reviews.ratingLabel} /> },
          { label: strings.reviews.statusRow, value: MODERATION_LABEL[status] ?? status },
        ]}
      />
      {review.text && <TextCard>{review.text}</TextCard>}
      {status === 'pending' && review.published && (
        <Note>
          {strings.reviews.publishedVersionLabel}:{' '}
          {strings.reviews.ratingValue(review.published.rating)} —{' '}
          {review.published.text ?? strings.common.notSpecified}
        </Note>
      )}

      {review.reply ? (
        <MessageBubble author={strings.reviews.replyTitle} time={shortDate(review.reply.created_at)}>
          {review.reply.body}
        </MessageBubble>
      ) : (
        <Note>{strings.reviews.replyNone}</Note>
      )}

      <TextActionSheet
        id="appeal-reason"
        open={appealOpen}
        title={strings.reviews.appealTitle}
        label={strings.reviews.appealReasonLabel}
        submitLabel={strings.reviews.appealSubmit}
        errorFallback={strings.reviews.appealError}
        pending={appeal.isPending}
        onSubmit={async (reason) => {
          await appeal.mutateAsync({ reviewId: review.id, input: { reason } });
          onChanged();
        }}
        onClose={() => setAppealOpen(false)}
      />
    </Screen>
  );
}

export function RequestReviewScreen() {
  const { id } = useParams<{ id: string }>();
  const { activeMembership } = useSession();
  const isManager = Boolean(activeMembership && canManageRequestApprovals(activeMembership.role));
  const navigate = useNavigate();
  const request = useRequest(id);
  const data = request.data as RequestCustomer | undefined;
  const relevant = Boolean(isManager && data && RELEVANT_STATUSES.includes(data.status));
  const state = useRequestReviewState(relevant ? id : undefined);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setEditing(false);
  }, [state.data?.review?.moderation_status]);

  const shell = (body: ReactNode) => (
    <Screen title={data ? strings.ui.requestTitle(data.request_number) : strings.reviews.screenHeader}>{body}</Screen>
  );

  if (request.isPending) return shell(<Skeleton lines={6} />);
  if (request.isError)
    return shell(<ErrorState error={request.error} onRetry={() => void request.refetch()} />);
  if (!relevant || !data) {
    return shell(
      <StatusHero illustration="review" top={40} title={strings.reviews.notAllowedNoAssignment} />,
    );
  }
  if (state.isPending) return shell(<Skeleton lines={6} />);
  if (state.isError)
    return shell(<ErrorState error={state.error} onRetry={() => void state.refetch()} />);

  const { review, eligibility } = state.data;

  if (review && !editing) {
    return (
      <ReviewStatus
        review={review}
        requestNumber={data.request_number}
        onEdit={() => setEditing(true)}
        onChanged={() => void state.refetch()}
        onDone={() => navigate(`/requests/${data.id}`)}
      />
    );
  }
  if (review && editing) {
    return (
      <ReviewForm
        request={data}
        assignmentId={review.assignment_id}
        isEdit
        needsAdmission={false}
        initial={{
          rating: review.rating,
          text: review.text,
          showCustomerName: review.show_customer_name,
          photoIds: review.photo_attachment_ids,
        }}
        onDone={() => {
          setEditing(false);
          void state.refetch();
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }
  if (!eligibility.can_submit) {
    return shell(
      <StatusHero illustration="review" top={40} title={strings.reviews.sectionTitle}>
        {notAllowedText(state.data)}
      </StatusHero>,
    );
  }
  return (
    <ReviewForm
      request={data}
      assignmentId={eligibility.assignment_id ?? null}
      isEdit={false}
      needsAdmission={eligibility.mode === 'needs_admission'}
      onDone={() => void state.refetch()}
    />
  );
}
