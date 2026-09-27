import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useReportCompletion } from '../../../api/hooks/useProviderRequests';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note } from '../../../ui/blocks/Blocks';
import { Segmented } from '../../../ui/Segmented';
import { TextAreaField } from '../../../ui/FormField';
import { ReportPhotoSlots } from './ReportPhotoSlots';
import { runAndClose, type ProviderSubViewProps } from './types';

type Outcome = 'resolved' | 'not_resolved';

export function WorkProgressPanel({
  request,
  runner,
  onDone,
  onStale,
}: ProviderSubViewProps & { onStale?: () => unknown }) {
  const reportCompletion = useReportCompletion(request.id);
  const [outcome, setOutcome] = useState<Outcome>('resolved');
  const [summary, setSummary] = useState('');

  return (
    <Screen
      title={strings.workspace.reportHeader}
      subtitle={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('reportCompletion')}
            disabled={!summary.trim() || runner.busy}
            onClick={() =>
              void runAndClose(
                runner,
                'reportCompletion',
                () =>
                  reportCompletion.mutateAsync({
                    assignment_id: request.assignment.id,
                    outcome,
                    summary: summary.trim(),
                    expected_version: request.version,
                  }),
                onDone,
              )
            }
          >
            {strings.workspace.reportSend}
          </ActionButton>
        </BottomActions>
      }
    >
      <TextAreaField
        id="report-summary"
        label={strings.workspace.reportWhatDone}
        placeholder={strings.workspace.reportSummaryPlaceholder}
        value={summary}
        onChange={setSummary}
        rows={4}
      />
      <Segmented
        label={strings.workspace.reportOutcomeLabel}
        items={[
          { id: 'resolved', label: strings.workspace.reportOutcomeOption.resolved },
          { id: 'not_resolved', label: strings.workspace.reportOutcomeOption.not_resolved },
        ]}
        value={outcome}
        onChange={setOutcome}
      />
      <ReportPhotoSlots request={request} onStale={onStale} />
      <Note>{strings.workspace.reportCloseNote}</Note>
      <ActionFeedback feedback={runner.feedback} />
    </Screen>
  );
}
