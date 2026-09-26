import { Link } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import { useRequestMessages } from '../../../api/hooks/useRequests';
import type { RequestCustomer } from '../../../api/types';
import { Avatar } from '../../../ui/blocks/Blocks';
import { eventTime } from './cardFormat';
import { openQuestion, questionAuthor } from './cardModel';

export function CardQuestion({ request }: { request: RequestCustomer }) {
  const unread = (request.unread_messages_count ?? 0) > 0;
  const messages = useRequestMessages(request.id, unread);
  const question = unread ? openQuestion(messages.data, request.assignment?.provider_organization_id ?? null) : null;
  if (!question || question.author_kind !== 'integration_client') return null;
  const c = strings.requests.card;
  const author = questionAuthor(question, request);
  return (
    <Link className="request-question" to={`/requests/${request.id}/messages`}>
      <span className="request-question__head">
        <Avatar name={author.name} aria-hidden />
        <span className="request-question__who">
          <span className="request-question__author">{author.name}</span>
          <span className="request-question__meta">
            {[author.org, eventTime(question.created_at, request.location.timezone)].filter(Boolean).join(' · ')}
          </span>
        </span>
      </span>
      <span className="request-question__body">{question.body}</span>
      <span className="request-question__cta">{c.questionAnswer}</span>
    </Link>
  );
}
