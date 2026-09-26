import type { ReactNode } from 'react';
import { strings } from '../../strings/ru';
import type { PublicReview } from '../../api/types';
import { MessageBubble } from '../../ui/MessageBubble';
import { PhotoGrid, PhotoTile } from '../../ui/PhotoGrid';
import { PageTitle, Note } from '../../ui/blocks/Blocks';
import { countLabel, hasRating, ratingValue, shortDate, starsText } from './reputation';

export function RatingSummary({
  rating,
  uniqueCustomers,
  reviewsCount,
}: {
  rating: number | null | undefined;
  uniqueCustomers: number;
  reviewsCount: number;
}) {
  const reviews = countLabel(reviewsCount, strings.provider.reviewForms);
  if (hasRating(rating)) {
    return (
      <PageTitle
        subtitle={strings.provider.reviewsSummary(
          countLabel(uniqueCustomers, strings.provider.orgForms),
          reviews,
        )}
      >
        {strings.provider.ratingTag(ratingValue(rating))}
      </PageTitle>
    );
  }
  return (
    <>
      <PageTitle subtitle={reviewsCount > 0 ? reviews : undefined}>
        {strings.provider.reviewsFewTitle}
      </PageTitle>
      <Note>{strings.provider.reviewsFewHint}</Note>
    </>
  );
}

export function ReviewItem({ review, actions }: { review: PublicReview; actions?: ReactNode }) {
  return (
    <>
      <MessageBubble
        author={strings.provider.reviewsAuthorStars(
          review.author_display_name,
          starsText(review.rating),
        )}
        time={shortDate(review.published_at)}
        attachments={
          review.photo_attachment_ids.length > 0 ? (
            <PhotoGrid label={strings.provider.publicProfilePhotoAlt}>
              {review.photo_attachment_ids.map((id, index) => (
                <PhotoTile
                  key={id}
                  attachmentId={id}
                  alt={`${strings.provider.publicProfilePhotoAlt} ${index + 1}`}
                />
              ))}
            </PhotoGrid>
          ) : undefined
        }
      >
        <span className="ui-visually-hidden">{strings.ui.star(review.rating)}. </span>
        {review.text && <span>{review.text}</span>}
      </MessageBubble>
      {review.reply && (
        <MessageBubble
          author={strings.reviews.replyTitle}
          time={shortDate(review.reply.created_at)}
        >
          {review.reply.body}
        </MessageBubble>
      )}
      {actions}
    </>
  );
}
