import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import {
  useConfirmCompletion,
  useCreateFollowup,
  useRequestCancellation,
  useReturnToDraft,
  useRevokeAssignment,
  useSubmitToOwnService,
  useWithdrawCancellation,
} from '../../../api/hooks/useRequests';
import { useRequestReviewState } from '../../../api/hooks/useReviews';
import type { Offer, RequestCustomer } from '../../../api/types';
import type { ActionRunner } from '../../../components/actions/useActionRunner';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { List, ListRow } from '../../../ui/List';
import { Sheet } from '../../../ui/Sheet';
import { TextAreaField } from '../../../ui/FormField';
import { forceDeadlinePassed, hasNoProviders, pendingQuote, reserveLapsed } from './cardFormat';
import { deliveryProblem } from './delivery';
import { MESSAGE_STATUSES } from './cardModel';

type Confirm = (options: {
  title: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
}) => Promise<boolean>;

interface CardActionsInput {
  request: RequestCustomer;
  isManager: boolean;
  runner: ActionRunner;
  confirm: Confirm;
  offers: Offer[] | undefined;
  visitOffer: boolean;
  onRemark: () => void;
  onWait: () => void;
}

export interface CardActions {
  bottom: ReactNode;
  rows: ReactNode;
  overlay: ReactNode;
  sheetOpen: boolean;
  messageButton: boolean;
  feedbackInBottom: boolean;
}

