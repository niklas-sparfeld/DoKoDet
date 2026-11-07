import { useEffect, useMemo, useRef, useState } from "react";
import {
  pipelineDerivedFramePath,
  pipelineReviewFramePath,
  snapSampledFrameTimeUs,
} from "../api/client";
import type { GeometryFrameIdentity } from "./GeometrySurface";

export type WorkingAreaFrameMode = "exact" | "sampled";

export type WorkingAreaFrameRequest = {
  recordingId: string;
  /** Identity of the exact source selected by the workspace. */
  sourceId: string;
  sourceSha256: string;
  requestedTimeUs: number;
  mode: WorkingAreaFrameMode;
};

export type WorkingAreaFrame = {
  identity: GeometryFrameIdentity;
  imageUrl: string;
  requestedTimeUs: number;
  resolvedTimeUs: number;
  mode: WorkingAreaFrameMode;
  canMutate: boolean;
};

export type WorkingAreaFrameState =
  | { state: "loading"; request: WorkingAreaFrameRequest }
  | {
      state: "ready";
      request: WorkingAreaFrameRequest;
      frame: WorkingAreaFrame;
    }
  | { state: "failed"; request: WorkingAreaFrameRequest; reason: string };

const MAX_CACHED_FRAMES = 32;
const frameCache = new Map<string, string>();
const inFlight = new Map<string, Promise<string>>();

export function workingAreaFramePath(request: WorkingAreaFrameRequest): string {
  return request.mode === "sampled"
    ? pipelineReviewFramePath(request.recordingId, request.requestedTimeUs)
    : pipelineDerivedFramePath(request.recordingId, request.requestedTimeUs);
}

export function workingAreaFrameRequestKey(
  request: WorkingAreaFrameRequest,
): string {
  return [
    request.recordingId,
    request.sourceId,
    request.sourceSha256,
    request.mode,
    Math.max(0, Math.round(request.requestedTimeUs)),
  ].join(":");
}

export function workingAreaFrameCanMutate(
  frame: WorkingAreaFrame | null | undefined,
): boolean {
  return frame?.mode === "exact" && frame.canMutate;
}

export async function loadWorkingAreaFrame(
  request: WorkingAreaFrameRequest,
  signal?: AbortSignal,
): Promise<WorkingAreaFrame> {
  if (!isSha256(request.sourceSha256)) {
    throw new Error("The selected source has an invalid SHA-256 identity.");
  }
  const key = workingAreaFrameRequestKey(request);
  const imageUrl = await loadFrameImage(request, key, signal);
  if (signal?.aborted) throw abortError();
  const response = responseCache.get(key);
  if (response === undefined)
    throw new Error("Frame response metadata is unavailable.");
  return {
    identity: response.identity,
    imageUrl,
    requestedTimeUs: Math.max(0, Math.round(request.requestedTimeUs)),
    resolvedTimeUs: response.resolvedTimeUs,
    mode: request.mode,
    canMutate: request.mode === "exact",
  };
}

type CachedResponse = {
  identity: GeometryFrameIdentity;
  resolvedTimeUs: number;
};

const responseCache = new Map<string, CachedResponse>();

function peek(key: string): string | null {
  const cached = frameCache.get(key);
  if (cached === undefined) return null;
  frameCache.delete(key);
  frameCache.set(key, cached);
  return cached;
}

async function loadFrameImage(
  request: WorkingAreaFrameRequest,
  key: string,
  signal?: AbortSignal,
): Promise<string> {
  const cached = peek(key);
  if (cached !== null) return cached;
  if (signal?.aborted) throw abortError();

  let pending = inFlight.get(key);
  if (pending === undefined) {
    pending = fetchFrame(request, key);
    inFlight.set(key, pending);
    void pending
      .finally(() => {
        if (inFlight.get(key) === pending) inFlight.delete(key);
      })
      .catch(() => undefined);
  }
  return signal === undefined ? pending : raceWithAbort(pending, signal);
}

