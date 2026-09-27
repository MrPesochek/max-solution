import { useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import {
  useAppealReview,
  useMyReviews,
  useProviderReviewsInfinite,
  useReplyToReview,
} from '../../api/hooks/useReviews';
import { useProviderPublicProfile } from '../../api/hooks/useProviders';
import { useMyComplaints, useWithdrawComplaint } from '../../api/hooks/useComplaints';
import type {
  Complaint,
  ComplaintStatus,
  ProviderReview,
  PublicReview,
  ReviewAppealReasonCode,
} from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { useConfirm } from '../../components/useConfirm';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { Screen } from '../../ui/layout/Screen';
import { Note, Tag } from '../../ui/blocks/Blocks';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Stepper } from '../../ui/Stepper';
import { TextAreaField } from '../../ui/FormField';
import { requestNo } from '../../ui/format';
import './components/workspace.css';
import './components/profile.css';
import { List, ListRow } from '../../ui/List';
import { StatusHero } from '../../ui/StatusHero';
import { ComplaintButton, type ComplaintSubject } from '../reviews/ComplaintButton';
import { RatingSummary, ReviewItem } from '../reviews/ReviewFeed';
import { TextActionSheet } from '../reviews/TextActionSheet';
import { shortDate } from '../reviews/reputation';

function reviewSubjects(items: PublicReview[]): ComplaintSubject[] {
  return items.map((review) => ({
    subjectType: 'review',
    targetId: review.id,
    label: strings.complaints.reviewSubject(
      review.author_display_name,
      shortDate(review.published_at),
    ),
  }));
}

function ReviewsBody({
  providerId,
  renderActions,
  emptyTitle = strings.provider.publicProfileReviewsEmpty,
}: {
  providerId: string | undefined;
  renderActions?: (review: PublicReview) => ReactNode;
  emptyTitle?: string;
}) {
  const profile = useProviderPublicProfile(providerId);
  const reviews = useProviderReviewsInfinite(providerId);

  if (reviews.isPending) return <Skeleton lines={4} />;
  if (reviews.isError)
    return <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />;

  const items = reviews.data.pages.flatMap((page) => page.items);

  return (
    <>
      {profile.data && (
        <RatingSummary
          rating={profile.data.rating}
          uniqueCustomers={profile.data.unique_customers}
          reviewsCount={profile.data.reviews_count}
        />
      )}

      {items.length === 0 ? (
        <StatusHero icon="★" top={40} title={emptyTitle} />
      ) : (
        items.map((review) => (
          <ReviewItem key={review.id} review={review} actions={renderActions?.(review)} />
        ))
      )}

      {(reviews.hasNextPage || items.length > 0) && (
        <List>
          {reviews.hasNextPage && (
            <ListRow
              title={strings.provider.publicProfileLoadMore}
              action="accent"
              loading={reviews.isFetchingNextPage}
              onClick={() => void reviews.fetchNextPage()}
            />
          )}
          {items.length > 0 && (
            <ComplaintButton
              variant="row"
              subjectType="review"
              targetId={items[0]!.id}
              subjects={reviewSubjects(items)}
            />
          )}
        </List>
      )}
    </>
  );
}

export function ProviderPublicReviewsScreen() {
  const { providerId } = useParams<{ providerId: string }>();
  return (
    <Screen title={strings.provider.reviewsHeader}>
      <ReviewsBody providerId={providerId} />
    </Screen>
  );
}

type ComplaintStep = 'closed' | 'open';

const REASON_CODES: readonly ReviewAppealReasonCode[] = [
  'not_our_work',
  'abuse_or_personal_data',
  'customer_not_involved',
  'other',
];

