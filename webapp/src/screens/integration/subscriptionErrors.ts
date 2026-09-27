import { strings } from '../../strings/ru';
import { ApiError } from '../../api/errors';
import { actionErrorMessage } from '../../components/actions/actionErrors';

export function subscriptionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'NO_ACTIVE_API_KEY') return strings.integration.noActiveKeyError;
    if (error.status === 422 && error.details?.field === 'client_id') {
      return strings.integration.chooseKeyError;
    }
  }
  return actionErrorMessage(error, strings.common.unknownError);
}

export function isAlreadyToggled(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === 'SUBSCRIPTION_ACTIVE' || error.code === 'SUBSCRIPTION_DISABLED')
  );
}