async function fetchFrame(
  request: WorkingAreaFrameRequest,
  key: string,
): Promise<string> {
  const response = await fetch(workingAreaFramePath(request), {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Source frame request failed (${response.status}).`);
  }
  const sourceSha256 = response.headers.get("X-DokoDetector-Source-Sha256");
  const frameIndex = parseHeaderInteger(response, "X-DokoDetector-Frame-Index");
  const width = parseHeaderInteger(response, "X-DokoDetector-Frame-Width");
  const height = parseHeaderInteger(response, "X-DokoDetector-Frame-Height");
  const requestedTimeUs = parseHeaderInteger(
    response,
    "X-DokoDetector-Requested-Time-Us",
  );
  const resolvedTimeUs = parseHeaderInteger(
    response,
    "X-DokoDetector-Frame-Time-Us",
  );
  const contentSha256 = (response.headers.get("ETag") ?? "").replace(
    /^"|"$/g,
    "",
  );
  if (sourceSha256 !== request.sourceSha256) {
    throw new Error("The recording source changed while loading this frame.");
  }
  if (
    frameIndex === null ||
    width === null ||
    height === null ||
    width === 0 ||
    height === 0 ||
    requestedTimeUs === null ||
    resolvedTimeUs === null ||
    !isSha256(contentSha256)
  ) {
    throw new Error(
      "The source frame response has incomplete identity metadata.",
    );
  }
  const expectedTime =
    request.mode === "sampled"
      ? snapSampledFrameTimeUs(request.requestedTimeUs)
      : Math.max(0, Math.round(request.requestedTimeUs));
  if (requestedTimeUs !== expectedTime) {
    throw new Error(
      "The source frame response does not match the requested time.",
    );
  }
  const blob = await response.blob();
  const imageUrl = URL.createObjectURL(blob);
  responseCache.set(key, {
    identity: {
      sourceId: `${request.sourceId}:${sourceSha256}`,
      frameId: `${frameIndex}@${resolvedTimeUs}`,
      width,
      height,
      contentSha256,
    },
    resolvedTimeUs,
  });
  remember(key, imageUrl);
  return imageUrl;
}

function remember(key: string, imageUrl: string): void {
  frameCache.set(key, imageUrl);
  while (frameCache.size > MAX_CACHED_FRAMES) {
    const oldest = frameCache.keys().next().value;
    if (oldest === undefined) break;
    const oldUrl = frameCache.get(oldest);
    frameCache.delete(oldest);
    responseCache.delete(oldest);
    if (oldUrl?.startsWith("blob:")) URL.revokeObjectURL(oldUrl);
  }
}

function parseHeaderInteger(response: Response, name: string): number | null {
  const raw = response.headers.get(name);
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) ? value : null;
}

function isSha256(value: string): boolean {
  return /^[a-f\d]{64}$/i.test(value);
}

function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

function raceWithAbort<T>(
  promise: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        if (signal.aborted) reject(abortError());
        else resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

export function resetWorkingAreaFrameCacheForTests(): void {
  for (const url of frameCache.values()) {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  }
  frameCache.clear();
  responseCache.clear();
  inFlight.clear();
}

export function useWorkingAreaFrame(
  request: WorkingAreaFrameRequest,
): WorkingAreaFrameState {
  const key = workingAreaFrameRequestKey(request);
  const { mode, recordingId, requestedTimeUs, sourceId, sourceSha256 } =
    request;
  const requestValue = useMemo(
    () => ({ mode, recordingId, requestedTimeUs, sourceId, sourceSha256 }),
    [mode, recordingId, requestedTimeUs, sourceId, sourceSha256],
  );
  const generation = useRef(0);
  const [stored, setStored] = useState<WorkingAreaFrameState | null>(null);
  const state =
    stored !== null && workingAreaFrameRequestKey(stored.request) === key
      ? stored
      : { state: "loading" as const, request: requestValue };

  useEffect(() => {
    const current = generation.current + 1;
    generation.current = current;
    const controller = new AbortController();
    void loadWorkingAreaFrame(requestValue, controller.signal)
      .then((frame) => {
        if (controller.signal.aborted || generation.current !== current) return;
        setStored({ state: "ready", request: requestValue, frame });
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          generation.current !== current ||
          isAbort(error)
        )
          return;
        setStored({
          state: "failed",
          request: requestValue,
          reason:
            error instanceof Error
              ? error.message
              : "The source frame failed to load.",
        });
      });
    return () => controller.abort();
  }, [key, requestValue]);
  return state;
}

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
