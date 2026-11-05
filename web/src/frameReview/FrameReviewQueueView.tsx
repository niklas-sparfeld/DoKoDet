import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createDokoDetectorClient,
  repositoryBundleThumbnailPath,
  type FrameReviewPageResponse,
} from "../api/client";
import { ProfileControl } from "../profile/ProfileControl";
import styles from "./FrameReviewQueueView.module.css";

type QueueItem = FrameReviewPageResponse["items"][number];
type QueueState = QueueItem["state"] | "all";

const FILTERS: Array<{ value: QueueState; label: string }> = [
  { value: "all", label: "All frames" },
  { value: "pending", label: "Pending" },
  { value: "deferred", label: "Deferred" },
  { value: "saved_review", label: "Saved review" },
  { value: "unavailable", label: "Unavailable" },
];

export function FrameReviewQueueView() {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [counts, setCounts] = useState<
    FrameReviewPageResponse["counts"] | null
  >(null);
  const [queueDigest, setQueueDigest] = useState<string | null>(null);
  const [resumeTarget, setResumeTarget] = useState<{
    recordingId: string;
    itemId: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<QueueState>(() =>
    readFilter(window.location.search),
  );

  const loadQueue = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const first = await client.getFrameReviewPage({
          limit: 100,
          cursor: 0,
          signal,
        });
        const pages = [first];
        let cursor = first.next_cursor;
        while (cursor !== null) {
          const page = await client.getFrameReviewPage({
            limit: 100,
            cursor,
            signal,
          });
          pages.push(page);
          cursor = page.next_cursor;
        }
        if (!signal?.aborted) {
          setItems(pages.flatMap((page) => page.items));
          setCounts(first.counts);
          setQueueDigest(first.queue_digest);
          setResumeTarget(
            first.resume_recording_id !== null && first.resume_item_id !== null
              ? {
                  recordingId: first.resume_recording_id,
                  itemId: first.resume_item_id,
                }
              : null,
          );
          setError(null);
        }
      } catch (reason) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void loadQueue(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadQueue]);

  useEffect(() => {
    const updateFilter = () => setFilter(readFilter(window.location.search));
    window.addEventListener("popstate", updateFilter);
    return () => window.removeEventListener("popstate", updateFilter);
  }, []);

  const visibleItems =
    filter === "all" ? items : items.filter((item) => item.state === filter);
  const openTarget = (item: QueueItem) => {
    if (item.editor_target === null || item.state === "unavailable")
      return null;
    const target = new URL(item.editor_target.path, window.location.origin);
    target.searchParams.set("frame_review", "0096-M4");
    return `${target.pathname}${target.search}`;
  };
  const updateWorkflow = async (
    item: QueueItem,
    action: "defer" | "resume",
  ) => {
    if (queueDigest === null) return;
    await client.updateFrameReviewWorkflow(item.recording_id, item.item_id, {
      queue_digest: queueDigest,
      action,
    });
    await loadQueue();
  };

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <a href="/recordings" className={styles.backLink}>
            ← Recordings
          </a>
          <p className={styles.eyebrow}>Frame review</p>
          <h1>To review</h1>
          <p className={styles.description}>
            Frozen 0096 M4 queue · {counts?.total ?? "…"} frames
          </p>
        </div>
        <ProfileControl />
      </header>

      {counts !== null ? (
        <section className={styles.progress} aria-label="Frame review progress">
          <strong>{counts.by_state.saved_review} saved</strong>
          <span>{counts.by_state.pending} pending</span>
          <span>{counts.by_state.deferred} deferred</span>
          <span>{counts.by_state.unavailable} unavailable</span>
        </section>
      ) : null}
      {resumeTarget !== null ? (
        <p className={styles.note}>
          Resume position: {resumeTarget.recordingId} · {resumeTarget.itemId}{" "}
          <a href={resumeHref(items, resumeTarget)}>Open resume frame</a>
        </p>
      ) : null}

      <nav
        className={styles.filters}
        aria-label="Filter frames by review state"
      >
        {FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={filter === option.value}
            onClick={() => {
              setFilter(option.value);
              const params = new URLSearchParams(window.location.search);
              if (option.value === "all") params.delete("state");
              else params.set("state", option.value);
              const query = params.toString();
              window.history.pushState(
                {},
                "",
                `${window.location.pathname}${query ? `?${query}` : ""}`,
              );
            }}
          >
            {option.label}
            {option.value === "all"
              ? ` (${counts?.total ?? 0})`
              : counts
                ? ` (${counts.by_state[option.value]})`
                : ""}
          </button>
        ))}
      </nav>

      {error !== null ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {loading && items.length === 0 ? (
        <p role="status">Loading frame review queue…</p>
      ) : null}
      {!loading && error === null && visibleItems.length === 0 ? (
        <p className={styles.empty}>No frames match this filter.</p>
      ) : null}

      <ol className={styles.list} aria-label="Frames to review">
        {visibleItems.map((item) => {
          const href = openTarget(item);
          const sceneMissing =
            item.editor_target?.scene_run_id !== null &&
            item.editor_target?.scene_revision_id === null;
          return (
            <li
              key={`${item.recording_id}:${item.item_id}`}
              className={styles.row}
            >
              <img
                src={repositoryBundleThumbnailPath(item.recording_id)}
                alt=""
                loading="lazy"
              />
              <div className={styles.itemInfo}>
                <h2>{item.recording_id}</h2>
                <p>
                  Frame {item.item_id} · {formatState(item.state)}
                </p>
                <ul className={styles.reasons} aria-label="Selection reasons">
                  {item.reasons.map((reason) => (
                    <li key={reason}>{formatReason(reason)}</li>
                  ))}
                </ul>
                {sceneMissing ? (
                  <p className={styles.note}>
                    Detector result only. Proposed scene output is unavailable
                    for this frame.
                  </p>
                ) : null}
                {item.unavailable_reason !== null ? (
                  <p className={styles.error}>{item.unavailable_reason}</p>
                ) : null}
              </div>
              {href === null ? (
                <span className={styles.disabledAction}>Unavailable</span>
              ) : (
                <div className={styles.actions}>
                  <a className={styles.openLink} href={href}>
                    Open exact result
                  </a>
                  {item.state === "deferred" ? (
                    <button
                      type="button"
                      onClick={() => void updateWorkflow(item, "resume")}
                    >
                      Resume
                    </button>
                  ) : item.state === "pending" ? (
                    <button
                      type="button"
                      onClick={() => void updateWorkflow(item, "defer")}
                    >
                      Defer
                    </button>
                  ) : null}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </main>
  );
}

export function FrameReviewEditorNavigation({
  recordingId,
  itemId,
}: {
  recordingId: string;
  itemId: string | null;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [queueDigest, setQueueDigest] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const savedResumeKey = useRef<string | null>(null);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const first = await client.getFrameReviewPage({
          limit: 100,
          cursor: 0,
          signal,
        });
        const all = [...first.items];
        let cursor = first.next_cursor;
        while (cursor !== null) {
          const page = await client.getFrameReviewPage({
            limit: 100,
            cursor,
            signal,
          });
          all.push(...page.items);
          cursor = page.next_cursor;
        }
        if (!signal?.aborted) {
          setItems(all);
          setQueueDigest(first.queue_digest);
        }
      } catch {
        if (!signal?.aborted) setItems([]);
      }
    },
    [client],
  );
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refresh(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [refresh]);
  useEffect(() => {
    const updated = () => void refresh();
    window.addEventListener("frame-review-progress-updated", updated);
    return () =>
      window.removeEventListener("frame-review-progress-updated", updated);
  }, [refresh]);

  const index = items.findIndex(
    (item) => item.recording_id === recordingId && item.item_id === itemId,
  );
  useEffect(() => {
    const current = items[index];
    if (index < 0 || queueDigest === null || current === undefined) return;
    const key = `${recordingId}:${current.item_id}`;
    if (savedResumeKey.current === key) return;
    savedResumeKey.current = key;
    void client
      .updateFrameReviewWorkflow(recordingId, current.item_id, {
        queue_digest: queueDigest,
        action: "set_resume",
      })
      .catch((reason: unknown) => setNotice(describeError(reason)));
  }, [client, index, items, queueDigest, recordingId]);
  if (index < 0) {
    return (
      <nav
        className={styles.editorNavigation}
        aria-label="Frame review navigation"
      >
        <a href="/frame-reviews/0096-M4">Return to frame list</a>
      </nav>
    );
  }
  const current = items[index];
  const previous = items[index - 1];
  const next = items[index + 1];
  const changeState = async (action: "defer" | "resume" | "set_resume") => {
    if (queueDigest === null) return;
    try {
      await client.updateFrameReviewWorkflow(recordingId, itemId ?? "", {
        queue_digest: queueDigest,
        action,
      });
      setNotice(
        action === "defer" ? "Frame deferred." : "Resume position saved.",
      );
      window.dispatchEvent(new Event("frame-review-progress-updated"));
      await refresh();
    } catch (reason) {
      setNotice(describeError(reason));
    }
  };
  const previousHref =
    previous === undefined ? undefined : editorHref(previous);
  const nextHref = next === undefined ? undefined : editorHref(next);
  return (
    <nav
      className={styles.editorNavigation}
      aria-label="Frame review navigation"
    >
      <a href="/frame-reviews/0096-M4">Return to frame list</a>
      {current.state === "pending" ? (
        <button type="button" onClick={() => void changeState("defer")}>
          Defer this frame
        </button>
      ) : current.state === "deferred" ? (
        <button type="button" onClick={() => void changeState("resume")}>
          Resume this frame
        </button>
      ) : null}
      <button type="button" onClick={() => void changeState("set_resume")}>
        Set resume point
      </button>
      <span>
        Frame {index + 1} of {items.length} · {current.recording_id} ·{" "}
        {current.item_id}
      </span>
      {previousHref === undefined ? (
        <span className={styles.disabledNav}>← Previous</span>
      ) : (
        <a href={previousHref}>← Previous</a>
      )}
      {nextHref === undefined ? (
        <span className={styles.disabledNav}>Next →</span>
      ) : (
        <a href={nextHref}>Next →</a>
      )}
      {notice !== null ? <span role="status">{notice}</span> : null}
      {items.find((item) => item.state === "pending")?.editor_target ? (
        <a href={editorHref(items.find((item) => item.state === "pending")!)}>
          Next pending frame
        </a>
      ) : null}
      {current.editor_target?.scene_run_id !== null &&
      current.editor_target?.scene_revision_id === null ? (
        <span className={styles.editorNote}>
          Detector result only; scene output is unavailable.
        </span>
      ) : null}
    </nav>
  );
}

export function FrameReviewPinnedRevisionNotice({
  pinnedRevision,
  selectedRevision,
}: {
  pinnedRevision: string | null;
  selectedRevision: string | null;
}) {
  if (
    pinnedRevision === null ||
    selectedRevision === null ||
    pinnedRevision === selectedRevision
  )
    return null;
  return (
    <p role="status" className={styles.editorNote}>
      Viewing frozen queue result {pinnedRevision}. The current generated
      selection is {selectedRevision}; this queue item stays pinned to its
      original result.
    </p>
  );
}

function editorHref(item: QueueItem): string | undefined {
  if (item.state === "unavailable" || item.editor_target === null)
    return undefined;
  const target = new URL(item.editor_target.path, window.location.origin);
  target.searchParams.set("frame_review", "0096-M4");
  return `${target.pathname}${target.search}`;
}

function resumeHref(
  items: QueueItem[],
  target: { recordingId: string; itemId: string },
): string {
  const item = items.find(
    (candidate) =>
      candidate.recording_id === target.recordingId &&
      candidate.item_id === target.itemId,
  );
  return item === undefined
    ? "/frame-reviews/0096-M4"
    : (editorHref(item) ?? "/frame-reviews/0096-M4");
}

export function readFilter(search: string): QueueState {
  const value = new URLSearchParams(search).get("state");
  return FILTERS.some((filter) => filter.value === value)
    ? (value as QueueState)
    : "all";
}

function formatState(value: QueueItem["state"]): string {
  return value === "saved_review"
    ? "Saved review"
    : value[0].toUpperCase() + value.slice(1);
}

function formatReason(value: string): string {
  return value.replaceAll("_", " ").replaceAll(":", " · ");
}

function describeError(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The frame review queue could not be loaded.";
}
