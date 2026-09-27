import { useState } from 'react';
import { strings } from '../../strings/ru';
import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
  useRotateApiKey,
} from '../../api/hooks/useIntegration';
import {
  INTEGRATION_SCOPES,
  type ApiKey,
  type ApiKeyIssued,
  type IntegrationScope,
} from '../../api/types';
import { ApiError } from '../../api/errors';
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
import { Segmented } from '../../ui/Segmented';
import { UnsavedInputGuard } from '../../ui/layout/unsavedGuard';
import { useSubView } from '../../ui/layout/subView';
import './integration.css';
import { shortDateTime } from '../../ui/format';
import { IssuedSecretScreen } from './IssuedSecretScreen';
import { KeyWarnings } from './KeyWarnings';

const SUB_VIEWS = ['create'] as const;
type KeyKind = 'requests' | 'bindings';

const KIND_SCOPES: Record<KeyKind, IntegrationScope[]> = {
  requests: INTEGRATION_SCOPES.filter((scope) => !scope.startsWith('service_bindings')),
  bindings: INTEGRATION_SCOPES.filter((scope) => scope.startsWith('service_bindings')),
};

function scopeGroups(scopes: IntegrationScope[]): string {
  const groups = Array.from(new Set(scopes.map((scope) => scope.split(':')[0]!)));
  const text = groups.map((group) => strings.integration.scopeGroup[group] ?? group).join(', ');
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '—';
}

