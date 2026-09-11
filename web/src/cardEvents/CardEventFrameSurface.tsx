import { useEffect, useRef, useState } from "react";

import { pipelineDerivedFramePath } from "../api/client";
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

class ExactFrameUnavailableError extends Error {
  constructor(status: number) {
    super(`Exact source frame unavailable (${status}).`);
    this.name = "ExactFrameUnavailableError";
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
      requestedUrl: pipelineDerivedFramePath(recordingId, normalizedTimeUs),
      displayUrl: null,
      displayedTimeUs: null,
      status: "loading",
      error: null,
    };
  });

  useEffect(() => {
    const normalizedTimeUs = normalizeTime(requestedTimeUs);
    const requestUrl = pipelineDerivedFramePath(recordingId, normalizedTimeUs);
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void fetch(requestUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new ExactFrameUnavailableError(response.status);
        return response.blob();
      })
      .then((blob) => {
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
          displayedTimeUs: normalizedTimeUs,
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
            reason instanceof ExactFrameUnavailableError
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
  const requestedUrl = pipelineDerivedFramePath(
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
      aria-label="CardEvent exact source frame"
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
                ? `Exact CardEvent source frame at ${timeLabel}`
                : `Exact CardEvent source frame at ${displayedTimeLabel}`
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
                        "The exact source frame image could not be displayed.",
                    }
                  : current,
              );
            }}
          />
        ) : null}
        {currentFrame.status === "loading" ? (
          <p className={eventStyles.frameStatus} role="status">
            Loading exact source frame at {timeLabel}…
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
      ? `Loading exact source frame at ${timeLabel}. The last available frame remains visible.`
      : `Loading exact source frame at ${timeLabel}.`;
  if (status === "ready") return `Exact source frame loaded at ${timeLabel}.`;
  if (status === "unavailable")
    return `Exact source frame unavailable at ${timeLabel}.`;
  return `Exact source frame failed at ${timeLabel}.`;
}

function describeFrameError(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The exact source frame request failed.";
}