function OwnReviewCard({
  review,
  organizationName,
  complaint,
  onChanged,
}: {
  review: ProviderReview;
  organizationName: string;
  complaint: Complaint | undefined;
  onChanged: () => void;
}) {
  const p = strings.provider;
  const c = strings.complaints;
  const [replying, setReplying] = useState(false);
  const [step, setStep] = useState<ComplaintStep>('closed');
  const [reason, setReason] = useState<ReviewAppealReasonCode | null>(null);
  const [details, setDetails] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [withdrawError, setWithdrawError] = useState<string | null>(null);
  const reply = useReplyToReview();
  const appeal = useAppealReview(onChanged);
  const withdraw = useWithdrawComplaint();
  const { confirm, dialog } = useConfirm();

  const brief = review.complaint ?? null;
  const status: ComplaintStatus | null = brief?.status ?? null;
  const filed = brief && status !== 'withdrawn' ? brief : null;
  const createdAt = complaint?.id === brief?.id ? complaint?.created_at : undefined;

  const send = async () => {
    if (reason === null) return;
    setError(null);
    try {
      await appeal.mutateAsync({
        reviewId: review.id,
        input: { reason_code: reason, reason: details.trim() || c.reasonCode[reason] },
      });
      setStep('closed');
      setReason(null);
      setDetails('');
    } catch (e) {
      setError(actionErrorMessage(e, strings.reviews.appealError));
    }
  };

  const runWithdraw = async (complaintId: string) => {
    if (
      !(await confirm({
        title: c.withdrawConfirm,
        confirmLabel: c.withdrawConfirmLabel,
        destructive: true,
      }))
    )
      return;
    setWithdrawError(null);
    try {
      await withdraw.mutateAsync(complaintId);
    } catch (e) {
      setWithdrawError(actionErrorMessage(e, c.withdrawError));
      onChanged();
    }
  };

  return (
    <article
      className="pw-own-review"
      aria-label={p.reviewsActionsLabel(review.author_display_name)}
    >
      <div className="pw-own-review__head">
        <h3 className="pw-own-review__author">{review.author_display_name}</h3>
        <Tag tone="y">{p.ratingTag(String(review.rating))}</Tag>
      </div>
      {review.text && <p className="pw-own-review__text">{review.text}</p>}
      <span className="pw-own-review__meta">
        {strings.workspace.rowSubtitle(
          shortDate(review.published_at),
          p.reviewRequestMeta(requestNo(review.request_number)),
        )}
      </span>

      {review.reply ? (
        <div className="pw-own-review__reply">
          <span className="pw-own-review__reply-title">{p.reviewReplyFrom(organizationName)}</span>
          <span>{review.reply.body}</span>
        </div>
      ) : (
        <button type="button" className="pw-link pw-link--accent" onClick={() => setReplying(true)}>
          {p.reviewsReplyRow}
        </button>
      )}

      {filed ? (
        <div className="pw-own-review__complaint" role="status">
          <span className="pw-own-review__complaint-title">
            {filed.status === 'pending' ? p.reviewComplaintPending : c.status[filed.status]}
          </span>
          {filed.status === 'pending' && (
            <Stepper
              variant="dots"
              aria-label={p.reviewComplaintPending}
              steps={[
                {
                  id: 'sent',
                  label: p.reviewComplaintSteps.sent,
                  time: createdAt ? shortDate(createdAt) : undefined,
                  state: 'done',
                },
                {
                  id: 'check',
                  label: p.reviewComplaintSteps.check,
                  time: p.reviewComplaintSteps.checkTime,
                  state: 'current',
                },
                { id: 'decision', label: p.reviewComplaintSteps.decision, state: 'todo' },
              ]}
            />
          )}
          {complaint?.id === filed.id && complaint.decision_reason && (
            <span className="pw-own-review__meta">
              {c.decisionReasonLabel}: {complaint.decision_reason}
            </span>
          )}
          <p className="pw-section__note">{p.reviewComplaintVisibleNote}</p>
          {filed.status === 'pending' && (
            <button
              type="button"
              className="pw-link"
              disabled={withdraw.isPending}
              onClick={() => void runWithdraw(filed.id)}
            >
              {c.withdraw}
            </button>
          )}
          {withdrawError && (
            <Note tone="error" role="alert">
              {withdrawError}
            </Note>
          )}
        </div>
      ) : step === 'closed' ? (
        <>
          {status === 'withdrawn' && <p className="pw-section__note">{c.withdrawnNote}</p>}
          <button type="button" className="pw-link" onClick={() => setStep('open')}>
            {p.reviewComplaintOpen}
          </button>
        </>
      ) : (
        <div className="pw-own-review__complaint">
          <span className="pw-own-review__complaint-title" aria-hidden="true">
            {p.reviewComplaintReasonTitle}
          </span>
          <List role="radiogroup" aria-label={p.reviewComplaintReasonTitle}>
            {REASON_CODES.map((code) => (
              <ListRow
                key={code}
                title={c.reasonCode[code]}
                control={{ type: 'radio', checked: reason === code }}
                onToggle={() => setReason(code)}
              />
            ))}
          </List>
          <TextAreaField
            id={`complaint-details-${review.id}`}
            label={p.reviewComplaintDetails}
            value={details}
            onChange={setDetails}
            rows={2}
            error={error ?? undefined}
          />
          <div className="pw-own-review__buttons">
            <ActionButton
              kind="s"
              compact
              disabled={appeal.isPending}
              onClick={() => setStep('closed')}
            >
              {strings.common.cancel}
            </ActionButton>
            <ActionButton
              compact
              loading={appeal.isPending}
              disabled={reason === null}
              onClick={() => void send()}
            >
              {p.reviewComplaintSend}
            </ActionButton>
          </div>
        </div>
      )}

      <TextActionSheet
        id={`reply-${review.id}`}
        open={replying}
        title={p.reviewsReplyTitle}
        description={p.reviewsReplyPlaceholder}
        label={p.reviewsReplyLabel}
        submitLabel={p.reviewsReplySubmit}
        errorFallback={p.reviewsReplyError}
        maxLength={2000}
        pending={reply.isPending}
        onSubmit={async (body) => {
          await reply.mutateAsync({ reviewId: review.id, input: { body } });
          onChanged();
        }}
        onClose={() => setReplying(false)}
      />
      {dialog}
    </article>
  );
}

