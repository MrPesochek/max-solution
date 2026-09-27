import type { UseQueryResult } from '@tanstack/react-query';
import { strings } from '../../../strings/ru';
import type { MarketplaceListItem, ProviderProfile } from '../../../api/types';
import { Skeleton } from '../../../components/states/Skeleton';
import { ErrorState } from '../../../components/states/ErrorState';
import { Note, SectionCaption } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { StatusHero } from '../../../ui/StatusHero';
import { equipmentIllustration } from '../../../ui/illustrations';
import { pluralRu } from '../../requests/card/cardFormat';
import { cardAreaName, cardTitle } from '../components/cardText';
import { JobCard, JobList } from '../components/JobCard';
import { urgencyTag } from '../components/jobTags';

function cardMeta(card: MarketplaceListItem): string {
  const w = strings.workspace;
  if (card.has_open_question) return w.rowSubtitle(w.clarificationTag, w.waitingAnswerNote);
  if (card.has_clarification) return w.rowSubtitle(w.clarificationTag, w.answeredNote);
  if (card.offers_count === 0) return w.noOffersTag;
  return pluralRu(card.offers_count, strings.requests.card.offerForms);
}

export function AvailableList({
  query,
  profile,
}: {
  query: UseQueryResult<MarketplaceListItem[]>;
  profile: UseQueryResult<ProviderProfile>;
}) {
  const w = strings.workspace;
  if (query.isPending || profile.isPending) return <Skeleton lines={4} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const items = query.data;
  if (items.length === 0) {
    const profileNotReady = profile.isSuccess && profile.data.status !== 'active';
    const notAccepting =
      profile.isSuccess && profile.data.status === 'active' && !profile.data.accepting_new_requests;
    return (
      <>
        <StatusHero
          illustration="performer-empty"
          illustrationWidth={210}
          top={8}
          title={w.availableEmpty}
        />
        <SectionCaption>{w.availableEmptyReasonsTitle}</SectionCaption>
        <List>
          {profileNotReady && <ListRow marker="-" title={w.availableEmptyProfileNotActive} />}
          {notAccepting && <ListRow marker="-" title={w.availableEmptyNotAccepting} />}
          <ListRow marker="-" title={w.availableEmptyNoMatch} />
        </List>
      </>
    );
  }

  return (
    <>
      <JobList>
        {items.map((card) => (
          <JobCard
            key={card.request_id}
            to={`/provider/available/${card.request_id}`}
            art={equipmentIllustration(null, card.equipment_category_name)}
            title={cardTitle(card)}
            place={w.rowSubtitle(card.model, cardAreaName(card))}
            tag={urgencyTag(card.urgency)}
            text={card.published_description}
            meta={cardMeta(card)}
          />
        ))}
      </JobList>
      <Note>{w.availableContactsNote}</Note>
    </>
  );
}
