import { ApiError } from '../../api/errors';

export function isInvalidInvitationError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 400 || error.status === 422);
}
