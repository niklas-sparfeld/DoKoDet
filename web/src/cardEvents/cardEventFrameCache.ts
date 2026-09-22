const MAX_CACHED_FRAMES = 64;

type CacheEntry = {
  objectUrl: string;
};

const frameCache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<string>>();

/** Test helper: drop cached frames and in-flight loads. */
export function resetReviewFrameCacheForTests(): void {
  for (const entry of frameCache.values()) {
    if (entry.objectUrl.startsWith("blob:")) {
      URL.revokeObjectURL(entry.objectUrl);
    }
  }
  frameCache.clear();
  inflight.clear();
}

export function peekCachedReviewFrame(url: string): string | null {
  const entry = frameCache.get(url);
  if (entry === undefined) return null;
  // Refresh LRU order.
  frameCache.delete(url);
  frameCache.set(url, entry);
  return entry.objectUrl;
}

export async function loadCachedReviewFrame(
  url: string,
  signal?: AbortSignal,
): Promise<string> {
  const cached = peekCachedReviewFrame(url);
  if (cached !== null) return cached;

  if (signal?.aborted) {
    throw abortError();
  }

  let pending = inflight.get(url);
  if (pending === undefined) {
    // Do not attach the caller's AbortSignal to the shared fetch. Aborting a
    // superseded UI request must not poison later waiters for the same URL.
    pending = (async () => {
      const response = await fetch(url);
      if (!response.ok) {
        throw new ReviewFrameUnavailableError(response.status);
      }
      const blob = await response.blob();
      const objectUrl =
        typeof URL.createObjectURL === "function"
          ? URL.createObjectURL(blob)
          : url;
      rememberFrame(url, objectUrl);
      return objectUrl;
    })();
    inflight.set(url, pending);
    void pending.finally(() => {
      if (inflight.get(url) === pending) inflight.delete(url);
    });
  }

  if (signal === undefined) {
    return pending;
  }

  return raceWithAbort(pending, signal);
}

export function isAbortError(reason: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" &&
      reason instanceof DOMException &&
      reason.name === "AbortError") ||
    (reason instanceof Error && reason.name === "AbortError") ||
    (reason instanceof Error && /aborted/i.test(reason.message))
  );
}

export class ReviewFrameUnavailableError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`CardEvent review frame unavailable (${status}).`);
    this.name = "ReviewFrameUnavailableError";
    this.status = status;
  }
}

function raceWithAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }

    const onAbort = () => {
      cleanup();
      reject(abortError());
    };
    const cleanup = () => {
      signal.removeEventListener("abort", onAbort);
    };

    signal.addEventListener("abort", onAbort);
    promise.then(
      (value) => {
        cleanup();
        if (signal.aborted) {
          reject(abortError());
          return;
        }
        resolve(value);
      },
      (error: unknown) => {
        cleanup();
        reject(error);
      },
    );
  });
}

function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

function rememberFrame(url: string, objectUrl: string): void {
  const existing = frameCache.get(url);
  if (existing !== undefined) {
    frameCache.delete(url);
    frameCache.set(url, existing);
    if (existing.objectUrl !== objectUrl && objectUrl.startsWith("blob:")) {
      URL.revokeObjectURL(objectUrl);
    }
    return;
  }
  while (frameCache.size >= MAX_CACHED_FRAMES) {
    const oldest = frameCache.keys().next().value;
    if (oldest === undefined) break;
    const entry = frameCache.get(oldest);
    frameCache.delete(oldest);
    if (entry !== undefined && entry.objectUrl.startsWith("blob:")) {
      URL.revokeObjectURL(entry.objectUrl);
    }
  }
  frameCache.set(url, { objectUrl });
}
