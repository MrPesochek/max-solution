import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useIdempotentMutation } from '../idempotency';
import { api, apiPath } from '../client';
import { getActiveScope } from '../orgStore';
import { queryKeys } from '../queryKeys';
import type {
  ApiKey,
  ApiKeyCreateInput,
  ApiKeyIssued,
  Delivery,
  DeliveryPage,
  IntegrationSummary,
  WebhookSubscription,
  WebhookSubscriptionCreateInput,
  WebhookSubscriptionIssued,
} from '../types';

export function useApiKeys(allowed: boolean) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.apiKeys(scope),
    queryFn: () => api.get<ApiKey[]>('/integration/api-keys'),
    enabled: Boolean(scope) && allowed,
  });
}

function withOneTimeSecret<T extends { mutateAsync: (...args: never[]) => Promise<unknown>; reset: () => void }>(
  mutation: T,
): T {
  const { mutateAsync, reset } = mutation;
  return {
    ...mutation,
    mutateAsync: (async (...args: Parameters<T['mutateAsync']>) => {
      const result = await mutateAsync(...args);
      reset();
      return result;
    }) as T['mutateAsync'],
  };
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  const mutation = useIdempotentMutation({
    mutationFn: (input: ApiKeyCreateInput, idempotencyKey) =>
      api.post<ApiKeyIssued>('/integration/api-keys', input, { idempotencyKey }),
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(scope) });
    },
  });
  return withOneTimeSecret(mutation);
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (clientId: string, idempotencyKey) =>
      api.post<ApiKey>(apiPath`/integration/api-keys/${clientId}/revoke`, undefined, { idempotencyKey }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(scope) });
    },
  });
}

export function useRotateApiKey() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  const mutation = useIdempotentMutation({
    mutationFn: (clientId: string, idempotencyKey) =>
      api.post<ApiKeyIssued>(apiPath`/integration/api-keys/${clientId}/rotate`, undefined, {
        idempotencyKey,
      }),
    gcTime: 0,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(scope) });
    },
  });
  return withOneTimeSecret(mutation);
}

export function useWebhookSubscriptions() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.webhookSubscriptions(scope),
    queryFn: () => api.get<WebhookSubscription[]>('/integration/webhook-subscriptions'),
    enabled: Boolean(scope),
  });
}

export function useDeliveries() {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.deliveries(scope),
    queryFn: () => api.get<DeliveryPage>('/integration/deliveries'),
    enabled: Boolean(scope),
  });
}

export function useRedeliver() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return useIdempotentMutation({
    mutationFn: (deliveryId: string, idempotencyKey) =>
      api.post<Delivery>(apiPath`/integration/deliveries/${deliveryId}/redeliver`, undefined, {
        idempotencyKey,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.deliveries(scope) });
    },
  });
}

export function useIntegrationSummary(allowed: boolean) {
  const scope = getActiveScope();
  return useQuery({
    queryKey: queryKeys.integrationSummary(scope),
    queryFn: () => api.get<IntegrationSummary>('/integration/summary'),
    enabled: Boolean(scope) && allowed,
  });
}

function useInvalidateIntegration() {
  const queryClient = useQueryClient();
  const scope = getActiveScope();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.webhookSubscriptions(scope) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.integrationSummary(scope) });
  };
}

export function useCreateWebhookSubscription() {
  const invalidate = useInvalidateIntegration();
  const mutation = useIdempotentMutation({
    mutationFn: (input: WebhookSubscriptionCreateInput, idempotencyKey) =>
      api.post<WebhookSubscriptionIssued>('/integration/webhook-subscriptions', input, {
        idempotencyKey,
      }),
    gcTime: 0,
    onSuccess: invalidate,
  });
  return withOneTimeSecret(mutation);
}

export function useToggleWebhookSubscription() {
  const invalidate = useInvalidateIntegration();
  return useIdempotentMutation({
    mutationFn: (input: { subscriptionId: string; enabled: boolean }, idempotencyKey) =>
      api.post<WebhookSubscription>(
        apiPath`/integration/webhook-subscriptions/${input.subscriptionId}/${input.enabled ? 'enable' : 'disable'}`,
        undefined,
        { idempotencyKey },
      ),
    onSuccess: invalidate,
  });
}

export function useRotateWebhookSecret() {
  const invalidate = useInvalidateIntegration();
  const mutation = useIdempotentMutation({
    mutationFn: (subscriptionId: string, idempotencyKey) =>
      api.post<WebhookSubscriptionIssued>(
        apiPath`/integration/webhook-subscriptions/${subscriptionId}/rotate-secret`,
        undefined,
        { idempotencyKey },
      ),
    gcTime: 0,
    onSuccess: invalidate,
  });
  return withOneTimeSecret(mutation);
}
