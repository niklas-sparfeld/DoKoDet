import { repositoryBundleVideoPath } from "../api/client";

/**
 * Buffer recordings up to this size into a blob URL for local nudge seeks.
 * Larger files keep the network URL (Range seeks).
 */
export const MAX_RECORDING_VIDEO_BLOB_BYTES = 2 * 1024 * 1024 * 1024;

type CacheEntry = {
  objectUrl: string;
};

const videoCache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<string>>();

/** Test helper: drop cached recording video object URLs. */
export function resetRecordingVideoCacheForTests(): void {
  for (const entry of videoCache.values()) {
    if (entry.objectUrl.startsWith("blob:")) {
      URL.revokeObjectURL(entry.objectUrl);
    }
  }
  videoCache.clear();
  inflight.clear();
}

/** Return a cached blob URL when the recording is already buffered in RAM. */
export function peekRecordingVideoUrl(recordingId: string): string | null {
  return videoCache.get(recordingId)?.objectUrl ?? null;
}

/**
 * Return a playable URL for the recording video.
 * Prefers a blob object URL in RAM when the file is small enough.
 */
export async function loadRecordingVideoUrl(
  recordingId: string,
  signal?: AbortSignal,
): Promise<string> {
  const networkUrl = repositoryBundleVideoPath(recordingId);
  const cached = videoCache.get(recordingId);
  if (cached !== undefined) return cached.objectUrl;

  if (signal?.aborted) {
    throw new DOMException("Aborted", "AbortError");
  }

  let pending = inflight.get(recordingId);
  if (pending === undefined) {
    pending = fetchRecordingVideoObjectUrl(recordingId, networkUrl);
    inflight.set(recordingId, pending);
    void pending.finally(() => {
      if (inflight.get(recordingId) === pending) inflight.delete(recordingId);
    });
  }

  if (signal === undefined) return pending;

  return raceWithAbort(pending, signal);
}

/** Warm the recording video cache without waiting for the caller. */
export function prefetchRecordingVideo(recordingId: string): void {
  void loadRecordingVideoUrl(recordingId).catch(() => undefined);
}

async function fetchRecordingVideoObjectUrl(
  recordingId: string,
  networkUrl: string,
): Promise<string> {
  const existing = videoCache.get(recordingId);
  if (existing !== undefined) return existing.objectUrl;

  const response = await fetch(networkUrl);
  if (!response.ok) {
    throw new Error(`Recording video unavailable (${response.status}).`);
  }

  const lengthHeader = response.headers.get("content-length");
  if (lengthHeader !== null) {
    const length = Number(lengthHeader);
    if (Number.isFinite(length) && length > MAX_RECORDING_VIDEO_BLOB_BYTES) {
      await response.body?.cancel().catch(() => undefined);
      return networkUrl;
    }
  }

  const blob = await response.blob();
  if (blob.size > MAX_RECORDING_VIDEO_BLOB_BYTES) {
    return networkUrl;
  }

  const objectUrl =
    typeof URL.createObjectURL === "function"
      ? URL.createObjectURL(blob)
      : networkUrl;
  if (objectUrl.startsWith("blob:")) {
    videoCache.set(recordingId, { objectUrl });
  }
  return objectUrl;
}

function raceWithAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      cleanup();
      reject(new DOMException("Aborted", "AbortError"));
    };
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    signal.addEventListener("abort", onAbort);
    promise.then(
      (value) => {
        cleanup();
        if (signal.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
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
