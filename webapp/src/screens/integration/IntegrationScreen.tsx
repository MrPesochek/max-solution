import { useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { strings } from '../../strings/ru';
import { useSession } from '../../session/SessionContext';
import { canAccessIntegration } from '../../lib/roles';
import {
  useApiKeys,
  useDeliveries,
  useIntegrationSummary,
  useRedeliver,
  useToggleWebhookSubscription,
  useWebhookSubscriptions,
} from '../../api/hooks/useIntegration';
import type { Delivery } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { useConfirm } from '../../components/useConfirm';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { NoAccessState } from '../../components/states/NoAccessState';
import { Screen } from '../../ui/layout/Screen';
import { Banner, Note, PageTitle, SectionCaption, TextCard } from '../../ui/blocks/Blocks';
import { KeyValueRows } from '../../ui/KeyValueRows';
import { SceneBanner } from '../../ui/SceneBanner';
import { List, ListRow } from '../../ui/List';
import { relativeDay, shortDateTime } from '../../ui/format';
import './integration.css';
import { ApiKeysSection } from './ApiKeysSection';
import { DeliveryLogSection } from './DeliveryLogSection';
import { needsRedelivery } from './delivery';
import { KeyWarnings } from './KeyWarnings';
import { isAlreadyToggled } from './subscriptionErrors';
import { WebhooksSection } from './WebhooksSection';

type Section = 'keys' | 'webhooks' | 'log' | 'help';
const SECTIONS = new Set<string>(['keys', 'webhooks', 'log', 'help']);

export function IntegrationScreen() {
  const { section } = useParams<{ section?: string }>();
  const { activeMembership } = useSession();

  if (!activeMembership) return null;
  if (!canAccessIntegration(activeMembership.role)) {
    return (
      <Screen title={strings.integration.title}>
        <NoAccessState />
      </Screen>
    );
  }
  if (section && !SECTIONS.has(section)) return <Navigate to="/integration" replace />;

  switch (section as Section | undefined) {
    case 'keys':
      return <ApiKeysSection />;
    case 'webhooks':
      return <WebhooksSection />;
    case 'log':
      return <DeliveryLogSection />;
    case 'help':
      return <HelpSection />;
    default:
      return <IntegrationOverview />;
  }
}

function lastProblem(items: Delivery[]): Delivery | undefined {
  return [...items]
    .filter((d) => needsRedelivery(d) || d.state === 'retrying')
    .sort((a, b) =>
      (b.last_attempt_at ?? b.created_at).localeCompare(a.last_attempt_at ?? a.created_at),
    )[0];
}

function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '');
}