export function ApiKeysSection() {
  const apiKeys = useApiKeys(true);
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const rotateKey = useRotateApiKey();
  const { confirm, dialog } = useConfirm();

  const [view, setView] = useSubView(SUB_VIEWS);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<KeyKind>('requests');
  const [scopes, setScopes] = useState<IntegrationScope[]>([]);
  const [issued, setIssued] = useState<ApiKeyIssued | null>(null);
  const [selected, setSelected] = useState<ApiKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggleScope = (scope: IntegrationScope, checked: boolean) =>
    setScopes((prev) => (checked ? [...prev, scope] : prev.filter((s) => s !== scope)));

  const handleCreate = async () => {
    setError(null);
    if (!name.trim() || scopes.length === 0) return;
    try {
      const result = await createKey.mutateAsync({ name: name.trim(), scopes });
      setIssued(result);
      setView('main');
      setName('');
      setScopes([]);
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === 'SCOPE_CONFLICT'
          ? strings.integration.scopeConflictError
          : actionErrorMessage(e, strings.common.unknownError),
      );
    }
  };

  const handleRotate = async (key: ApiKey) => {
    setSelected(null);
    if (
      !(await confirm({
        title: strings.integration.keyRotateConfirm,
        confirmLabel: strings.integration.keyRotate,
      }))
    )
      return;
    setError(null);
    try {
      setIssued(await rotateKey.mutateAsync(key.id));
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  const handleRevoke = async (key: ApiKey) => {
    setSelected(null);
    if (
      !(await confirm({
        title: strings.integration.keyRevokeConfirm,
        confirmLabel: strings.integration.keyRevoke,
        destructive: true,
      }))
    )
      return;
    setError(null);
    try {
      await revokeKey.mutateAsync(key.id);
    } catch (e) {
      setError(actionErrorMessage(e, strings.common.unknownError));
    }
  };

  if (issued) {
    const bindings = issued.scopes.some((scope) => scope.startsWith('service_bindings'));
    return (
      <IssuedSecretScreen
        id="issued-key"
        title={strings.integration.issuedTitle}
        onceTitle={strings.integration.keyCreatedOnce}
        onceText={strings.integration.keyShownOnce}
        label={issued.name}
        value={issued.key}
        copyLabel={strings.integration.copyKey}
        onClose={() => setIssued(null)}
      >
        <List>
          <ListRow title={strings.integration.keyRights} value={scopeGroups(issued.scopes)} />
          <ListRow
            title={strings.integration.keyPrefix}
            value={
              <span className="int-code">{strings.integration.keyMask(issued.key_prefix)}</span>
            }
          />
          <ListRow
            title={strings.integration.keyBindingsRight}
            value={bindings ? strings.common.yes : strings.common.no}
          />
        </List>
      </IssuedSecretScreen>
    );
  }

  if (view === 'create') {
    return (
      <UnsavedInputGuard>
        <Screen
          title={strings.integration.createKey}
          back={() => setView('main')}
          actions={
            <BottomActions>
              <ActionButton
                loading={createKey.isPending}
                disabled={!name.trim() || scopes.length === 0}
                onClick={() => void handleCreate()}
              >
                {strings.integration.createKey}
              </ActionButton>
            </BottomActions>
          }
        >
          <TextField
            id="api-key-name"
            label={strings.integration.keyNameLabel}
            placeholder={strings.integration.keyNamePlaceholder}
            value={name}
            onChange={setName}
          />
          <Segmented<KeyKind>
            label={strings.integration.keyKindLabel}
            items={[
              { id: 'requests', label: strings.integration.keyKindRequests },
              { id: 'bindings', label: strings.integration.keyKindBindings },
            ]}
            value={kind}
            onChange={(next) => {
              setKind(next);
              setScopes((prev) => prev.filter((scope) => KIND_SCOPES[next].includes(scope)));
            }}
          />
          <Note>
            {kind === 'requests'
              ? strings.integration.keyKindRequestsHint
              : strings.integration.keyKindBindingsHint}
          </Note>
          <SectionCaption>{strings.integration.keyScopesLabel}</SectionCaption>
          <List role="group" aria-label={strings.integration.keyScopesLabel}>
            {KIND_SCOPES[kind].map((scope) => (
              <ListRow
                key={scope}
                title={strings.integration.scopeTitle[scope] ?? scope}
                subtitle={
                  <>
                    <span className="int-code">{scope}</span>
                    <br />
                    {strings.integration.scopeDescriptions[scope]}
                  </>
                }
                aria-label={scope}
                control={{ type: 'checkbox', checked: scopes.includes(scope) }}
                onToggle={(checked) => toggleScope(scope, checked)}
              />
            ))}
          </List>
          {error && (
            <Note tone="error" role="alert">
              {error}
            </Note>
          )}
        </Screen>
      </UnsavedInputGuard>
    );
  }

  return (
    <Screen title={strings.integration.apiKeysRow} back="/integration">
      {apiKeys.isPending && <Skeleton lines={4} />}
      {apiKeys.isError && (
        <ErrorState error={apiKeys.error} onRetry={() => void apiKeys.refetch()} />
      )}
      {apiKeys.isSuccess && apiKeys.data.length === 0 && (
        <EmptyState title={strings.integration.apiKeysEmpty} />
      )}

      {apiKeys.isSuccess && (
        <List>
          {apiKeys.data.map((key) => (
            <ListRow
              key={key.id}
              title={key.name}
              subtitle={[
                strings.integration.keyMask(key.key_prefix),
                key.last_used_at
                  ? `${strings.integration.keyLastUsed}: ${shortDateTime(key.last_used_at)}`
                  : `${strings.integration.keyCreatedAt}: ${shortDateTime(key.created_at)}`,
              ].join(' · ')}
              tag={{
                label: strings.integration.keyStatus[key.status],
                tone: key.status === 'active' ? 'ok' : 'w',
              }}
              chevron={key.status === 'active'}
              onClick={key.status === 'active' ? () => setSelected(key) : undefined}
            />
          ))}
          <ListRow
            title={strings.integration.createKey}
            action="accent"
            onClick={() => {
              setError(null);
              setView('create');
            }}
          />
        </List>
      )}
      {error && (
        <Note tone="error" role="alert">
          {error}
        </Note>
      )}

      <Sheet
        open={selected !== null}
        title={selected?.name}
        description={selected ? strings.integration.keyMask(selected.key_prefix) : undefined}
        onClose={() => setSelected(null)}
        actions={
          selected && (
            <>
              <ActionButton
                kind="s"
                loading={rotateKey.isPending}
                onClick={() => void handleRotate(selected)}
              >
                {strings.integration.keyRotate}
              </ActionButton>
              <ActionButton
                kind="d"
                loading={revokeKey.isPending}
                onClick={() => void handleRevoke(selected)}
              >
                {strings.integration.keyRevoke}
              </ActionButton>
            </>
          )
        }
      >
        {selected && (
          <>
            <KeyWarnings apiKey={selected} />
            <List>
              <ListRow title={strings.integration.keyRights} value={scopeGroups(selected.scopes)} />
              <ListRow
                title={strings.integration.keyCreatedAt}
                value={shortDateTime(selected.created_at)}
              />
            </List>
            <Note>{strings.integration.scopesImmutableNote}</Note>
          </>
        )}
      </Sheet>
      {dialog}
    </Screen>
  );
}
