import { useNavigate } from 'react-router-dom';
import { strings } from '../../../strings/ru';
import type { RequestCustomer } from '../../../api/types';
import { Screen, BottomActions } from '../../../ui/layout/Screen';
import { ActionButton } from '../../../ui/layout/ActionButton';
import { StatusHero } from '../../../ui/StatusHero';
import { requestNo } from '../../../ui/format';

const t = strings.requests.wizard.sent;

export function RequestSentScreen({ request }: { request: RequestCustomer }) {
  const navigate = useNavigate();
  const number = requestNo(request.request_number);
  const toApproval = request.status === 'approval_required';
  const provider = request.assignment?.provider_display_name ?? null;

  return (
    <Screen
      title={strings.ui.requestTitle(request.request_number)}
      actions={
        <BottomActions>
          <ActionButton onClick={() => navigate(`/requests/${request.id}`, { replace: true })}>
            {t.open}
          </ActionButton>
        </BottomActions>
      }
    >
      <StatusHero
        illustration="request-sent"
        top={72}
        role="status"
        title={toApproval ? t.approvalTitle : t.title}
      >
        {toApproval ? t.approvalText(number) : t.text(number, provider)}
      </StatusHero>
    </Screen>
  );
}
