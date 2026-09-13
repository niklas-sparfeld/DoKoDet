import { useEffect, useRef, useState } from "react";

import { pipelineReviewFramePath } from "../api/client";
import styles from "../App.module.css";
import eventStyles from "./PipelineCardEventEditor.module.css";
import { formatMicroseconds } from "./PipelineCardEventFormatting";

type FrameStatus = "loading" | "ready" | "unavailable" | "failed";

type FrameState = {
  requestedTimeUs: number;
  requestedUrl: string;
  displayUrl: string | null;
  displayedTimeUs: number | null;
  status: FrameStatus;
  error: string | null;
};

export type CardEventFrameSurfaceProps = {
  recordingId: string;
  requestedTimeUs: number;
};

class ReviewFrameUnavailableError extends Error {
  constructor(status: number) {
    super(`CardEvent review frame unavailable (${status}).`);
    this.name = "ReviewFrameUnavailableError";
  }
}

export function CardEventFrameSurface({
  recordingId,
  requestedTimeUs,
}: CardEventFrameSurfaceProps) {
  const sequenceRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const displayUrlRef = useRef<string | null>(null);
  const objectUrlsRef = useRef(new Set<string>());
  const [frame, setFrame] = useState<FrameState>(() => {
    const normalizedTimeUs = normalizeTime(requestedTimeUs);
    return {
      requestedTimeUs: normalizedTimeUs,
      requestedUrl: pipelineReviewFramePath(recordingId, normalizedTimeUs),
      displayUrl: null,
      displayedTimeUs: null,
      status: "loading",
      error: null,
    };
  });

  useEffect(() => {
    const normalizedTimeUs = normalizeTime(requestedTimeUs);
    const requestUrl = pipelineReviewFramePath(recordingId, normalizedTimeUs);
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void fetch(requestUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok)
          throw new ReviewFrameUnavailableError(response.status);
        const displayedTimeUs = readFrameTime(response, normalizedTimeUs);
        return response.blob().then((blob) => ({ blob, displayedTimeUs }));
      })
      .then(({ blob, displayedTimeUs }) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current)
          return;
        const displayUrl = createDisplayUrl(
          blob,
          requestUrl,
          objectUrlsRef.current,
        );
        const previousUrl = displayUrlRef.current;
        if (
          previousUrl !== null &&
          previousUrl !== displayUrl &&
          objectUrlsRef.current.has(previousUrl)
        ) {
          URL.revokeObjectURL(previousUrl);
          objectUrlsRef.current.delete(previousUrl);
        }
        displayUrlRef.current = displayUrl;
        setFrame({
          requestedTimeUs: normalizedTimeUs,
          requestedUrl: requestUrl,
          displayUrl,
          displayedTimeUs,
          status: "ready",
          error: null,
        });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current)
          return;
        setFrame((current) => ({
          ...current,
          requestedTimeUs: normalizedTimeUs,
          requestedUrl: requestUrl,
          status:
            reason instanceof ReviewFrameUnavailableError
              ? "unavailable"
              : "failed",
          error: describeFrameError(reason),
        }));
      });

    return () => {
      controller.abort();
      if (abortRef.current === controller) abortRef.current = null;
    };
  }, [recordingId, requestedTimeUs]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
      objectUrlsRef.current.clear();
    },
    [],
  );

  const normalizedRequestedTimeUs = normalizeTime(requestedTimeUs);
  const requestedUrl = pipelineReviewFramePath(
    recordingId,
    normalizedRequestedTimeUs,
  );
  const currentFrame =
    frame.requestedTimeUs === normalizedRequestedTimeUs &&
    frame.requestedUrl === requestedUrl
      ? frame
      : {
          requestedTimeUs: normalizedRequestedTimeUs,
          requestedUrl,
          displayUrl: frame.displayUrl,
          displayedTimeUs: frame.displayedTimeUs,
          status: "loading" as const,
          error: null,
        };
  const timeLabel = formatMicroseconds(currentFrame.requestedTimeUs);
  const retained = currentFrame.displayUrl !== null;
  const displayedTimeLabel =
    currentFrame.displayedTimeUs === null
      ? null
      : formatMicroseconds(currentFrame.displayedTimeUs);
  const announcement = frameAnnouncement(
    currentFrame.status,
    timeLabel,
    retained,
  );

  return (
    <section
      className={eventStyles.frameSurface}
      aria-label="CardEvent review source frame"
      data-frame-status={currentFrame.status}
      data-requested-time-us={currentFrame.requestedTimeUs}
    >
      <div className={eventStyles.frameViewport}>
        {currentFrame.displayUrl !== null ? (
          <img
            className={eventStyles.frameImage}
            src={currentFrame.displayUrl}
            alt={
              displayedTimeLabel === null
                ? `CardEvent review frame at ${timeLabel}`
                : `CardEvent review frame at ${displayedTimeLabel}`
            }
            data-frame-requested-time-us={currentFrame.requestedTimeUs}
            onError={() => {
              const failedUrl = currentFrame.displayUrl;
              if (failedUrl === null || displayUrlRef.current !== failedUrl)
                return;
              if (objectUrlsRef.current.has(failedUrl)) {
                URL.revokeObjectURL(failedUrl);
                objectUrlsRef.current.delete(failedUrl);
              }
              displayUrlRef.current = null;
              setFrame((current) =>
                current.displayUrl === failedUrl
                  ? {
                      ...current,
                      displayUrl: null,
                      displayedTimeUs: null,
                      status: "failed",
                      error:
                        "The CardEvent review frame image could not be displayed.",
                    }
                  : current,
              );
            }}
          />
        ) : null}
        {currentFrame.status === "loading" ? (
          <p className={eventStyles.frameStatus} role="status">
            Loading CardEvent review frame at {timeLabel}…
          </p>
        ) : null}
        {currentFrame.status === "unavailable" ||
        currentFrame.status === "failed" ? (
          <p className={eventStyles.frameStatus} role="alert">
            {retained
              ? `${currentFrame.error ?? announcement} Showing the last available frame.`
              : (currentFrame.error ?? announcement)}
          </p>
        ) : null}
      </div>
      <p className={styles.visuallyHidden} role="status" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}

function normalizeTime(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function readFrameTime(response: Response, fallback: number): number {
  const raw = response.headers.get("X-DokoDetector-Frame-Time-Us");
  if (raw === null) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? Math.round(value) : fallback;
}

function createDisplayUrl(
  blob: Blob,
  fallbackUrl: string,
  objectUrls: Set<string>,
): string {
  if (typeof URL.createObjectURL !== "function") return fallbackUrl;
  const displayUrl = URL.createObjectURL(blob);
  objectUrls.add(displayUrl);
  return displayUrl;
}

function frameAnnouncement(
  status: FrameStatus,
  timeLabel: string,
  retained: boolean,
): string {
  if (status === "loading")
    return retained
      ? `Loading CardEvent review frame at ${timeLabel}. The last available frame remains visible.`
      : `Loading CardEvent review frame at ${timeLabel}.`;
  if (status === "ready")
    return `CardEvent review frame loaded at ${timeLabel}.`;
  if (status === "unavailable")
    return `CardEvent review frame unavailable at ${timeLabel}.`;
  return `CardEvent review frame failed at ${timeLabel}.`;
}

function describeFrameError(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The CardEvent review frame request failed.";
}