export function useCardActions({
  request,
  isManager,
  runner,
  confirm,
  offers,
  visitOffer,
  onRemark,
  onWait,
}: CardActionsInput): CardActions {
  const navigate = useNavigate();
  const c = strings.requests.card;
  const [returning, setReturning] = useState(false);
  const [comment, setComment] = useState('');

  const returnToDraft = useReturnToDraft(request.id);
  const submitToOwnService = useSubmitToOwnService(request.id);
  const confirmCompletion = useConfirmCompletion(request.id);
  const createFollowup = useCreateFollowup();
  const revokeAssignment = useRevokeAssignment(request.id);
  const requestCancellation = useRequestCancellation(request.id);
  const withdrawCancellation = useWithdrawCancellation(request.id);
  const reviewState = useRequestReviewState(isManager && request.status === 'closed' ? request.id : undefined);
  const canLeaveReview = Boolean(
    reviewState.data && !reviewState.data.review && reviewState.data.eligibility.can_submit,
  );

  const id = request.id;
  const status = request.status;
  const assignment = request.assignment;
  const quote = pendingQuote(request);
  const activeOffers = (offers ?? []).filter((o) => o.state === 'active');
  const noProviders = hasNoProviders(request, offers);
  const cancellation = request.cancellation;
  const cancellationOpen = Boolean(cancellation && ['pending', 'disputed'].includes(cancellation.status));
  const canCancel = isManager && !['closed', 'cancelled', 'draft'].includes(status) && !cancellationOpen;
  const canRevoke =
    isManager && status === 'awaiting_provider' && assignment?.state === 'pending' && request.route === 'own_service';

  const go = (path: string) => () => navigate(path);
  const phone = assignment?.provider_contact_phone?.trim() || null;
  const tel = phone ? `tel:${phone.replace(/[^\d+]/g, '')}` : null;
  const providerName = assignment?.provider_display_name ?? null;
  const messagesPath = `/requests/${id}/messages`;
  const writeLabel = assignment?.field_worker ? c.writeToMaster : c.writeToProvider;
  const callRow = () =>
    tel && (
      <ListRow
        key="call"
        title={providerName ? c.callProviderNamed(providerName) : c.callProvider}
        action="accent"
        href={tel}
      />
    );

  const submitOwn = () =>
    void runner.run('submitOwnService', () =>
      submitToOwnService.mutateAsync({
        photos_incomplete: request.photos_incomplete,
        photos_incomplete_reason: request.photos_incomplete
          ? request.photos_incomplete_reason || strings.common.notSpecified
          : null,
        expected_version: request.version,
      }),
    );

  const stopSearch = async (title: string, description: string, then?: string) => {
    const ok = await confirm({ title, description, destructive: !then });
    if (!ok) return;
    const done = await runner.run('stopSearch', () =>
      requestCancellation.mutateAsync({
        target: 'change_provider',
        reason: null,
        expected_version: request.version,
      }),
    );
    if (done && then) navigate(then);
  };

  const revoke = async () => {
    if (!assignment) return;
    const ok = await confirm({ title: c.actionRevokeAssignmentConfirm, description: c.revokeConfirmText });
    if (!ok) return;
    void runner.run('revokeAssignment', () =>
      revokeAssignment.mutateAsync({ assignment_id: assignment.id, expected_version: request.version }),
    );
  };

  const withdraw = async () => {
    if (!cancellation) return;
    const ok = await confirm({ title: c.withdrawRequestConfirm, description: c.withdrawRequestConfirmText });
    if (!ok) return;
    void runner.run('withdrawCancellation', () =>
      withdrawCancellation.mutateAsync({ cancellation_id: cancellation.id, expected_version: request.version }),
    );
  };

  const followup = async () => {
    const created = await runner.run('followup', () => createFollowup.mutateAsync({ id, input: {} }));
    if (created) navigate(`/requests/${created.id}`);
  };

  const submitReturn = async () => {
    const done = await runner.run('returnToDraft', async () => {
      await returnToDraft.mutateAsync({ comment: comment.trim(), expected_version: request.version });
      return true;
    });
    if (done) {
      setReturning(false);
      setComment('');
    }
  };

  let primary: ReactNode = null;
  let secondary: ReactNode = null;
  let messageButton = false;
  let stack = false;
  const rows: ReactNode[] = [];
  const cancelRow = (label: string = c.actionCancel) =>
    canCancel && <ListRow key="cancel" title={label} action="danger" onClick={go(`/requests/${id}/cancel`)} />;
  const cancelButton = (
    <ActionButton key="cancel" kind="s" disabled={runner.busy} to={`/requests/${id}/cancel`}>
      {c.cancelShort}
    </ActionButton>
  );
  const writeButton = (kind: 'p' | 's') => {
    messageButton = true;
    return (
      <ActionButton key="write" kind={kind} to={messagesPath}>
        {writeLabel}
      </ActionButton>
    );
  };

  if (isManager && !visitOffer) {
    switch (status) {
      case 'approval_required':
        stack = true;
        if (request.route === 'own_service') {
          primary = (
            <ActionButton key="own" loading={runner.isRunning('submitOwnService')} disabled={runner.busy} onClick={submitOwn}>
              {c.actionSubmitOwnService}
            </ActionButton>
          );
          rows.push(<ListRow key="publish" title={c.findProvider} action="accent" onClick={go(`/requests/${id}/publish`)} />);
        } else {
          primary = (
            <ActionButton key="publish" disabled={runner.busy} onClick={go(`/requests/${id}/publish`)}>
              {c.reviewAndPublish}
            </ActionButton>
          );
          rows.push(
            <ListRow key="own" title={c.actionSubmitOwnService} action="accent" disabled={runner.busy} loading={runner.isRunning('submitOwnService')} onClick={submitOwn} />,
          );
        }
        secondary = (
          <ActionButton key="return" kind="s" disabled={runner.busy} onClick={() => setReturning(true)}>
            {c.returnToEmployee}
          </ActionButton>
        );
        break;

      case 'awaiting_provider':
        if (deliveryProblem(request) && tel) {
          primary = (
            <ActionButton key="call" href={tel}>
              {c.callProvider}
            </ActionButton>
          );
        } else if (canRevoke) {
          secondary = (
            <ActionButton key="wait" kind="s" disabled={runner.busy} onClick={onWait}>
              {c.wait}
            </ActionButton>
          );
          primary = (
            <ActionButton key="revoke" loading={runner.isRunning('revokeAssignment')} disabled={runner.busy} onClick={() => void revoke()}>
              {c.findOther}
            </ActionButton>
          );
          rows.push(callRow());
        } else {
          rows.push(callRow());
        }
        rows.push(cancelRow());
        break;

      case 'searching':
        if (noProviders) {
          secondary = cancelButton;
          primary = (
            <ActionButton key="term" disabled={runner.busy} onClick={() => void stopSearch(c.editSearchConfirm, c.editSearchConfirmText, `/requests/${id}/details`)}>
              {c.changeTerm}
            </ActionButton>
          );
        } else if (reserveLapsed(request)) {
          primary = (
            <ActionButton key="offers" to={`/requests/${id}/offers`}>
              {c.chooseAnotherOffer}
            </ActionButton>
          );
          rows.push(cancelRow());
        } else {
          const edit = (
            <ActionButton key="edit" kind="s" disabled={runner.busy} onClick={() => void stopSearch(c.editSearchConfirm, c.editSearchConfirmText, `/requests/${id}/details`)}>
              {c.editRequest}
            </ActionButton>
          );
          if (activeOffers.length > 0) {
            stack = true;
            secondary = edit;
            primary = (
              <ActionButton key="offers" to={`/requests/${id}/offers`}>
                {c.compareOffers}
              </ActionButton>
            );
          } else {
            primary = edit;
          }
          rows.push(
            <ListRow key="unpublish" title={c.unpublish} action="danger" disabled={runner.busy} loading={runner.isRunning('stopSearch')} onClick={() => void stopSearch(c.unpublishConfirm, c.unpublishConfirmText)} />,
          );
        }
        break;

      case 'awaiting_assignment_confirmation':
        rows.push(
          <ListRow key="unchoose" title={c.cancelChoice} action="danger" disabled={runner.busy} loading={runner.isRunning('stopSearch')} onClick={() => void stopSearch(c.cancelChoiceConfirm, c.cancelChoiceConfirmText)} />,
        );
        rows.push(cancelRow());
        break;

      case 'accepted':
      case 'scheduled':
      case 'in_progress':
        if (quote) {
          stack = true;
          secondary = writeButton('s');
          primary = (
            <ActionButton key="quote" to={`/requests/${id}/repair-quotes/${quote.id}`}>
              {c.actionOpenQuoteApproval}
            </ActionButton>
          );
        } else {
          primary = writeButton(status === 'accepted' ? 's' : 'p');
        }
        rows.push(cancelRow(status === 'scheduled' ? c.cancelVisit : c.actionCancel));
        break;

      case 'completion_reported':
        secondary = (
          <ActionButton key="remark" kind="s" disabled={runner.busy} onClick={onRemark}>
            {c.actionRejectCompletion}
          </ActionButton>
        );
        primary = (
          <ActionButton
            key="confirm"
            loading={runner.isRunning('confirmCompletion')}
            disabled={runner.busy}
            onClick={() =>
              void runner.run('confirmCompletion', () =>
                confirmCompletion.mutateAsync({ expected_version: request.version }),
              )
            }
          >
            {c.allWorks}
          </ActionButton>
        );
        break;

      case 'action_required':
        secondary = cancelButton;
        if (noProviders) {
          primary = (
            <ActionButton key="term" to={`/requests/${id}/details`}>
              {c.changeTerm}
            </ActionButton>
          );
        } else {
          primary = (
            <ActionButton key="find" to={`/requests/${id}/publish`}>
              {c.findOther}
            </ActionButton>
          );
          rows.push(
            callRow(),
            <ListRow key="details" title={c.actionUpdateDetails} action="accent" onClick={go(`/requests/${id}/details`)} />,
          );
        }
        break;

      case 'cancellation_pending':
        if (cancellationOpen) {
          secondary = (
            <ActionButton
              key="withdraw"
              kind="s"
              loading={runner.isRunning('withdrawCancellation')}
              disabled={runner.busy}
              onClick={() => void withdraw()}
            >
              {c.withdrawRequest}
            </ActionButton>
          );
          if (cancellation?.status === 'pending' && !forceDeadlinePassed(cancellation)) {
            primary = (
              <ActionButton key="waiting" disabled>
                {c.waitingAnswer}
              </ActionButton>
            );
          }
        }
        break;

      case 'closed':
        if (canLeaveReview) {
          primary = (
            <ActionButton key="review" to={`/requests/${id}/review`}>
              {c.leaveReview}
            </ActionButton>
          );
        }
        break;

      default:
        break;
    }
  } else if (isManager && visitOffer) {
    rows.push(cancelRow());
  } else if (MESSAGE_STATUSES.has(status) && !visitOffer) {
    primary = writeButton(status === 'scheduled' || status === 'in_progress' ? 'p' : 's');
  }

  if (status === 'closed' && primary) {
    rows.push(
      <ListRow key="again" title={c.brokeAgain} action="accent" disabled={runner.busy} loading={runner.isRunning('followup')} onClick={() => void followup()} />,
    );
  }
  if (status === 'closed' && !primary) {
    primary = (
      <ActionButton key="again" loading={runner.isRunning('followup')} disabled={runner.busy} onClick={() => void followup()}>
        {c.brokeAgain}
      </ActionButton>
    );
  }
  if (status === 'cancelled') {
    rows.push(
      <ListRow key="new" title={c.createNewRequest} action="accent" disabled={runner.busy} loading={runner.isRunning('followup')} onClick={() => void followup()} />,
    );
  }

  const visibleRows = rows.filter(Boolean);
  const buttons = (stack ? [primary, secondary] : [secondary, primary]).filter(Boolean);
  const feedbackNote = !returning && runner.feedback ? <ActionFeedback feedback={runner.feedback} /> : undefined;

  return {
    bottom:
      buttons.length > 0 ? (
        <BottomActions layout={buttons.length > 1 && !stack ? 'row' : 'stack'} note={feedbackNote}>
          {buttons}
        </BottomActions>
      ) : null,
    feedbackInBottom: buttons.length > 0,
    rows: visibleRows.length > 0 ? <List>{visibleRows}</List> : null,
    sheetOpen: returning,
    messageButton,
    overlay: (
      <Sheet
        open={returning}
        title={c.returnSheetTitle}
        description={c.returnSheetText}
        onClose={() => setReturning(false)}
        locked={runner.busy}
        actions={
          <>
            <ActionButton
              loading={runner.isRunning('returnToDraft')}
              disabled={!comment.trim() || runner.busy}
              onClick={() => void submitReturn()}
            >
              {c.actionReturnToDraft}
            </ActionButton>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setReturning(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        <TextAreaField
          label={c.actionReturnToDraftCommentLabel}
          value={comment}
          onChange={setComment}
          rows={3}
        />
        <ActionFeedback feedback={runner.feedback} />
      </Sheet>
    ),
  };
}
