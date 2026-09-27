import { useState } from 'react';
import { strings } from '../../../strings/ru';
import { useProviderWarrantyDecision } from '../../../api/hooks/useProviderRequests';
import type { WarrantyDecision } from '../../../api/types';
import { ActionFeedback } from '../../../components/actions/ActionFeedback';
import { BottomActions, Screen } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { Note } from '../../../ui/blocks/Blocks';
import { List, ListRow } from '../../../ui/List';
import { TextAreaField } from '../../../ui/FormField';
import { runAndClose, type ProviderSubViewProps } from './types';

const OPTIONS: WarrantyDecision[] = ['warranty', 'not_warranty', 'undetermined'];

export function WarrantyPanel({ request, runner, onDone }: ProviderSubViewProps) {
  const setWarranty = useProviderWarrantyDecision(request.id);
  const current = request.assignment.warranty_decision;
  const [choice, setChoice] = useState<WarrantyDecision>(
    current === 'not_stated' ? 'undetermined' : current,
  );
  const [comment, setComment] = useState(request.assignment.warranty_decision_comment ?? '');

  return (
    <Screen
      title={strings.workspace.warrantyTitle}
      subtitle={strings.ui.requestTitle(request.request_number)}
      back={onDone}
      actions={
        <BottomActions>
          <ActionButton
            loading={runner.isRunning('warranty')}
            disabled={runner.busy || !comment.trim()}
            onClick={() =>
              void runAndClose(
                runner,
                'warranty',
                () =>
                  setWarranty.mutateAsync({
                    assignment_id: request.assignment.id,
                    decision: choice,
                    comment: comment.trim() || null,
                    expected_version: request.version,
                  }),
                onDone,
              )
            }
          >
            {strings.workspace.warrantySave}
          </ActionButton>
        </BottomActions>
      }
    >
      <Note>{strings.workspace.warrantyDisclaimer}</Note>
      <List role="radiogroup" aria-label={strings.workspace.warrantyTitle}>
        {OPTIONS.map((option) => (
          <ListRow
            key={option}
            title={strings.workspace.warrantyOption[option]}
            control={{ type: 'radio', checked: choice === option }}
            onToggle={() => setChoice(option)}
          />
        ))}
      </List>
      <TextAreaField
        label={strings.workspace.warrantyCommentLabel}
        value={comment}
        onChange={setComment}
        rows={3}
      />
      <ActionFeedback feedback={runner.feedback} />
    </Screen>
  );
}
