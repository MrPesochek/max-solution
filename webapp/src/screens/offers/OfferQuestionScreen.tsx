import { useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { usePostMessage, useRefreshRequest, useRequestMessages } from '../../api/hooks/useRequests';
import { useOfferMessages, usePostOfferMessage, useRequestOffers } from '../../api/hooks/useOffers';
import type { RequestCustomer } from '../../api/types';
import { MessagesSection, type MessageThreadSource } from '../../components/request/MessagesSection';
import { Skeleton } from '../../components/states/Skeleton';
import { Banner, Note } from '../../ui/blocks/Blocks';
import { Screen } from '../../ui/layout/Screen';
import { requestNo } from '../../ui/format';
import { requestFallback, useCustomerRequest } from '../requests/card/customerRequest';

export function OfferQuestionScreen() {
  const { id, offerId: offerParam, providerId } = useParams<{ id: string; offerId?: string; providerId?: string }>();
  const { query, request } = useCustomerRequest(id);
  const offers = useRequestOffers(id);
  const t = strings.offers.question;
  const back = offerParam ? `/requests/${id}/offers/${offerParam}` : `/requests/${id}`;

  const fallback = requestFallback({ query, request, title: t.title, back });
  if (fallback || !request || !id) return fallback;
  if (!offerParam && offers.isPending) {
    return (
      <Screen title={t.title} back={back}>
        <Skeleton lines={4} />
      </Screen>
    );
  }

  const offer = offerParam
    ? offers.data?.find((o) => o.id === offerParam)
    : offers.data
        ?.filter((o) => o.provider_organization_id === providerId)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const offerId = offerParam ?? offer?.id;
  const threadProvider = offer?.provider_organization_id ?? providerId ?? null;

  return (
    <QuestionThread
      request={request}
      offerId={offerId}
      threadProviderId={threadProvider}
      providerName={offer?.provider?.display_name ?? null}
      back={back}
    />
  );
}

function QuestionThread({
  request,
  offerId,
  threadProviderId,
  providerName,
  back,
}: {
  request: RequestCustomer;
  offerId: string | undefined;
  threadProviderId: string | null;
  providerName: string | null;
  back: string;
}) {
  const t = strings.offers.question;
  const refresh = useRefreshRequest(request.id);
  const offerMessages = useOfferMessages(request.id, offerId);
  const postOffer = usePostOfferMessage(request.id, offerId ?? '');
  const requestMessages = useRequestMessages(request.id, !offerId);
  const postMessage = usePostMessage(request.id);
  const open = request.status === 'searching';

  const thread: MessageThreadSource = offerId
    ? { query: offerMessages, send: (body) => postOffer.mutateAsync({ body }) }
    : {
        query: requestMessages,
        send: (body) => postMessage.mutateAsync({ body, thread_provider_id: threadProviderId }),
      };

  return (
    <Screen title={t.title} subtitle={`${requestNo(request.request_number)} · ${t.beforeChoice}`} back={back}>
      <Banner tone="a" title={t.privateTitle}>
        {t.privateText}
      </Banner>
      <div className="request-thread">
        <MessagesSection
          requestId={request.id}
          ownAuthorKind="customer_membership"
          thread={thread}
          filter={offerId ? undefined : (m) => m.thread_provider_id === threadProviderId}
          otherAuthor={providerName ?? strings.offers.providerFallback}
          fieldLabel={t.fieldLabel}
          placeholder={t.placeholder}
          canPost={open}
          timezone={request.location.timezone}
          onSendError={() => void refresh()}
          embedded
        />
      </div>
      {!open && <Note>{strings.errorCodes.OFFER_DIALOG_CLOSED}</Note>}
    </Screen>
  );
}
