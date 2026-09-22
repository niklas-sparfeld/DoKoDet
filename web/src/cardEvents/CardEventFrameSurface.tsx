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
import { loadRecordingVideoUrl, peekRecordingVideoUrl } from "./recordingVideoCache";

type FrameStatus = "loading" | "ready" | "failed";
type VideoBufferState = "buffering" | "ready" | "network";

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
  const normalizedTimeUs = normalizeTime(requestedTimeUs);
  const requestUrl = pipelineDerivedFramePath(recordingId, normalizedTimeUs);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const jpegSequenceRef = useRef(0);
  const jpegAbortRef = useRef<AbortController | null>(null);
  const seekGenerationRef = useRef(0);
  const [videoSrc, setVideoSrc] = useState(
    () =>
      peekRecordingVideoUrl(recordingId) ??
      repositoryBundleVideoPath(recordingId),
  );
  const [videoBufferState, setVideoBufferState] = useState<VideoBufferState>(
    () => (peekRecordingVideoUrl(recordingId) !== null ? "ready" : "buffering"),
  );
  const [jpegUrl, setJpegUrl] = useState<string | null>(() =>
    peekCachedReviewFrame(requestUrl),
  );
  const [jpegTimeUs, setJpegTimeUs] = useState<number | null>(() =>
    peekCachedReviewFrame(requestUrl) === null ? null : normalizedTimeUs,
  );
  const [videoTimeUs, setVideoTimeUs] = useState<number | null>(null);
  const [status, setStatus] = useState<FrameStatus>(() =>
    playback === "derived" && peekCachedReviewFrame(requestUrl) !== null
      ? "ready"
      : "loading",
  );
  const [error, setError] = useState<string | null>(null);

  const timeLabel = formatMicroseconds(normalizedTimeUs);
  const displayedTimeUs = playback === "video" ? videoTimeUs : jpegTimeUs;
  const displayedTimeLabel =
    displayedTimeUs === null ? null : formatMicroseconds(displayedTimeUs);
  const frameIsSettled =
    status === "ready" &&
    displayedTimeUs !== null &&
    displayedTimeUs === normalizedTimeUs &&
    (playback === "video" || jpegUrl !== null);

  // Prefetch the recording into a blob URL so nudge seeks stay local.
  useEffect(() => {
    const controller = new AbortController();
    const cached = peekRecordingVideoUrl(recordingId);
    if (cached !== null) {
      setVideoSrc(cached);
      setVideoBufferState("ready");
      return;
    }
    setVideoBufferState("buffering");
    void loadRecordingVideoUrl(recordingId, controller.signal)
      .then((url) => {
        if (controller.signal.aborted) return;
        setVideoSrc(url);
        setVideoBufferState(url.startsWith("blob:") ? "ready" : "network");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || isAbortError(reason)) return;
        setVideoBufferState("network");
      });
    return () => controller.abort();
  }, [recordingId]);

  // Exact JPEG path for event jumps.
  useEffect(() => {
    if (playback !== "derived") return;

    const cached = peekCachedReviewFrame(requestUrl);
    if (cached !== null) {
      setJpegUrl(cached);
      setJpegTimeUs(normalizedTimeUs);
      setStatus("ready");
      setError(null);
      return;
    }

    const sequence = jpegSequenceRef.current + 1;
    jpegSequenceRef.current = sequence;
    jpegAbortRef.current?.abort();
    const controller = new AbortController();
    jpegAbortRef.current = controller;
    setStatus("loading");
    setError(null);

    void loadCachedReviewFrame(requestUrl, controller.signal)
      .then((objectUrl) => {
        if (controller.signal.aborted || sequence !== jpegSequenceRef.current)
          return;
        setJpegUrl(objectUrl);
        setJpegTimeUs(normalizedTimeUs);
        setStatus("ready");
        setError(null);
      })
      .catch((reason: unknown) => {
        if (
          controller.signal.aborted ||
          sequence !== jpegSequenceRef.current ||
          isAbortError(reason)
        ) {
          return;
        }
        setStatus("failed");
        setError(
          reason instanceof ReviewFrameUnavailableError ||
            reason instanceof Error
            ? reason.message
            : "The CardEvent review frame request failed.",
        );
      });

    return () => {
      controller.abort();
      if (jpegAbortRef.current === controller) jpegAbortRef.current = null;
    };
  }, [normalizedTimeUs, playback, requestUrl]);

  // Keep the video element warm near the playhead (quiet seek while showing JPEG).
  useEffect(() => {
    if (playback !== "derived") return;
    const video = videoRef.current;
    if (video === null || video.readyState < HTMLMediaElement.HAVE_METADATA)
      return;
    const targetSeconds = normalizedTimeUs / 1_000_000;
    if (Math.abs(video.currentTime - targetSeconds) <= 0.0005) return;
    try {
      video.currentTime = targetSeconds;
    } catch {
      // Best-effort warm seek; JPEG owns the review UI in derived mode.
    }
  }, [normalizedTimeUs, playback, videoSrc]);

  // Visible video seeks for frame nudges.
  useEffect(() => {
    if (playback !== "video") return;
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
      setVideoTimeUs(normalizedTimeUs);
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
  }, [normalizedTimeUs, playback, videoSrc]);

  const announcement = frameIsSettled
    ? `CardEvent review frame ready at ${timeLabel}.`
    : status === "failed"
      ? (error ?? `CardEvent review frame failed at ${timeLabel}.`)
      : displayedTimeLabel === null
        ? `Loading CardEvent review frame at ${timeLabel}.`
        : `Loading CardEvent review frame at ${timeLabel}. Still showing ${displayedTimeLabel}.`;

  const showJpeg = playback === "derived" && jpegUrl !== null;
  const mediaBusy = !frameIsSettled && status !== "failed";

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
      videoBufferState={videoBufferState}
    >
      <video
        ref={videoRef}
        className={`${eventStyles.frameImage}${mediaBusy && !showJpeg ? ` ${eventStyles.frameImageBusy}` : ""}${showJpeg ? ` ${eventStyles.frameImageHidden}` : ""}`}
        src={videoSrc}
        muted
        playsInline
        preload="auto"
        aria-hidden={showJpeg ? true : undefined}
        aria-label={
          showJpeg ? undefined : `CardEvent review frame at ${timeLabel}`
        }
      />
      {showJpeg ? (
        <img
          className={`${eventStyles.frameImage}${mediaBusy ? ` ${eventStyles.frameImageBusy}` : ""}`}
          src={jpegUrl}
          alt={`CardEvent review frame at ${displayedTimeLabel ?? timeLabel}`}
        />
      ) : null}
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
  videoBufferState,
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
  videoBufferState: VideoBufferState;
  children: ReactNode;
}) {
  const bufferLabel =
    videoBufferState === "buffering"
      ? "Buffering video into memory…"
      : videoBufferState === "ready"
        ? "Video ready in memory"
        : "Network video (too large for memory buffer)";

  return (
    <section
      className={eventStyles.frameSurface}
      aria-label="CardEvent review source frame"
      data-frame-status={status}
      data-video-buffer={videoBufferState}
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
        <p className={eventStyles.frameBufferBadge} role="status">
          {bufferLabel}
        </p>
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
