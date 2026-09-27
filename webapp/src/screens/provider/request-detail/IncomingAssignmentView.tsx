import { useRef, useState } from 'react';
import { strings } from '../../../strings/ru';
import {
  useAcceptAssignment,
  useDeclineAssignment,
  useProviderIncoming,
} from '../../../api/hooks/useProviderRequests';
import { MessagesSection } from '../../../components/request/MessagesSection';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { urgencyLabel } from '../../../lib/status';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note, PageTitle, SectionCaption, TextCard } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { Sheet } from '../../../ui/Sheet';
import { TextAreaField } from '../../../ui/FormField';
import { relativeDay, shortDateTime } from '../../../ui/format';
import { RequestPhotos } from './RequestPhotos';
import { ContactRows } from './common';
import { equipmentTitle, runAndClose, type ProviderPanelProps } from './types';

export function IncomingAssignmentView({
  request,
  runner,
  initialAsking = false,
}: ProviderPanelProps & { initialAsking?: boolean }) {
  const assignment = request.assignment;
  const accept = useAcceptAssignment(request.id);
  const decline = useDeclineAssignment(request.id);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');
  const [asking, setAsking] = useState(initialAsking);
  const questionRef = useRef<HTMLDivElement>(null);
  const tz = request.location.timezone;
  const listed = useProviderIncoming({ poll: false }).data?.find((item) => item.id === request.id);

  const ask = () => {
    setAsking(true);
    window.setTimeout(
      () => questionRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }),
      0,
    );
  };

  return (
    <Screen
      title={strings.workspace.detailHeader(
        request.customer_org_name,
        strings.ui.requestTitle(request.request_number),
      )}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('accept')}
            disabled={runner.busy}
            onClick={() =>
              void runner.run('accept', () =>
                accept.mutateAsync({
                  assignment_id: assignment.id,
                  expected_version: request.version,
                }),
              )
            }
          >
            {strings.workspace.incomingAccept}
          </ActionButton>
          <ActionButton kind="s" disabled={runner.busy} onClick={ask}>
            {strings.workspace.incomingAskQuestion}
          </ActionButton>
        </BottomActions>
      }
    >
      <PageTitle
        subtitle={strings.workspace.rowSubtitle(
          request.customer_org_name,
          request.contacts_disclosed ? request.location.name : null,
          urgencyLabel(request.urgency).toLowerCase(),
          relativeDay(request.submitted_at ?? request.created_at, tz),
        )}
      >
        {equipmentTitle(request)}
      </PageTitle>

      {request.symptom_description && <TextCard>{request.symptom_description}</TextCard>}
      <RequestPhotos request={request} canUpload={false} />

      <List>
        <ListRow
          title={strings.workspace.cardCategoryLabel}
          value={request.equipment.category_name ?? strings.common.notSpecified}
        />
        {request.error_code && (
          <ListRow title={strings.requests.card.errorCodeTitle} value={request.error_code} />
        )}
        {listed?.contract_number && (
          <ListRow
            title={strings.workspace.contractRow}
            value={strings.workspace.contractNumber(listed.contract_number)}
          />
        )}
        {assignment.expires_at && (
          <ListRow
            title={strings.workspace.incomingReplyUntil}
            value={shortDateTime(assignment.expires_at, tz)}
          />
        )}
      </List>

      {request.contacts_disclosed ? (
        <ContactRows request={request} />
      ) : (
        <Note>{strings.workspace.incomingHiddenContacts}</Note>
      )}

      <ActionFeedback feedback={runner.feedback} />

      {asking && (
        <div ref={questionRef}>
          <SectionCaption>{strings.workspace.questionThreadTitle}</SectionCaption>
          <div className="ui-pad">
            <MessagesSection
              requestId={request.id}
              assignmentId={assignment.id}
              ownAuthorKind="provider_membership"
              placeholder={strings.workspace.questionPlaceholder}
              sendLabel={strings.workspace.questionSend}
              embedded
            />
          </div>
        </div>
      )}

      <List>
        <ListRow
          title={strings.workspace.incomingRefuse}
          action="danger"
          disabled={runner.busy}
          onClick={() => setDeclining(true)}
        />
      </List>

      <Sheet
        open={declining}
        role="alertdialog"
        title={strings.workspace.incomingRefuseSheetTitle}
        description={strings.workspace.incomingRefuseSheetText}
        onClose={() => setDeclining(false)}
        locked={runner.busy}
        actions={
          <>
            <ActionButton
              kind="d"
              loading={runner.isRunning('decline')}
              disabled={!reason.trim() || runner.busy}
              onClick={() =>
                void runAndClose(
                  runner,
                  'decline',
                  () =>
                    decline.mutateAsync({
                      assignment_id: assignment.id,
                      reason: reason.trim(),
                      expected_version: request.version,
                    }),
                  () => setDeclining(false),
                )
              }
            >
              {strings.workspace.incomingRefuse}
            </ActionButton>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setDeclining(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        <TextAreaField
          label={strings.workspace.incomingDeclineReasonLabel}
          placeholder={strings.workspace.incomingDeclineReasonPlaceholder}
          value={reason}
          onChange={setReason}
          rows={3}
        />
        <ActionFeedback feedback={declining ? runner.feedback : null} />
      </Sheet>
    </Screen>
  );
}
