import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { useRequestMessages } from '../../../api/hooks/useRequests';
import type { RequestMessage } from '../../../api/types';
import { MessagesSection } from '../../../components/request/MessagesSection';
import { Avatar, Note } from '../../../ui/blocks/Blocks';
import { Screen } from '../../../ui/layout/Screen';
import { requestNo } from '../../../ui/format';
import { requestFallback, useCustomerRequest } from './customerRequest';
import { useMarkReadOnOpen } from './useMarkReadOnOpen';
import { chatPartner, deliveredToCrm, MESSAGE_STATUSES, messageAuthorLine, openQuestion } from './cardModel';
import { ClarificationView } from './ClarificationView';
import '../../../components/request/request.css';

export function ChatHead({ name, sub }: { name: string; sub: string }) {
  return (
    <span className="request-chat-head">
      <Avatar name={name} aria-hidden />
      <span className="request-chat-head__who">
        <span className="request-chat-head__name">{name}</span>
        <span className="request-chat-head__sub">{sub}</span>
      </span>
    </span>
  );
}

export function RequestMessagesScreen() {
  const { id } = useParams<{ id: string }>();
  const { query, request } = useCustomerRequest(id);
  const messages = useRequestMessages(request ? id : undefined, Boolean(request));
  const [chat, setChat] = useState(false);
  const [pinned, setPinned] = useState<RequestMessage | null>(null);
  const providerOrg = request?.assignment?.provider_organization_id ?? null;
  const open = openQuestion(messages.data, providerOrg);
  useEffect(() => {
    if (!pinned && open?.author_kind === 'integration_client') setPinned(open);
  }, [open, pinned]);
  const back = id ? `/requests/${id}` : undefined;
  const title = strings.requests.messages.title;

  useMarkReadOnOpen(request ? id : undefined);

  const fallback = requestFallback({ query, request, title, back });
  if (fallback || !request) return fallback;

  const canPost = MESSAGE_STATUSES.has(request.status);
  const providerOrgId = request.assignment?.provider_organization_id ?? null;
  const partner = chatPartner(request);
  const category = request.equipment_category_name ?? request.equipment.category_name;
  const sub = [requestNo(request.request_number), category?.toLowerCase()].filter(Boolean).join(' · ');

  const question = pinned ?? (open?.author_kind === 'integration_client' ? open : null);
  if (!chat && canPost && question) {
    return <ClarificationView request={request} question={question} back={back} onOpenChat={() => setChat(true)} />;
  }

  return (
    <Screen
      className="request-chat"
      title={<span className="ui-visually-hidden">{title}</span>}
      subtitle={<ChatHead name={partner} sub={sub} />}
      back={back}
    >
      <div className="request-thread">
        <MessagesSection
          variant="chat"
          requestId={request.id}
          ownAuthorKind="customer_membership"
          placeholder={strings.requests.messages.placeholderCustomer}
          allowPhotos={canPost}
          attachments={request.attachments}
          otherAuthor={partner}
          authorName={(m) => messageAuthorLine(m, request)}
          deliveredToCrm={deliveredToCrm}
          canPost={canPost}
          quickReplies={strings.requests.messages.quickReplies}
          timezone={request.location.timezone}
          filter={(m) => !m.thread_provider_id || m.thread_provider_id === providerOrgId}
          embedded
        />
      </div>
      {!canPost && <Note>{strings.requests.messages.closedNote}</Note>}
    </Screen>
  );
}
