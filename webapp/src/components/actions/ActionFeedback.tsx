import { strings } from '../../strings/ru';
import { Banner, Note } from '../../ui/blocks/Blocks';
import type { ActionFeedbackState } from './actionErrors';

export function ActionFeedback({ feedback }: { feedback: ActionFeedbackState | null }) {
  if (!feedback) return null;
  if (feedback.kind === 'stale') {
    return (
      <Banner tone="y" role="alert" title={strings.actions.staleTitle}>
        {strings.actions.staleDescription}
      </Banner>
    );
  }
  return (
    <Note tone="error" role="alert">
      {feedback.message}
    </Note>
  );
}