function IntegrationOverview() {
  const summary = useIntegrationSummary(true);
  const apiKeys = useApiKeys(true);
  const subscriptions = useWebhookSubscriptions();
  const deliveries = useDeliveries();
  const redeliver = useRedeliver();
  const toggle = useToggleWebhookSubscription();
  const { confirm, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [redelivering, setRedelivering] = useState(false);
  const [switching, setSwitching] = useState(false);
  const t = strings.integration;

  const queries = [summary, apiKeys, subscriptions, deliveries] as const;
  if (queries.some((q) => q.isPending)) {
    return (
      <Screen title={t.title}>
        <Skeleton lines={4} />
      </Screen>
    );
  }
  const failed = queries.find((q) => q.isError);
  if (failed) {
    return (
      <Screen title={t.title}>
        <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />
      </Screen>
    );
  }

  const info = summary.data!;
  const items = deliveries.data!.items;
  const broken = items.filter(needsRedelivery);
  const problem = lastProblem(items);
  const activeKeys = apiKeys.data!.filter((key) => key.status === 'active');
  const activeHooks = subscriptions.data!.filter((sub) => sub.status === 'active');
  const disabledHooks = subscriptions.data!.filter((sub) => sub.status !== 'active');
  const { connected, webhook, last_event_at: lastEvent } = info;
  const day = info.deliveries_24h;

  const redeliverAll = async () => {
    setError(null);
    setRedelivering(true);
    try {
      for (const delivery of broken) await redeliver.mutateAsync(delivery.id);
    } catch (e) {
      setError(actionErrorMessage(e, t.redeliverError));
    } finally {
      setRedelivering(false);
    }
  };

  const switchDelivery = async (enabled: boolean) => {
    if (
      !enabled &&
      !(await confirm({
        title: t.disableIntegrationConfirm,
        confirmLabel: t.disableConfirmLabel,
        destructive: true,
      }))
    )
      return;
    setError(null);
    setSwitching(true);
    try {
      for (const sub of enabled ? disabledHooks : activeHooks) {
        try {
          await toggle.mutateAsync({ subscriptionId: sub.id, enabled });
        } catch (e) {
          if (!isAlreadyToggled(e)) throw e;
        }
      }
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    } finally {
      setSwitching(false);
      void summary.refetch();
      void subscriptions.refetch();
    }
  };

  return (
    <Screen title={t.title}>
      <SceneBanner name={connected ? 'crm-sync' : 'crm-wires'} height={130} width={163} />
      <PageTitle
        subtitle={
          lastEvent ? t.lastEvent(relativeDay(lastEvent)) : connected ? undefined : t.onlyMaxText
        }
      >
        {connected ? t.crmConnected : t.crmNotConnected}
      </PageTitle>

      {broken.length > 0 && (
        <Banner tone="x" role="alert" title={t.errorsBannerTitle}>
          {t.errorsBannerText(
            broken.length,
            shortDateTime(broken.map((d) => d.created_at).sort()[0]),
            problem?.last_http_status ?? null,
          )}
        </Banner>
      )}

      <KeyValueRows
        rows={[
          {
            id: 'webhook',
            label: t.webhookRow,
            value: !webhook
              ? t.webhookNone
              : webhook.status === 'active'
                ? shortUrl(webhook.url)
                : t.webhookDisabledValue(shortUrl(webhook.url)),
            mono: Boolean(webhook),
          },
          {
            id: 'events',
            label: t.eventsDayRow,
            value: t.eventsDayValue(day.total, day.failed),
            tone: day.failed > 0 ? 'error' : undefined,
          },
          {
            id: 'key',
            label: t.apiKeyRow,
            value: activeKeys[0] ? t.keyMask(activeKeys[0].key_prefix) : t.keyNone,
            mono: Boolean(activeKeys[0]),
          },
        ]}
      />

      {activeKeys.map((key) => (
        <section
          key={key.id}
          aria-label={t.keyScopesTitle(activeKeys.length > 1 ? key.name : null)}
        >
          <SectionCaption>
            {t.keyScopesTitle(activeKeys.length > 1 ? key.name : null)}
          </SectionCaption>
          <KeyWarnings apiKey={key} />
          <List>
            {key.scopes.map((scope) => (
              <ListRow
                key={scope}
                title={t.scopeTitle[scope] ?? scope}
                subtitle={<span className="int-code">{scope}</span>}
              />
            ))}
          </List>
        </section>
      ))}
      {activeKeys.length > 0 && <Note>{t.scopesImmutableNote}</Note>}

      <List>
        <ListRow
          title={t.apiKeysRow}
          value={String(info.api_keys_active)}
          to="/integration/keys"
          chevron
        />
        <ListRow
          title={t.webhooksRow}
          value={String(activeHooks.length)}
          to="/integration/webhooks"
          chevron
        />
        <ListRow title={t.logRow} to="/integration/log" chevron />
        <ListRow title={t.helpTitle} to="/integration/help" chevron />
      </List>

      <List>
        {broken.length > 0 && (
          <ListRow
            title={t.redeliver}
            action="accent"
            loading={redelivering}
            onClick={() => void redeliverAll()}
          />
        )}
        {activeHooks.length > 0 ? (
          <ListRow
            title={t.disableIntegration}
            action="danger"
            loading={switching}
            onClick={() => void switchDelivery(false)}
          />
        ) : disabledHooks.length > 0 ? (
          <ListRow
            title={t.enableIntegration}
            action="accent"
            loading={switching}
            onClick={() => void switchDelivery(true)}
          />
        ) : (
          <ListRow title={t.connectCrm} action="accent" to="/integration/webhooks?view=create" />
        )}
      </List>
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}
      {dialog}
    </Screen>
  );
}

function HelpSection() {
  return (
    <Screen title={strings.integration.helpTitle} back="/integration">
      <TextCard>{strings.integration.helpSignature}</TextCard>
      <TextCard>{strings.integration.helpIdempotency}</TextCard>
      <TextCard>{strings.integration.helpRecovery}</TextCard>
    </Screen>
  );
}
