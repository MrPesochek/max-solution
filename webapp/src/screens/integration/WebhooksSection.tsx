import { useState } from 'react';
import { strings } from '../../strings/ru';
import {
  useApiKeys,
  useCreateWebhookSubscription,
  useRotateWebhookSecret,
  useToggleWebhookSubscription,
  useWebhookSubscriptions,
} from '../../api/hooks/useIntegration';
import type { WebhookSubscription, WebhookSubscriptionIssued } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { useConfirm } from '../../components/useConfirm';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { BottomActions, Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, SectionCaption } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { TextField } from '../../ui/FormField';
import { UnsavedInputGuard } from '../../ui/layout/unsavedGuard';
import { useSubView } from '../../ui/layout/subView';
import { IssuedSecretScreen } from './IssuedSecretScreen';
import { isAlreadyToggled, subscriptionErrorMessage } from './subscriptionErrors';
import './integration.css';

const SUB_VIEWS = ['create'] as const;

export function WebhooksSection() {
  const subscriptions = useWebhookSubscriptions();
  const apiKeys = useApiKeys(true);
  const create = useCreateWebhookSubscription();
  const toggle = useToggleWebhookSubscription();
  const rotate = useRotateWebhookSecret();
  const { confirm, dialog } = useConfirm();
  const t = strings.integration;

  const [view, setView] = useSubView(SUB_VIEWS);
  const creating = view === 'create';
  const [url, setUrl] = useState('');
  const [clientId, setClientId] = useState<string | null>(null);
  const [issued, setIssued] = useState<WebhookSubscriptionIssued | null>(null);
  const [selected, setSelected] = useState<WebhookSubscription | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeKeys = (apiKeys.data ?? []).filter((key) => key.status === 'active');
  const chooseKey = activeKeys.length > 1;

  const handleCreate = async () => {
    setError(null);
    try {
      const result = await create.mutateAsync({
        url: url.trim(),
        client_id: chooseKey ? clientId : undefined,
      });
      setIssued(result);
      setView('main');
      setUrl('');
      setClientId(null);
    } catch (e) {
      setError(subscriptionErrorMessage(e));
    }
  };

  const handleToggle = async (sub: WebhookSubscription) => {
    setSelected(null);
    setError(null);
    const enabled = sub.status !== 'active';
    try {
      await toggle.mutateAsync({ subscriptionId: sub.id, enabled });
    } catch (e) {
      if (isAlreadyToggled(e)) void subscriptions.refetch();
      else setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const handleRotate = async (sub: WebhookSubscription) => {
    setSelected(null);
    if (
      !(await confirm({ title: t.rotateSecretConfirm, confirmLabel: t.rotateSecretConfirmLabel }))
    )
      return;
    setError(null);
    try {
      setIssued(await rotate.mutateAsync(sub.id));
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const errorNote = error && (
    <Note tone="error" role="alert">
      {error}
    </Note>
  );

  if (issued) {
    return (
      <IssuedSecretScreen
        id="webhook-secret"
        title={t.secretTitle}
        onceTitle={t.secretOnceTitle}
        onceText={t.secretOnceText}
        label={issued.url}
        value={issued.secret}
        copyLabel={t.copySecret}
        onClose={() => setIssued(null)}
      />
    );
  }

  if (creating) {
    const valid = /^https:\/\/\S+$/.test(url.trim()) && (!chooseKey || Boolean(clientId));
    return (
      <UnsavedInputGuard>
        <Screen
          title={t.connectCrm}
          back={() => setView('main')}
          actions={
            <BottomActions>
              <ActionButton
                loading={create.isPending}
                disabled={!valid}
                onClick={() => void handleCreate()}
              >
                {t.connectCrm}
              </ActionButton>
            </BottomActions>
          }
        >
          <TextField
            id="webhook-url"
            type="url"
            inputMode="url"
            label={t.webhookUrlLabel}
            placeholder={t.webhookUrlPlaceholder}
            hint={t.webhookUrlHint}
            value={url}
            onChange={setUrl}
          />
          {apiKeys.isSuccess && activeKeys.length === 0 && (
            <List>
              <ListRow title={t.createKey} subtitle={t.webhookNeedsKey} to="/integration/keys" chevron />
            </List>
          )}
          {chooseKey && (
            <>
              <SectionCaption>{t.webhookKeyLabel}</SectionCaption>
              <List role="radiogroup" aria-label={t.webhookKeyLabel}>
                {activeKeys.map((key) => (
                  <ListRow
                    key={key.id}
                    title={key.name}
                    subtitle={<span className="int-code">{t.keyMask(key.key_prefix)}</span>}
                    control={{ type: 'radio', checked: clientId === key.id }}
                    onToggle={() => setClientId(key.id)}
                  />
                ))}
              </List>
              <Note>{t.webhookKeyHint}</Note>
            </>
          )}
          {errorNote}
        </Screen>
      </UnsavedInputGuard>
    );
  }

  return (
    <Screen title={t.webhooksRow} back="/integration">
      {subscriptions.isPending && <Skeleton lines={3} />}
      {subscriptions.isError && (
        <ErrorState error={subscriptions.error} onRetry={() => void subscriptions.refetch()} />
      )}
      {subscriptions.isSuccess && subscriptions.data.length === 0 && (
        <EmptyState title={t.subscriptionsEmpty} />
      )}
      {subscriptions.isSuccess && (
        <List>
          {subscriptions.data.map((sub) => (
            <ListRow
              key={sub.id}
              title={sub.url}
              subtitle={sub.events.join(', ') || strings.common.notSpecified}
              tag={{
                label: t.subscriptionStatus[sub.status],
                tone: sub.status === 'active' ? 'ok' : 'w',
              }}
              chevron
              onClick={() => setSelected(sub)}
            />
          ))}
          <ListRow
            title={t.connectCrm}
            action="accent"
            onClick={() => {
              setError(null);
              setView('create');
            }}
          />
        </List>
      )}
      {errorNote}

      <Sheet
        open={selected !== null}
        title={selected?.url}
        description={selected ? t.subscriptionStatus[selected.status] : undefined}
        onClose={() => setSelected(null)}
        actions={
          selected && (
            <>
              <ActionButton
                kind="s"
                loading={rotate.isPending}
                onClick={() => void handleRotate(selected)}
              >
                {t.rotateSecret}
              </ActionButton>
              <ActionButton
                kind={selected.status === 'active' ? 'd' : 's'}
                loading={toggle.isPending}
                onClick={() => void handleToggle(selected)}
              >
                {selected.status === 'active' ? t.subscriptionDisable : t.subscriptionEnable}
              </ActionButton>
            </>
          )
        }
      >
        {selected && (
          <List>
            <ListRow
              title={t.subscriptionEvents}
              value={selected.events.join(', ') || strings.common.notSpecified}
            />
          </List>
        )}
      </Sheet>
      {dialog}
    </Screen>
  );
}
