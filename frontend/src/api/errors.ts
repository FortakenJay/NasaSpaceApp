import { ApiError, OfflineError } from './client';

/** Human message for any error a hook returns. */
export function describeError(error: unknown, what: string): string {
  if (error instanceof ApiError && error.notBuilt) return `${what} is not built yet (milestone ${error.milestone ?? '?'}).`;
  if (error instanceof ApiError) return `${what} failed: ${error.message}`;
  if (error instanceof OfflineError) return `${what} needs the API (python -m marswalk serve).`;
  return `${what} failed: ${String(error)}`;
}
