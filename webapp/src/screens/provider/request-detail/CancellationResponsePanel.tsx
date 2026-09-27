import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useRespondToCancellation } from '../../../api/hooks/useProviderRequests';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { useConfirm } from '../../../components/useConfirm';
import { cancellationStatusLabel } from '../../../lib/status';
import { BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Banner } from '../../../ui/blocks/Blocks';
import { Sheet } from '../../../ui/Sheet';
import { TextAreaField } from '../../../ui/FormField';
import { runAndClose, type ProviderPanelProps } from './types';

export function CancellationBanner({ request }: Pick<ProviderPanelProps, 'request'>) {
  const cancellation = request.cancellation;
  if (!cancellation) return null;
  const title =
    cancellation.status === 'pending'
      ? strings.workspace.cancellationBannerTitle[
          cancellation.target === 'change_provider' ? 'change_provider' : 'cancel_request'
        ]
      : cancellationStatusLabel(cancellation.status);
  return (
    <Banner tone={cancellation.status === 'pending' ? 'y' : 'w'} title={title} role="status">
      {cancellation.status === 'pending'
        ? strings.workspace.cancellationBannerText(cancellation.reason)
        : cancellation.reason
          ? strings.workspace.cancellationReasonText(cancellation.reason)
          : undefined}
    </Banner>
  );
}

export function CancellationActions({ request, runner }: ProviderPanelProps) {
  const respond = useRespondToCancellation(request.id);
  const { confirm, dialog } = useConfirm();
  const [disagreeing, setDisagreeing] = useState(false);
  const [comment, setComment] = useState('');
  const cancellation = request.cancellation;
  if (!cancellation || cancellation.status !== 'pending') return null;

  const send = (decision: 'accept' | 'decline', text: string, onDone: () => void) =>
    runAndClose(
      runner,
      'respondCancellation',
      () =>
        respond.mutateAsync({
          assignment_id: request.assignment.id,
          cancellation_id: cancellation.id,
          decision,
          comment: text.trim() || null,
          expected_version: request.version,
        }),
      onDone,
    );

  const agree = async () => {
    const ok = await confirm({
      title: strings.workspace.cancellationConfirmTitle,
      description: strings.workspace.cancellationConfirmText,
      confirmLabel: strings.workspace.cancellationConfirm,
    });
    if (ok) await send('accept', '', () => undefined);
  };

  return (
    <>
      <BottomActions>
        <ActionButton
          loading={runner.isRunning('respondCancellation') && !disagreeing}
          disabled={runner.busy}
          onClick={() => void agree()}
        >
          {strings.workspace.cancellationConfirm}
        </ActionButton>
        <ActionButton kind="s" disabled={runner.busy} onClick={() => setDisagreeing(true)}>
          {strings.workspace.cancellationDisagree}
        </ActionButton>
      </BottomActions>
      <Sheet
        open={disagreeing}
        title={strings.workspace.cancellationDisagreeTitle}
        description={strings.workspace.cancellationDisagreeText}
        onClose={() => setDisagreeing(false)}
        locked={runner.busy}
        actions={
          <>
            <ActionButton
              loading={runner.isRunning('respondCancellation')}
              disabled={runner.busy || !comment.trim()}
              onClick={() =>
                void send('decline', comment, () => {
                  setDisagreeing(false);
                  setComment('');
                })
              }
            >
              {strings.workspace.cancellationSubmit}
            </ActionButton>
            <ActionButton kind="s" disabled={runner.busy} onClick={() => setDisagreeing(false)}>
              {strings.common.cancel}
            </ActionButton>
          </>
        }
      >
        <TextAreaField
          label={strings.workspace.cancellationCommentLabel}
          placeholder={strings.workspace.cancellationCommentLabel}
          value={comment}
          onChange={setComment}
          rows={3}
        />
        <ActionFeedback feedback={disagreeing ? runner.feedback : null} />
      </Sheet>
      {dialog}
    </>
  );
}
