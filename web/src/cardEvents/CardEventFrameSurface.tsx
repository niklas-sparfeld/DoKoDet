import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  pipelineDerivedFramePath,
  repositoryBundleVideoPath,
} from "../api/client";
import styles from "../App.module.css";
import eventStyles from "./PipelineCardEventEditor.module.css";
import { formatMicroseconds } from "./PipelineCardEventFormatting";
import {
  isAbortError,
  loadCachedReviewFrame,
  peekCachedReviewFrame,
  ReviewFrameUnavailableError,
} from "./cardEventFrameCache";

type FrameStatus = "loading" | "ready" | "failed";

export type CardEventFramePlayback = "derived" | "video";

export type CardEventFrameSurfaceProps = {
  recordingId: string;
  requestedTimeUs: number;
  /** derived = cached exact JPEG (event jumps). video = local seek (nudges). */
  playback?: CardEventFramePlayback;
};

export function CardEventFrameSurface({
  recordingId,
  requestedTimeUs,
  playback = "derived",
}: CardEventFrameSurfaceProps) {
  return playback === "video" ? (
    <VideoFrameSurface
      recordingId={recordingId}
      requestedTimeUs={requestedTimeUs}
    />
  ) : (
    <DerivedFrameSurface
      recordingId={recordingId}
      requestedTimeUs={requestedTimeUs}
    />
  );
}

function DerivedFrameSurface({
  recordingId,
  requestedTimeUs,
}: {
  recordingId: string;
  requestedTimeUs: number;
}) {
  const normalizedTimeUs = normalizeTime(requestedTimeUs);
  const requestUrl = pipelineDerivedFramePath(recordingId, normalizedTimeUs);
  const sequenceRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const [status, setStatus] = useState<FrameStatus>(() =>
    peekCachedReviewFrame(requestUrl) === null ? "loading" : "ready",
  );
  const [displayUrl, setDisplayUrl] = useState<string | null>(() =>
    peekCachedReviewFrame(requestUrl),
  );
  const [displayedTimeUs, setDisplayedTimeUs] = useState<number | null>(() =>
    peekCachedReviewFrame(requestUrl) === null ? null : normalizedTimeUs,
  );
  const [error, setError] = useState<string | null>(null);
  const timeLabel = formatMicroseconds(normalizedTimeUs);
  const displayedTimeLabel =
    displayedTimeUs === null ? null : formatMicroseconds(displayedTimeUs);
  const frameIsSettled =
    status === "ready" &&
    displayedTimeUs !== null &&
    displayedTimeUs === normalizedTimeUs &&
    displayUrl !== null;

  useEffect(() => {
    const cached = peekCachedReviewFrame(requestUrl);
    if (cached !== null) {
      setDisplayUrl(cached);
      setDisplayedTimeUs(normalizedTimeUs);
      setStatus("ready");
      setError(null);
      return;
    }

    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("loading");
    setError(null);

    void loadCachedReviewFrame(requestUrl, controller.signal)
      .then((objectUrl) => {
        if (controller.signal.aborted || sequence !== sequenceRef.current)
          return;
        setDisplayUrl(objectUrl);
        setDisplayedTimeUs(normalizedTimeUs);
        setStatus("ready");
        setError(null);
      })
      .catch((reason: unknown) => {
        if (
          controller.signal.aborted ||
          sequence !== sequenceRef.current ||
          isAbortError(reason)
        ) {
          return;
        }
        setStatus("failed");
        setError(
          reason instanceof ReviewFrameUnavailableError || reason instanceof Error
            ? reason.message
            : "The CardEvent review frame request failed.",
        );
      });

    return () => {
      controller.abort();
      if (abortRef.current === controller) abortRef.current = null;
    };
  }, [normalizedTimeUs, requestUrl]);

  const announcement = frameIsSettled
    ? `CardEvent review frame ready at ${timeLabel}.`
    : status === "failed"
      ? (error ?? `CardEvent review frame failed at ${timeLabel}.`)
      : displayedTimeLabel === null
        ? `Loading CardEvent review frame at ${timeLabel}.`
        : `Loading CardEvent review frame at ${timeLabel}. Still showing ${displayedTimeLabel}.`;

  return (
    <FrameChrome
      status={
        frameIsSettled ? "ready" : status === "failed" ? "failed" : "loading"
      }
      settled={frameIsSettled}
      requestedTimeUs={normalizedTimeUs}
      displayedTimeUs={displayedTimeUs}
      timeLabel={timeLabel}
      displayedTimeLabel={displayedTimeLabel}
      announcement={announcement}
      error={error}
    >
      {displayUrl !== null ? (
        <img
          className={`${eventStyles.frameImage}${frameIsSettled ? "" : ` ${eventStyles.frameImageBusy}`}`}
          src={displayUrl}
          alt={`CardEvent review frame at ${displayedTimeLabel ?? timeLabel}`}
        />
      ) : null}
    </FrameChrome>
  );
}

