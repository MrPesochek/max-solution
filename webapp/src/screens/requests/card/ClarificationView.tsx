import { Fragment, useState } from 'react';
import { strings } from '../../../strings/ru';
import { usePostMessage, useRequestMessages } from '../../../api/hooks/useRequests';
import type { RequestCustomer, RequestMessage } from '../../../api/types';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { useActionRunner } from '../../../components/actions/useActionRunner';
import { formatTime } from '../../../lib/datetime';
import { Avatar, PageTitle } from '../../../ui/blocks/Blocks';
import { Screen, BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Chips, Chip } from '../../../ui/Chips';
import { TextAreaField } from '../../../ui/FormField';
import { requestEquipmentFullName } from '../components/equipmentName';
import { deliveredToCrm, questionAuthor } from './cardModel';

export function ClarificationView({
  request,
  question,
  back,
  onOpenChat,
}: {
  request: RequestCustomer;
  question: RequestMessage;
  back?: string;
  onOpenChat: () => void;
}) {
  const m = strings.requests.messages;
  const tz = request.location.timezone;
  const post = usePostMessage(request.id);
  const runner = useActionRunner({ fallbackMessage: strings.requests.card.messageSendError });
  const [text, setText] = useState('');
  const [sentList, setSentList] = useState<RequestMessage[]>([]);
  const [adding, setAdding] = useState(false);
  const sent = sentList.length > 0;
  const composing = !sent || adding;
  const messages = useRequestMessages(request.id, sent);
  const current = (message: RequestMessage) => messages.data?.find((m) => m.id === message.id) ?? message;
  const author = questionAuthor(question, request);
  const provider = request.assignment?.provider_display_name;

  const send = async () => {
    const body = text.trim();
    if (!body) return;
    const message = await runner.run('answer', () => post.mutateAsync({ body }));
    if (message) {
      setSentList((list) => [...list, message]);
      setAdding(false);
      setText('');
    }
  };

  const addQuick = (reply: string) => setText((current) => (current.trim() ? `${current.trim()}. ${reply}` : reply));

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      back={back}
      actions={
        <BottomActions>
          {!composing ? (
            <ActionButton kind="s" onClick={() => setAdding(true)}>
              {m.addToAnswer}
            </ActionButton>
          ) : (
            <ActionButton loading={runner.isRunning('answer')} disabled={!text.trim() || runner.busy} onClick={() => void send()}>
              {m.answer}
            </ActionButton>
          )}
          <ActionButton kind="g" onClick={onOpenChat}>
            {m.openChat}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle subtitle={[requestEquipmentFullName(request), provider].filter(Boolean).join(' · ')}>
        {sent ? m.answerSentTitle : m.clarificationTitle}
      </PageTitle>
      <div className="request-question">
        <span className="request-question__head">
          <Avatar name={author.name} aria-hidden />
          <span className="request-question__who">
            <span className="request-question__author">{author.name}</span>
            <span className="request-question__meta">
              {[author.org, formatTime(question.created_at, tz)].filter(Boolean).join(' · ')}
            </span>
          </span>
        </span>
        <span className="request-question__body">{question.body}</span>
      </div>
      {sentList.map((answer) => (
        <Fragment key={answer.id}>
          <div className="request-answer">
            <span className="ui-visually-hidden">{m.you}: </span>
            {answer.body}
          </div>
          <span className="request-answer-meta">
            {deliveredToCrm(current(answer)) ? m.deliveredToCrm : m.sentAt(formatTime(answer.created_at, tz))}
          </span>
        </Fragment>
      ))}
      {composing && (
        <>
          <Chips label={m.quickLabel}>
            {m.clarificationQuick.map((reply) => (
              <Chip key={reply} variant="outline" onClick={() => addQuick(reply)}>
                {reply}
              </Chip>
            ))}
          </Chips>
          <TextAreaField label={sent ? m.addToAnswerLabel : m.answerLabel} value={text} onChange={setText} placeholder={m.answerPlaceholder} rows={3} maxLength={4000} />
        </>
      )}
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
    </Screen>
  );
}
