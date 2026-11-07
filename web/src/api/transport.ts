export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`DokoDetector API request failed with status ${status}.`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function requestJson<Response>(
  fetchImplementation: typeof fetch,
  path: string,
  init?: RequestInit,
  timeoutMs?: number,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const timeoutController =
    timeoutMs === undefined ? null : new AbortController();
  const callerSignal = init?.signal;
  const abortFromCaller = () => timeoutController?.abort(callerSignal?.reason);
  if (callerSignal?.aborted) {
    abortFromCaller();
  } else {
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }
  const timeoutHandle =
    timeoutController === null
      ? null
      : globalThis.setTimeout(() => timeoutController.abort(), timeoutMs);
  try {
    const response = await fetchImplementation(path, {
      ...init,
      headers,
      ...(timeoutController === null
        ? {}
        : { signal: timeoutController.signal }),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readResponseBody(response));
    }
    return (await response.json()) as Response;
  } catch (error) {
    if (timeoutController?.signal.aborted && !callerSignal?.aborted) {
      throw new ApiError(408, {
        message: `The request timed out after ${timeoutMs} ms.`,
      });
    }
    throw error;
  } finally {
    if (timeoutHandle !== null) globalThis.clearTimeout(timeoutHandle);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export function jsonHeaders(headers: HeadersInit | undefined): Headers {
  const result = new Headers(headers);
  result.set("Accept", "application/json");
  result.set("Content-Type", "application/json");
  return result;
}

export async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}
