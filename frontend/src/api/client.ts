// The ONE place the frontend touches the network. ESLint (no-restricted-globals / no-restricted-syntax)
// and tests/test_architecture.py both fail if `fetch` appears anywhere outside src/api/.

export class ApiError extends Error {
  readonly status: number;
  /** Set when the backend answers 501 for a pipeline stage that isn't built yet. */
  readonly milestone?: string;

  constructor(status: number, message: string, milestone?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.milestone = milestone;
  }

  get notBuilt(): boolean {
    return this.status === 501;
  }
}

/** Network failure (backend not running), as opposed to an HTTP error answer. */
export class OfflineError extends Error {
  constructor(cause: unknown) {
    super(`API unreachable: ${String(cause)}`);
    this.name = 'OfflineError';
  }
}

interface ErrorBody {
  detail?: unknown;
  milestone?: string;
}

async function parseError(r: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await r.json()) as ErrorBody;
  } catch {
    // non-JSON error body
  }
  const detail = typeof body.detail === 'string' ? body.detail : r.statusText || `HTTP ${r.status}`;
  return new ApiError(r.status, detail, body.milestone);
}

export async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  let r: Response;
  try {
    r = await fetch(path, {
      ...rest,
      headers: { Accept: 'application/json', ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...rest.headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch (e) {
    throw new OfflineError(e);
  }
  // Behind a proxy (Vite dev server, nginx), an unreachable backend shows up as a gateway error.
  if (r.status === 502 || r.status === 504) throw new OfflineError(`gateway ${r.status}`);
  if (!r.ok) throw await parseError(r);
  return (await r.json()) as T;
}

/** Static asset shipped with the app (public/), e.g. the offline sample site. */
export async function staticJson<T>(file: string): Promise<T> {
  return request<T>(`${import.meta.env.BASE_URL}${file}`);
}