function VideoFrameSurface({
  recordingId,
  requestedTimeUs,
}: {
  recordingId: string;
  requestedTimeUs: number;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const seekGenerationRef = useRef(0);
  const normalizedTimeUs = normalizeTime(requestedTimeUs);
  const [status, setStatus] = useState<FrameStatus>("loading");
  const [displayedTimeUs, setDisplayedTimeUs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timeLabel = formatMicroseconds(normalizedTimeUs);
  const displayedTimeLabel =
    displayedTimeUs === null ? null : formatMicroseconds(displayedTimeUs);
  const videoUrl = repositoryBundleVideoPath(recordingId);
  const frameIsSettled =
    status === "ready" &&
    displayedTimeUs !== null &&
    displayedTimeUs === normalizedTimeUs;

  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;

    const generation = seekGenerationRef.current + 1;
    seekGenerationRef.current = generation;
    const targetSeconds = normalizedTimeUs / 1_000_000;
    let cancelled = false;

    setStatus("loading");
    setError(null);

    const markReady = () => {
      if (cancelled || seekGenerationRef.current !== generation) return;
      setDisplayedTimeUs(normalizedTimeUs);
      setStatus("ready");
      setError(null);
    };
    const markFailed = (message: string) => {
      if (cancelled || seekGenerationRef.current !== generation) return;
      setStatus("failed");
      setError(message);
    };

    const seekToTarget = () => {
      if (cancelled || seekGenerationRef.current !== generation) return;
      try {
        if (Math.abs(video.currentTime - targetSeconds) <= 0.0005) {
          markReady();
          return;
        }
        video.currentTime = targetSeconds;
      } catch {
        markFailed("The CardEvent review video could not seek to this time.");
      }
    };

    const onSeeked = () => markReady();
    const onError = () =>
      markFailed("The CardEvent review video could not be loaded.");
    const onLoadedMetadata = () => seekToTarget();

    video.addEventListener("seeked", onSeeked);
    video.addEventListener("error", onError);
    video.addEventListener("loadedmetadata", onLoadedMetadata);

    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) seekToTarget();

    return () => {
      cancelled = true;
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("error", onError);
      video.removeEventListener("loadedmetadata", onLoadedMetadata);
    };
  }, [normalizedTimeUs, videoUrl]);

  const announcement = frameIsSettled
    ? `CardEvent review frame ready at ${timeLabel}.`
    : status === "failed"
      ? (error ?? `CardEvent review video failed at ${timeLabel}.`)
      : displayedTimeLabel === null
        ? `Loading CardEvent review frame at ${timeLabel}.`
        : `Loading CardEvent review frame at ${timeLabel}. Still showing ${displayedTimeLabel}.`;

  return (
    <FrameChrome
      status={
        frameIsSettled ? "ready" : status === "failed" ? "failed" : "loading"
      }
      settled={frameIsSettled}
      requestedTimeUs={normalizedTimeUs}
      displayedTimeUs={displayedTimeUs}
      timeLabel={timeLabel}
      displayedTimeLabel={displayedTimeLabel}
      announcement={announcement}
      error={error}
    >
      <video
        ref={videoRef}
        className={`${eventStyles.frameImage}${frameIsSettled ? "" : ` ${eventStyles.frameImageBusy}`}`}
        src={videoUrl}
        muted
        playsInline
        preload="auto"
        aria-label={`CardEvent review frame at ${timeLabel}`}
      />
    </FrameChrome>
  );
}

function FrameChrome({
  status,
  settled,
  requestedTimeUs,
  displayedTimeUs,
  timeLabel,
  displayedTimeLabel,
  announcement,
  error,
  children,
}: {
  status: FrameStatus;
  settled: boolean;
  requestedTimeUs: number;
  displayedTimeUs: number | null;
  timeLabel: string;
  displayedTimeLabel: string | null;
  announcement: string;
  error: string | null;
  children: ReactNode;
}) {
  return (
    <section
      className={eventStyles.frameSurface}
      aria-label="CardEvent review source frame"
      data-frame-status={status}
      data-requested-time-us={requestedTimeUs}
      data-displayed-time-us={displayedTimeUs ?? undefined}
      data-frame-settled={settled ? "true" : "false"}
    >
      <div className={eventStyles.frameViewport}>
        {children}
        {!settled && status !== "failed" ? (
          <div
            className={eventStyles.frameLoadingOverlay}
            role="status"
            aria-live="polite"
          >
            <span
              className={eventStyles.frameLoadingSpinner}
              aria-hidden="true"
            />
            <p className={eventStyles.frameLoadingTitle}>Updating frame…</p>
            <p className={eventStyles.frameLoadingDetail}>
              Target {timeLabel}
              {displayedTimeLabel === null
                ? null
                : ` · still showing ${displayedTimeLabel}`}
            </p>
          </div>
        ) : null}
        {settled ? (
          <p className={eventStyles.frameReadyBadge} role="status">
            Frame ready · {timeLabel}
          </p>
        ) : null}
        {status === "failed" ? (
          <p className={eventStyles.frameStatus} role="alert">
            {error ?? announcement}
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