export function ProviderReviewsScreen() {
  const { activeMembership } = useSession();
  const providerId = activeMembership?.organization.id;
  const profile = useProviderPublicProfile(providerId);
  const reviews = useMyReviews();
  const complaints = useMyComplaints();

  if (!activeMembership) return null;

  const complaintById = new Map(
    (complaints.data?.pages ?? []).flatMap((page) => page.items).map((c) => [c.id, c] as const),
  );
  const refresh = () => {
    void reviews.refetch();
    void complaints.refetch();
  };

  let body;
  if (reviews.isPending) body = <Skeleton lines={4} />;
  else if (reviews.isError)
    body = <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />;
  else {
    const items = reviews.data.pages.flatMap((page) => page.items);
    body = (
      <>
        {profile.data && (
          <RatingSummary
            rating={profile.data.rating}
            uniqueCustomers={profile.data.unique_customers}
            reviewsCount={profile.data.reviews_count}
          />
        )}
        {items.length === 0 ? (
          <StatusHero
            illustration="review"
            illustrationWidth={188}
            top={24}
            title={strings.provider.reviewsOwnEmpty}
          />
        ) : (
          items.map((review) => (
            <OwnReviewCard
              key={review.id}
              review={review}
              organizationName={activeMembership.organization.name}
              complaint={review.complaint ? complaintById.get(review.complaint.id) : undefined}
              onChanged={refresh}
            />
          ))
        )}
        {reviews.hasNextPage && (
          <List>
            <ListRow
              title={strings.provider.publicProfileLoadMore}
              action="accent"
              loading={reviews.isFetchingNextPage}
              onClick={() => void reviews.fetchNextPage()}
            />
          </List>
        )}
      </>
    );
  }

  return (
    <Screen title={strings.provider.reviewsHeader}>
      {body}
      <Note>{strings.provider.reviewsCannotHideNotice}</Note>
    </Screen>
  );
}
