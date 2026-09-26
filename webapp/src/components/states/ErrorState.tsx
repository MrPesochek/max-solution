import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { StatusHero } from '../../ui/StatusHero';
import { ActionButton } from '../../ui/layout/ActionButton';
import { botChatUrl } from '../../session/loginLink';

interface ErrorStateProps {
  message?: string;
  error?: unknown;
  onRetry?: () => void;
  top?: number;
}

export function ErrorState({ message, error, onRetry, top = 48 }: ErrorStateProps) {
  const offline = error instanceof ApiError && error.isNetworkError;
  const unavailable = error instanceof ApiError && error.isServiceUnavailable;
  const title = offline
    ? strings.states.offlineTitle
    : unavailable
      ? strings.states.unavailableTitle
      : strings.states.error;
  const botUrl = offline ? null : botChatUrl();
  const text = offline
    ? strings.states.offlineLoad
    : unavailable
      ? strings.errorCodes.SERVICE_UNAVAILABLE
      : message;
  return (
    <StatusHero
      icon="!"
      illustration={offline ? 'error-offline' : unavailable ? 'error-maintenance' : 'error-broken'}
      illustrationWidth={188}
      tone={offline ? 'n' : 'x'}
      title={title}
      top={top}
      role="alert"
      actions={
        onRetry || botUrl ? (
          <>
            {onRetry && (
              <ActionButton kind={botUrl ? 'p' : 's'} onClick={onRetry}>
                {strings.common.retry}
              </ActionButton>
            )}
            {botUrl && (
              <ActionButton kind="s" href={botUrl}>
                {strings.states.openBot}
              </ActionButton>
            )}
          </>
        ) : undefined
      }
    >
      {text}
    </StatusHero>
  );
}
