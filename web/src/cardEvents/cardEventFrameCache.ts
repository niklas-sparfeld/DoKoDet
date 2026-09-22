const MAX_CACHED_FRAMES = 64;

type CacheEntry = {
  objectUrl: string;
};

const frameCache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<string>>();

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

  const pending = inflight.get(url);
  if (pending !== undefined) {
    return pending;
  }

  const request = (async () => {
    const response = await fetch(url, { signal });
    if (!response.ok) {
      throw new ReviewFrameUnavailableError(response.status);
    }
    const blob = await response.blob();
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }
    const objectUrl =
      typeof URL.createObjectURL === "function"
        ? URL.createObjectURL(blob)
        : url;
    rememberFrame(url, objectUrl);
    return objectUrl;
  })();

  inflight.set(url, request);
  try {
    return await request;
  } finally {
    if (inflight.get(url) === request) inflight.delete(url);
  }
}

export class ReviewFrameUnavailableError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`CardEvent review frame unavailable (${status}).`);
    this.name = "ReviewFrameUnavailableError";
    this.status = status;
  }
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
