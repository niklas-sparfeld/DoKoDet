import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  pipelineDerivedFramePath,
  repositoryBundleVideoPath,
} from "../api/client";
import styles from "../App.module.css";
import type {
  RecordingTimelineRailItem,
  RecordingTimelineRailLane,
} from "./recordingWorkspacePresentation";

const PREVIEW_DEBOUNCE_MS = 120;
const PREVIEW_CACHE_LIMIT = 8;

export type RecordingTimelineRailProps = {
  recordingId: string;
  durationUs: number;
  currentTimeUs: number | null;
  selectedItemId: string | null;
  lanes: readonly RecordingTimelineRailLane[];
  items: readonly RecordingTimelineRailItem[];
  onTimeChange: (timeUs: number) => void;
  onItemSelect: (item: RecordingTimelineRailItem) => void;
  videoSelector?: string;
};

type PreviewState = {
  requestedTimeUs: number;
  url: string | null;
  error: string | null;
};

export function RecordingTimelineRail({
  recordingId,
  durationUs,
  currentTimeUs,
  selectedItemId,
  lanes,
  items,
  onTimeChange,
  onItemSelect,
  videoSelector = "video[data-recording-source-video]",
}: RecordingTimelineRailProps) {
  const fallbackVideoRef = useRef<HTMLVideoElement>(null);
  const itemButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const previewCacheRef = useRef(new Map<number, string>());
  const previewObjectUrlsRef = useRef(new Set<string>());
  const previewTimerRef = useRef<number | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewSequenceRef = useRef(0);
  const onTimeChangeRef = useRef(onTimeChange);
  const [playing, setPlaying] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [scrubberScrollLeft, setScrubberScrollLeft] = useState(0);
  const [railHovered, setRailHovered] = useState(false);
  const [hoveredTimeUs, setHoveredTimeUs] = useState<number | null>(null);
  const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);
  const [focusedItemId, setFocusedItemId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewState>(() => ({
    requestedTimeUs: clampTime(currentTimeUs ?? 0, durationUs),
    url: null,
    error: null,
  }));
  const reducedMotion = usePrefersReducedMotion();
  const displayTimeUs = clampTime(currentTimeUs ?? 0, durationUs);
  const previewItemId = hoveredItemId ?? focusedItemId;
  const previewPositionTimeUs = hoveredTimeUs ?? displayTimeUs;

  useEffect(() => {
    onTimeChangeRef.current = onTimeChange;
  }, [onTimeChange]);

  const setItemButtonRef = useCallback(
    (itemId: string, element: HTMLButtonElement | null) => {
      if (element === null) itemButtonRefs.current.delete(itemId);
      else itemButtonRefs.current.set(itemId, element);
    },
    [],
  );

  const getVideo = useCallback((): HTMLVideoElement | null => {
    if (typeof document === "undefined") return null;
    const candidates = Array.from(
      document.querySelectorAll<HTMLVideoElement>(videoSelector),
    );
    const matchingVideo = candidates.find(
      (candidate) => candidate.dataset.recordingSourceVideo === recordingId,
    );
    return (
      matchingVideo ??
      (candidates.length === 1 ? candidates[0] : undefined) ??
      fallbackVideoRef.current
    );
  }, [recordingId, videoSelector]);

  const commitTime = useCallback(
    (nextTimeUs: number) => {
      const next = clampTime(nextTimeUs, durationUs);
      const video = getVideo();
      if (
        video !== null &&
        Math.abs(video.currentTime - next / 1_000_000) > 0.001
      ) {
        try {
          video.currentTime = next / 1_000_000;
        } catch {
          // The media element can reject a seek before metadata is ready.
        }
      }
      onTimeChange(next);
    },
    [durationUs, getVideo, onTimeChange],
  );

  const requestPreview = useCallback(
    (rawTimeUs: number) => {
      const requestedTimeUs = clampTime(rawTimeUs, durationUs);
      if (previewTimerRef.current !== null) {
        window.clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
      previewAbortRef.current?.abort();
      previewAbortRef.current = null;
      previewSequenceRef.current += 1;
      const sequence = previewSequenceRef.current;
      const cachedUrl = previewCacheRef.current.get(requestedTimeUs);
      if (cachedUrl !== undefined) {
        setPreview({ requestedTimeUs, url: cachedUrl, error: null });
        return;
      }
      setPreview({ requestedTimeUs, url: null, error: null });
      const load = () => {
        const controller = new AbortController();
        previewAbortRef.current = controller;
        const requestUrl = pipelineDerivedFramePath(
          recordingId,
          requestedTimeUs,
        );
        void fetch(requestUrl, { signal: controller.signal })
          .then((response) => {
            if (!response.ok)
              throw new Error(`Preview request failed (${response.status}).`);
            return response.blob();
          })
          .then((blob) => {
            if (
              controller.signal.aborted ||
              sequence !== previewSequenceRef.current
            )
              return;
            const previewUrl =
              typeof URL.createObjectURL === "function"
                ? URL.createObjectURL(blob)
                : requestUrl;
            previewCacheRef.current.set(requestedTimeUs, previewUrl);
            if (previewUrl !== requestUrl)
              previewObjectUrlsRef.current.add(previewUrl);
            while (previewCacheRef.current.size > PREVIEW_CACHE_LIMIT) {
              const oldest = previewCacheRef.current.keys().next().value as
                number | undefined;
              if (oldest === undefined) break;
              const evictedUrl = previewCacheRef.current.get(oldest);
              previewCacheRef.current.delete(oldest);
              if (
                evictedUrl !== undefined &&
                previewObjectUrlsRef.current.has(evictedUrl)
              ) {
                URL.revokeObjectURL(evictedUrl);
                previewObjectUrlsRef.current.delete(evictedUrl);
              }
            }
            setPreview({ requestedTimeUs, url: previewUrl, error: null });
          })
          .catch((reason: unknown) => {
            if (
              controller.signal.aborted ||
              sequence !== previewSequenceRef.current
            )
              return;
            setPreview({
              requestedTimeUs,
              url: null,
              error:
                reason instanceof Error
                  ? reason.message
                  : "Preview unavailable.",
            });
          });
      };
      previewTimerRef.current = window.setTimeout(
        load,
        reducedMotion ? PREVIEW_DEBOUNCE_MS / 2 : PREVIEW_DEBOUNCE_MS,
      );
    },
    [durationUs, recordingId, reducedMotion],
  );

  useEffect(() => {
    if (
      !railHovered ||
      previewItemId !== null ||
      (playing && hoveredTimeUs === null)
    )
      return;
    requestPreview(previewPositionTimeUs);
  }, [
    hoveredTimeUs,
    playing,
    previewItemId,
    previewPositionTimeUs,
    railHovered,
    requestPreview,
  ]);

  useEffect(() => {
    const video = getVideo();
    if (video === null) return;
    const updateTime = () => {
      const next = clampTime(video.currentTime * 1_000_000, durationUs);
      onTimeChangeRef.current(next);
    };
    const updatePlaying = () => setPlaying(!video.paused && !video.ended);
    const finish = () => setPlaying(false);
    video.addEventListener("timeupdate", updateTime);
    video.addEventListener("loadedmetadata", updateTime);
    video.addEventListener("play", updatePlaying);
    video.addEventListener("pause", updatePlaying);
    video.addEventListener("ended", finish);
    updatePlaying();
    return () => {
      video.removeEventListener("timeupdate", updateTime);
      video.removeEventListener("loadedmetadata", updateTime);
      video.removeEventListener("play", updatePlaying);
      video.removeEventListener("pause", updatePlaying);
      video.removeEventListener("ended", finish);
    };
  }, [durationUs, getVideo]);

  useEffect(() => {
    const video = getVideo();
    if (video === null || currentTimeUs === null || !video.paused) return;
    try {
      const nextTime = clampTime(currentTimeUs, durationUs) / 1_000_000;
      if (Math.abs(video.currentTime - nextTime) > 0.001)
        video.currentTime = nextTime;
    } catch {
      // The video will be synchronized when its metadata is loaded.
    }
  }, [currentTimeUs, durationUs, getVideo]);

  useEffect(
    () => () => {
      if (previewTimerRef.current !== null)
        window.clearTimeout(previewTimerRef.current);
      previewAbortRef.current?.abort();
      for (const objectUrl of previewObjectUrlsRef.current)
        URL.revokeObjectURL(objectUrl);
    },
    [],
  );

  const togglePlayback = useCallback(() => {
    const video = getVideo();
    if (video === null) return;
    if (video.paused) {
      if (video.ended) video.currentTime = 0;
      void video
        .play()
        .then(() => setPlaying(true))
        .catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }, [getVideo]);

  const selectItem = useCallback(
    (item: RecordingTimelineRailItem) => {
      if (item.timeRange !== null) commitTime(item.timeRange.startUs);
      onItemSelect(item);
      requestPreview(item.timeRange?.startUs ?? displayTimeUs);
    },
    [commitTime, displayTimeUs, onItemSelect, requestPreview],
  );

  const previewItemAtPointer = useCallback(
    (item: RecordingTimelineRailItem) => {
      setHoveredItemId(item.id);
      setHoveredTimeUs(
        item.timeRange === null
          ? displayTimeUs
          : midpoint(item.timeRange.startUs, item.timeRange.endUs),
      );
      requestPreview(item.timeRange?.startUs ?? displayTimeUs);
    },
    [displayTimeUs, requestPreview],
  );

  const previewItemAtFocus = useCallback(
    (item: RecordingTimelineRailItem) => {
      setFocusedItemId(item.id);
      setHoveredTimeUs(
        item.timeRange === null
          ? displayTimeUs
          : midpoint(item.timeRange.startUs, item.timeRange.endUs),
      );
      requestPreview(item.timeRange?.startUs ?? displayTimeUs);
    },
    [displayTimeUs, requestPreview],
  );

  const handleItemKeyDown = useCallback(
    (
      event: KeyboardEvent<HTMLButtonElement>,
      item: RecordingTimelineRailItem,
    ) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const index = items.findIndex((candidate) => candidate.id === item.id);
      const nextIndex = event.key === "ArrowLeft" ? index - 1 : index + 1;
      const next = items[nextIndex];
      if (next === undefined) return;
      itemButtonRefs.current.get(next.id)?.focus();
      selectItem(next);
    },
    [items, selectItem],
  );

  const ticks = useMemo(() => buildTimeTicks(durationUs), [durationUs]);
  const itemByLane = useMemo(() => {
    const grouped = new Map<string, RecordingTimelineRailItem[]>();
    for (const lane of lanes) grouped.set(lane.id, []);
    for (const item of items) grouped.get(item.laneId)?.push(item);
    return grouped;
  }, [items, lanes]);
  const trackStyle = {
    "--timeline-track-width": `${Math.max(52, 52 * zoom)}rem`,
  } as CSSProperties;

  return (
    <div
      className={styles.recordingTimelineRail}
      data-dragging={dragging}
      data-preview-visible={railHovered}
      data-reduced-motion={reducedMotion}
      data-zoom={zoom}
      onPointerEnter={() => setRailHovered(true)}
      onPointerLeave={() => {
        setRailHovered(false);
        setHoveredTimeUs(null);
      }}
    >
      <video
        ref={fallbackVideoRef}
        className={styles.visuallyHidden}
        src={repositoryBundleVideoPath(recordingId)}
        preload="none"
        aria-hidden="true"
      />

      <div className={styles.recordingTimelineRailHeader}>
        <div
          className={styles.recordingTimelineSeekingSlot}
          data-timeline-seeking-slot="true"
        />
        <div
          className={styles.recordingTimelineTransport}
          aria-label="Playback controls"
          role="group"
        >
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={togglePlayback}
            aria-label={playing ? "Pause recording" : "Play recording"}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <span className={styles.recordingTimelineTime} aria-live="polite">
            {formatTimeUs(displayTimeUs)} / {formatTimeUs(durationUs)}
          </span>
          <button
            className={styles.tertiaryButton}
            type="button"
            onClick={() => setZoom((value) => Math.max(1, value - 1))}
            aria-label="Zoom timeline out"
            disabled={zoom === 1}
          >
            −
          </button>
          <span aria-label={`Timeline zoom ${zoom}x`}>{zoom}×</span>
          <button
            className={styles.tertiaryButton}
            type="button"
            onClick={() => setZoom((value) => Math.min(4, value + 1))}
            aria-label="Zoom timeline in"
            disabled={zoom === 4}
          >
            +
          </button>
        </div>
      </div>

      <div className={styles.recordingTimelineScrubberViewport}>
        <div
          className={styles.recordingTimelineScrubberScroll}
          onScroll={(event) =>
            setScrubberScrollLeft(event.currentTarget.scrollLeft)
          }
        >
          <div className={styles.recordingTimelineScrubber} style={trackStyle}>
            <span aria-hidden="true" />
            <div className={styles.recordingTimelineScrubberTrack}>
              <div
                className={styles.recordingTimelineTickLabels}
                aria-hidden="true"
              >
                {ticks.map((tick) => (
                  <span
                    key={tick}
                    style={{ left: `${positionPercent(tick, durationUs)}%` }}
                  >
                    {formatTimeUs(tick)}
                  </span>
                ))}
              </div>
              <input
                className={styles.recordingTimelineRange}
                type="range"
                min={0}
                max={Math.max(durationUs, 0)}
                step={1_000}
                value={displayTimeUs}
                aria-label="Recording playhead"
                aria-valuetext={`${formatTimeUs(displayTimeUs)} of ${formatTimeUs(durationUs)}`}
                onChange={(event) => {
                  const nextTimeUs = Number(event.target.value);
                  setHoveredTimeUs(nextTimeUs);
                  commitTime(nextTimeUs);
                }}
                onFocus={() => requestPreview(displayTimeUs)}
                onPointerEnter={(event) =>
                  setHoveredTimeUs(scrubberTimeAtPointer(event, durationUs))
                }
                onPointerDown={(event) => {
                  capturePointer(event);
                  setDragging(true);
                  const nextTimeUs = scrubberTimeAtPointer(event, durationUs);
                  setHoveredTimeUs(nextTimeUs);
                  commitTime(nextTimeUs);
                }}
                onPointerMove={(event) => {
                  const nextTimeUs = scrubberTimeAtPointer(event, durationUs);
                  setHoveredTimeUs(nextTimeUs);
                  if (dragging) commitTime(nextTimeUs);
                }}
                onPointerLeave={() => setHoveredTimeUs(null)}
                onPointerUp={(event) => {
                  releasePointer(event);
                  setDragging(false);
                }}
                onPointerCancel={(event) => {
                  releasePointer(event);
                  setDragging(false);
                }}
              />
            </div>
          </div>
        </div>
        {railHovered ? (
          <div
            className={styles.recordingTimelinePreviewOverlay}
            style={{ ...trackStyle, left: -scrubberScrollLeft }}
          >
            <span aria-hidden="true" />
            <div className={styles.recordingTimelinePreviewOverlayTrack}>
              <div
                className={styles.recordingTimelinePreviewFrame}
                aria-atomic="true"
                aria-live="polite"
                data-preview-position-us={previewPositionTimeUs}
                style={
                  {
                    "--timeline-preview-position": `${positionPercent(previewPositionTimeUs, durationUs)}%`,
                  } as CSSProperties
                }
              >
                {preview.url !== null ? (
                  <img
                    src={preview.url}
                    alt={`Exact source frame preview at ${formatTimeUs(preview.requestedTimeUs)}`}
                  />
                ) : (
                  <span className={styles.recordingTimelinePreviewPlaceholder}>
                    {preview.error ?? "Loading exact source frame…"}
                  </span>
                )}
                <span className={styles.recordingTimelinePreviewTime}>
                  {formatTimeUs(preview.requestedTimeUs)}
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <div className={styles.recordingTimelineLanesViewport}>
        <div className={styles.recordingTimelineLanes} style={trackStyle}>
          {lanes.map((lane) => {
            const laneItems = itemByLane.get(lane.id) ?? [];
            return (
              <div
                key={lane.id}
                className={styles.recordingTimelineLane}
                role="group"
                aria-label={`${lane.label} lane`}
              >
                <div className={styles.recordingTimelineLaneLabel}>
                  <span>{lane.label}</span>
                  <small>{lane.itemCount}</small>
                </div>
                <div
                  className={styles.recordingTimelineLaneTrack}
                  style={
                    {
                      "--timeline-playhead-position": `${positionPercent(displayTimeUs, durationUs)}%`,
                    } as CSSProperties
                  }
                >
                  {laneItems.map((item) => (
                    <button
                      key={item.id}
                      ref={(element) => setItemButtonRef(item.id, element)}
                      className={styles.recordingTimelineItem}
                      type="button"
                      data-selected={item.id === selectedItemId}
                      data-state={item.state}
                      data-no-time={item.timeRange === null}
                      data-time-kind={timeRangeKind(item)}
                      style={itemStyle(item, durationUs)}
                      aria-pressed={item.id === selectedItemId}
                      aria-label={`${item.label}, ${formatItemTime(item, durationUs)}, ${item.state}`}
                      onClick={() => selectItem(item)}
                      onFocus={() => previewItemAtFocus(item)}
                      onBlur={() => setFocusedItemId(null)}
                      onKeyDown={(event) => handleItemKeyDown(event, item)}
                      onPointerEnter={() => previewItemAtPointer(item)}
                      onPointerLeave={() => {
                        setHoveredItemId(null);
                        setHoveredTimeUs(null);
                      }}
                    >
                      <span>{item.label}</span>
                    </button>
                  ))}
                  {laneItems.length === 0 ? (
                    <span className={styles.recordingTimelineLaneEmpty}>
                      No items
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function capturePointer(event: ReactPointerEvent<HTMLInputElement>): void {
  event.currentTarget.setPointerCapture?.(event.pointerId);
}

function releasePointer(event: ReactPointerEvent<HTMLInputElement>): void {
  if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }
}

function scrubberTimeAtPointer(
  event: ReactPointerEvent<HTMLInputElement>,
  durationUs: number,
): number {
  const range = event.currentTarget;
  const bounds = range.getBoundingClientRect();
  if (bounds.width <= 0) return clampTime(Number(range.value), durationUs);
  const progress = Math.min(
    Math.max((event.clientX - bounds.left) / bounds.width, 0),
    1,
  );
  return clampTime(progress * durationUs, durationUs);
}

function midpoint(startUs: number, endUs: number): number {
  return startUs + (endUs - startUs) / 2;
}

function itemStyle(
  item: RecordingTimelineRailItem,
  durationUs: number,
): CSSProperties {
  if (item.timeRange === null) return { left: "0%", width: "100%" };
  const start = positionPercent(item.timeRange.startUs, durationUs);
  const end = positionPercent(item.timeRange.endUs, durationUs);
  return {
    left: `${start}%`,
    width: `${Math.max(end - start, 1.5)}%`,
  };
}

function timeRangeKind(
  item: RecordingTimelineRailItem,
): "point" | "interval" | "none" {
  if (item.timeRange === null) return "none";
  return item.timeRange.startUs < item.timeRange.endUs ? "interval" : "point";
}

function formatItemTime(
  item: RecordingTimelineRailItem,
  durationUs: number,
): string {
  return item.timeRange === null
    ? "no source time"
    : `${formatTimeUs(clampTime(item.timeRange.startUs, durationUs))}–${formatTimeUs(clampTime(item.timeRange.endUs, durationUs))}`;
}

function buildTimeTicks(durationUs: number): number[] {
  if (durationUs <= 0) return [0];
  const durationSeconds = durationUs / 1_000_000;
  const stepSeconds =
    durationSeconds <= 60
      ? 10
      : durationSeconds <= 300
        ? 30
        : durationSeconds <= 1_800
          ? 60
          : 300;
  const ticks: number[] = [];
  for (
    let seconds = 0;
    seconds * 1_000_000 < durationUs;
    seconds += stepSeconds
  ) {
    ticks.push(seconds * 1_000_000);
    if (ticks.length >= 12) break;
  }
  const last = durationUs;
  if (ticks[ticks.length - 1] !== last) ticks.push(last);
  return ticks;
}

function positionPercent(timeUs: number, durationUs: number): number {
  return durationUs <= 0
    ? 0
    : (clampTime(timeUs, durationUs) / durationUs) * 100;
}

function clampTime(timeUs: number, durationUs: number): number {
  if (!Number.isFinite(timeUs)) return 0;
  return Math.min(Math.max(Math.round(timeUs), 0), Math.max(durationUs, 0));
}

function formatTimeUs(timeUs: number): string {
  const totalSeconds = Math.max(0, Math.round(timeUs / 1_000_000));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return reduced;
}
