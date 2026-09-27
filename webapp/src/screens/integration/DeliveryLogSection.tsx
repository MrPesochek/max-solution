import { useState } from 'react';
import { strings } from '../../strings/ru';
import { useDeliveries, useRedeliver } from '../../api/hooks/useIntegration';
import type { Delivery, DeliveryState } from '../../api/types';
import { actionErrorMessage } from '../../components/actions/actionErrors';
import { Skeleton } from '../../components/states/Skeleton';
import { ErrorState } from '../../components/states/ErrorState';
import { EmptyState } from '../../components/states/EmptyState';
import { Screen } from '../../ui/layout/Screen';
import { ActionButton } from '../../ui/layout/ActionButton';
import { Note, type Tone } from '../../ui/blocks/Blocks';
import { List, ListRow } from '../../ui/List';
import { Sheet } from '../../ui/Sheet';
import { shortDateTime } from '../../ui/format';
import { needsRedelivery } from './delivery';

const STATE_TONE: Record<DeliveryState, Tone> = {
  queued: 'w',
  delivered: 'ok',
  retrying: 'y',
  failed: 'x',
  blocked: 'x',
};

function stateTag(delivery: Delivery): { label: string; tone: Tone } {
  if (delivery.in_flight) return { label: strings.integration.deliveryInFlightTag, tone: 'a' };
  const label =
    delivery.state === 'retrying'
      ? `${delivery.state} · ${delivery.attempt_count}`
      : delivery.state;
  return { label, tone: STATE_TONE[delivery.state] };
}

export function DeliveryLogSection() {
  const deliveries = useDeliveries();
  const redeliver = useRedeliver();
  const [selected, setSelected] = useState<Delivery | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRedeliver = async (delivery: Delivery) => {
    setError(null);
    try {
      await redeliver.mutateAsync(delivery.id);
      setSelected(null);
    } catch (e) {
      setError(actionErrorMessage(e, strings.integration.redeliverError));
    }
  };

  const items = deliveries.data?.items ?? [];

  return (
    <Screen title={strings.integration.logRow} back="/integration">
      {deliveries.isPending && <Skeleton lines={3} />}
      {deliveries.isError && (
        <ErrorState error={deliveries.error} onRetry={() => void deliveries.refetch()} />
      )}
      {deliveries.isSuccess && items.length === 0 && (
        <EmptyState title={strings.integration.deliveriesEmpty} />
      )}

      {items.length > 0 && (
        <List>
          {items.map((delivery) => (
            <ListRow
              key={delivery.id}
              title={delivery.event_type}
              subtitle={strings.integration.deliverySubtitle(
                shortDateTime(delivery.last_attempt_at ?? delivery.created_at),
                delivery.last_http_status ?? null,
              )}
              tag={stateTag(delivery)}
              chevron
              aria-label={`${delivery.event_type}: ${strings.integration.deliveryState[delivery.state]}`}
              onClick={() => {
                setError(null);
                setSelected(delivery);
              }}
            />
          ))}
        </List>
      )}
      {error && !selected && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      <Sheet
        open={selected !== null}
        title={selected?.event_type}
        description={selected ? strings.integration.deliveryState[selected.state] : undefined}
        onClose={() => setSelected(null)}
        locked={redeliver.isPending}
        actions={
          selected && (
            <>
              {needsRedelivery(selected) && (
                <ActionButton
                  loading={redeliver.isPending}
                  onClick={() => void handleRedeliver(selected)}
                >
                  {strings.integration.redeliver}
                </ActionButton>
              )}
              <ActionButton
                kind="s"
                disabled={redeliver.isPending}
                onClick={() => setSelected(null)}
              >
                {strings.common.close}
              </ActionButton>
            </>
          )
        }
      >
        {selected && (
          <>
            <List>
              <ListRow
                title={strings.integration.deliveryAttempts}
                value={String(selected.attempt_count)}
              />
              {selected.last_http_status && (
                <ListRow
                  title={strings.integration.deliveryLastStatus}
                  value={String(selected.last_http_status)}
                />
              )}
              {selected.last_attempt_at && (
                <ListRow
                  title={strings.integration.deliveryLastAttempt}
                  value={shortDateTime(selected.last_attempt_at)}
                />
              )}
              {selected.next_attempt_at && (
                <ListRow
                  title={strings.integration.deliveryNextAttempt}
                  value={shortDateTime(selected.next_attempt_at)}
                />
              )}
              <ListRow
                title={strings.integration.deliveryId}
                value={selected.delivery_id}
                valueTone="secondary"
              />
            </List>
            {selected.last_error && <Note tone="error">{selected.last_error}</Note>}
            {error && (
              <Note tone="error" role="alert">
                {error}
              </Note>
            )}
          </>
        )}
      </Sheet>
    </Screen>
  );
}
