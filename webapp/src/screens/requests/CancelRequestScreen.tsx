import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useRefreshRequest, useRequestCancellation } from '../../api/hooks/useRequests';
import type { CancellationTarget } from '../../api/types';
import { canManageRequestApprovals } from '../../lib/roles';
import { useSession } from '../../session/SessionContext';
import { ActionFeedback } from '../../components/actions/ActionFeedback';
import { useActionRunner } from '../../components/actions/useActionRunner';
import { useConfirm } from '../../components/useConfirm';
import { Screen, BottomActions } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Banner, PageTitle } from '../../ui/blocks/Blocks';
import { ChoiceCard, ChoiceGroup } from '../../ui/ChoiceCard';
import { SceneBanner } from '../../ui/SceneBanner';
import { TextField } from '../../ui/FormField';
import { List, ListRow } from '../../ui/List';
import { requestFallback, useCustomerRequest } from './card/customerRequest';
import { CancellationNotice } from './card/CancellationNotice';
import { CardHero } from '../../ui/CardHero';
import { requestEquipmentFullName } from './components/equipmentName';
import '../../components/request/request.css';

export function CancelRequestScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { activeMembership } = useSession();
  const { query, request } = useCustomerRequest(id);
  const requestCancellation = useRequestCancellation(id ?? '');
  const refresh = useRefreshRequest(id);
  const runner = useActionRunner({ onStale: refresh });
  const { confirm, dialog } = useConfirm();

  const [target, setTarget] = useState<CancellationTarget>('cancel_request');
  const [reason, setReason] = useState('');
  const c = strings.requests.cancel;
  const back = id ? `/requests/${id}` : undefined;

  if (!activeMembership || !id) return null;
  const fallback = requestFallback({
    query,
    request,
    title: c.title,
    back,
    noAccess: !canManageRequestApprovals(activeMembership.role),
  });
  if (fallback || !request) return fallback;

  const cancellation = request.cancellation;
  if (cancellation && ['pending', 'disputed'].includes(cancellation.status)) {
    return (
      <Screen title={c.title} back={back}>
        <CardHero
          scene="status-cancel"
          title={
            cancellation.status === 'disputed'
              ? strings.requests.card.cancelDisputedTitle
              : strings.requests.card.cancellationPendingTitle
          }
          text={
            cancellation.status === 'disputed'
              ? strings.requests.card.cancelDisputedDescription
              : strings.requests.card.cancellationPendingText
          }
        />
        <div className="ui-pad">
          <ActionFeedback feedback={runner.feedback} />
        </div>
        <CancellationNotice request={request} isManager runner={runner} confirm={confirm} withdrawRow />
        {dialog}
      </Screen>
    );
  }

  const isAccepted = request.assignment?.state === 'accepted';
  const canChangeProvider =
    ['searching', 'awaiting_assignment_confirmation'].includes(request.status) ||
    ['pending', 'accepted'].includes(request.assignment?.state ?? '');
  const effectiveTarget: CancellationTarget = canChangeProvider ? target : 'cancel_request';

  const handleSubmit = async () => {
    const ok = await runner.run('request', async () => {
      await requestCancellation.mutateAsync({
        target: effectiveTarget,
        reason: reason.trim() || null,
        expected_version: request.version,
      });
      return true;
    });
    if (ok) navigate(`/requests/${id}`, { replace: true });
  };

  return (
    <Screen
      title={c.title}
      back={back}
      actions={
        <BottomActions>
          <ActionButton
            kind="d"
            loading={runner.isRunning('request')}
            disabled={runner.busy}
            onClick={() => void handleSubmit()}
          >
            {isAccepted ? c.submitRequest : c.submitNow}
          </ActionButton>
        </BottomActions>
      }
    >
      <SceneBanner name="status-cancel" height={130} />
      <PageTitle subtitle={[requestEquipmentFullName(request), request.location.name].filter(Boolean).join(' · ')}>
        {c.heading}
      </PageTitle>
      <ChoiceGroup label={c.optionsLabel}>
        <ChoiceCard
          title={c.cancelRequest}
          subtitle={c.cancelRequestHint}
          selected={effectiveTarget === 'cancel_request'}
          onSelect={() => setTarget('cancel_request')}
        />
        {canChangeProvider && (
          <ChoiceCard
            title={c.changeProvider}
            subtitle={c.changeProviderHint}
            selected={effectiveTarget === 'change_provider'}
            onSelect={() => setTarget('change_provider')}
          />
        )}
      </ChoiceGroup>
      {!canChangeProvider && request.status === 'action_required' && (
        <List>
          <ListRow title={strings.requests.card.findOther} action="accent" to={`/requests/${id}/publish`} />
        </List>
      )}
      <TextField
        label={c.reasonLabel}
        value={reason}
        placeholder={c.reasonPlaceholder}
        maxLength={1000}
        onChange={setReason}
      />
      <Banner tone="y" title={isAccepted ? c.acceptedTitle : c.notAcceptedTitle}>
        {isAccepted ? c.acceptedText : c.notAcceptedText}
      </Banner>
      <div className="ui-pad">
        <ActionFeedback feedback={runner.feedback} />
      </div>
    </Screen>
  );
}
