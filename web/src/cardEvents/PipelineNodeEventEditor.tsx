import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import styles from "../App.module.css";
import { useProfileName } from "../profile/profile";
import { Toast } from "../Toast";
import { GeometrySurface } from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";
import {
  TimelineRailSeekingPortal,
  useTimelineRailReviewControlsSlot,
  useTimelineRailSeekingSlot,
} from "../pipeline/TimelineRailSeekingControls";
import type { PipelineCardEventRailItem } from "./PipelineCardEventRailItem";

type EventRecord = {
  event_id: string;
  event_type: "card_state_changed";
  start_us: number;
  end_us: number;
  [key: string]: unknown;
};

type EventData = {
  schema_version: "event-data/v1";
  events: EventRecord[];
  [key: string]: unknown;
};

type NodeRevision = {
  node_id: string;
  name: string;
  content_type: string;
  source: Record<string, unknown>;
  head_revision_id: string;
  revision_id: string;
  content: EventData;
  metadata?: Record<string, unknown>;
};

type Review = {
  kind: "item" | "coverage" | "overall";
  item_id?: string;
  decision: string | null;
  review_id: string;
  coverage?: unknown;
};

const REVIEW_QUESTION = "Is this event annotation correct?";
const REVIEW_POLICY = "pipeline-event-review/v1";

export function PipelineNodeEventEditor({
  recordingId,
  nodeId,
  revisionId,
  durationUs,
  sourceSha256 = "",
  portalToInspector = false,
  selectionItemId,
  selectionTimeUs,
  onRevisionChange,
  onPositionChange,
  onRailItemsChange,
  onNotice,
}: {
  recordingId: string;
  nodeId: string;
  revisionId: string;
  durationUs: number;
  sourceSha256?: string;
  portalToInspector?: boolean;
  selectionItemId: string | null;
  selectionTimeUs: number | null;
  onRevisionChange: (
    sourceNodeId: string,
    sourceRevisionId: string,
    nodeId: string,
    revisionId: string,
    itemId: string | null,
    timeUs: number,
  ) => void;
  onPositionChange: (itemId: string | null, timeUs: number) => void;
  onRailItemsChange?: (items: PipelineCardEventRailItem[]) => void;
  onNotice?: (message: string) => void;
}) {
  const profileName = useProfileName();
  const frameRequestTimeUs = selectionTimeUs ?? 0;
  const [stepFrameIndex, setStepFrameIndex] = useState<number | null>(null);
  const completedFrameStepRef = useRef<number | null>(null);
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: `${nodeId}:${revisionId}`,
    sourceSha256,
    requestedTimeUs: frameRequestTimeUs,
    mode: "exact",
    ...(stepFrameIndex === null ? {} : { frameIndex: stepFrameIndex }),
  });
  const seekingSlot = useTimelineRailSeekingSlot();
  const frameStatusSlot = useTimelineRailReviewControlsSlot();
  const [inspectorTarget, setInspectorTarget] = useState<HTMLElement | null>(
    null,
  );
  const revisionRef = useRef({ nodeId, revisionId });
  const savedContentRef = useRef<EventData | null>(null);
  const pendingRef = useRef<{ content: EventData; key: string } | null>(null);
  const savingRef = useRef(false);
  const failedRef = useRef<{ content: EventData; key: string } | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const [node, setNode] = useState<NodeRevision | null>(null);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [localSelectedId, setLocalSelectedId] = useState<string | null>(null);
  const [timeState, setTimeState] = useState({
    external: selectionTimeUs,
    value: selectionTimeUs ?? 0,
  });
  if (timeState.external !== selectionTimeUs)
    setTimeState({
      external: selectionTimeUs,
      value: selectionTimeUs ?? timeState.value,
    });
  const timeUs = timeState.value;
  const setTimeUs = (value: number) =>
    setTimeState((current) => ({ ...current, value }));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [retryAvailable, setRetryAvailable] = useState(false);
  const [watchedThroughUs, setWatchedThroughUs] = useState(0);
  const previousFrameTimeRef = useRef<number | null>(null);
  const rejectedItems = useMemo(() => {
    const byId = new Map<string, { item_id: string }>();
    const excluded = node?.metadata?.excluded_items;
    if (Array.isArray(excluded)) {
      for (const item of excluded) {
        if (
          item !== null &&
          typeof item === "object" &&
          (item as Record<string, unknown>).decision === "rejected" &&
          typeof (item as Record<string, unknown>).item_id === "string"
        ) {
          const itemId = (item as Record<string, string>).item_id;
          byId.set(itemId, { item_id: itemId });
        }
      }
    }
    for (const review of reviews) {
      if (
        review.kind === "item" &&
        review.decision === "rejected" &&
        typeof review.item_id === "string"
      ) {
        byId.set(review.item_id, { item_id: review.item_id });
      }
    }
    return [...byId.values()];
  }, [node, reviews]);
  const savePendingRef = useRef<() => Promise<void>>(async () => undefined);
  const previousSelectionTimeRef = useRef(selectionTimeUs);

  useEffect(() => {
    if (!portalToInspector) return;
    const timer = window.setTimeout(
      () =>
        setInspectorTarget(
          document.querySelector<HTMLElement>(
            '[data-event-inspector-slot="action"]',
          ),
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [portalToInspector]);

  useEffect(() => {
    if (previousSelectionTimeRef.current === selectionTimeUs) return;
    previousSelectionTimeRef.current = selectionTimeUs;
    completedFrameStepRef.current = null;
    setStepFrameIndex(null);
  }, [selectionTimeUs]);

  useEffect(() => {
    if (
      stepFrameIndex === null ||
      frameState.state !== "ready" ||
      completedFrameStepRef.current === stepFrameIndex
    )
      return;
    completedFrameStepRef.current = stepFrameIndex;
    setTimeUs(frameState.frame.resolvedTimeUs);
    onPositionChange(null, frameState.frame.resolvedTimeUs);
  }, [frameState, onPositionChange, stepFrameIndex]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const [revisionResponse, reviewsResponse] = await Promise.all([
          fetch(
            `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}`,
            { signal },
          ),
          fetch(
            `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}/reviews`,
            { signal },
          ),
        ]);
        if (!revisionResponse.ok || !reviewsResponse.ok)
          throw new Error("The selected event revision could not be loaded.");
        const rawNode: unknown = await revisionResponse.json();
        const rawReviews: unknown = await reviewsResponse.json();
        if (!isNodeRevision(rawNode) || !Array.isArray(rawReviews))
          throw new Error("The backend returned invalid event revision data.");
        if (
          sourceSha256 !== "" &&
          rawNode.source.video_sha256 !== sourceSha256
        ) {
          throw new Error(
            "The selected event revision belongs to a different source video.",
          );
        }
        if (signal?.aborted) return;
        revisionRef.current = { nodeId, revisionId };
        savedContentRef.current = rawNode.content;
        setNode(rawNode);
        setEvents(rawNode.content.events);
        setReviews(rawReviews.filter(isReview));
        setError(null);
        setRetryAvailable(false);
        onRailItemsChange?.(
          rawNode.content.events.map((event) => ({
            itemId: event.event_id,
            label: "Card-state change",
            state: reviewState(rawReviews, event.event_id),
            startUs: event.start_us,
            endUs: event.end_us,
          })),
        );
      } catch (reason: unknown) {
        if (!signal?.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Event data could not be loaded.",
          );
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [nodeId, onRailItemsChange, revisionId, sourceSha256],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load]);

  useEffect(() => {
    if (frameState.state !== "ready") return;
    const currentUs = frameState.frame.resolvedTimeUs;
    const previousUs = previousFrameTimeRef.current;
    previousFrameTimeRef.current = currentUs;
    if (
      previousUs !== null &&
      currentUs >= previousUs &&
      currentUs - previousUs <= 500_000 &&
      previousUs <= watchedThroughUs + 500_000
    ) {
      setWatchedThroughUs((current) => Math.max(current, currentUs));
    }
  }, [frameState, watchedThroughUs]);

  useEffect(() => {
    onRailItemsChange?.(
      events.map((event) => ({
        itemId: event.event_id,
        label: "Card-state change",
        state: reviewState(reviews, event.event_id),
        startUs: event.start_us,
        endUs: event.end_us,
      })),
    );
  }, [events, onRailItemsChange, reviews]);

  const editable = node !== null && node.head_revision_id === revisionId;
  const selectedId =
    (selectionItemId !== null &&
    events.some((event) => event.event_id === selectionItemId)
      ? selectionItemId
      : null) ??
    (localSelectedId !== null &&
    events.some((event) => event.event_id === localSelectedId)
      ? localSelectedId
      : null) ??
    events[0]?.event_id ??
    null;
  const sortedEvents = useMemo(
    () => [...events].sort((left, right) => left.start_us - right.start_us),
    [events],
  );

  const savePending = useCallback(async () => {
    if (savingRef.current || pendingRef.current === null) return;
    savingRef.current = true;
    setSaving(true);
    while (pendingRef.current !== null) {
      const pending = pendingRef.current;
      pendingRef.current = null;
      const base = savedContentRef.current;
      if (base === null) break;
      const source = { ...revisionRef.current };
      const pointers = pointersFor(pending.content.events);
      const basePointers = pointersFor(base.events);
      const body = {
        expected_revision_id: revisionRef.current.revisionId,
        idempotency_key: pending.key,
        actor: { kind: "human", id: actorId(profileName) },
        content: pending.content,
        pointers,
        base_pointers: basePointers,
        operations: operationsBetween(base.events, pending.content.events),
      };
      let response: Response | null = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          response = await fetch(
            `/api/pipeline/nodes/${encodeURIComponent(revisionRef.current.nodeId)}/edit`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            },
          );
          if (response.ok || response.status < 500) break;
        } catch {
          if (attempt === 2) break;
        }
        await new Promise((resolve) =>
          window.setTimeout(resolve, 150 * (attempt + 1)),
        );
      }
      if (response === null || !response.ok) {
        failedRef.current = pending;
        pendingRef.current = pending;
        setError(
          response?.status === 409
            ? "This revision changed elsewhere. Select the current head in lineage. Your unsaved change remains here."
            : "The event changes could not be saved. Retry the save to continue.",
        );
        setRetryAvailable(true);
        break;
      }
      const result: unknown = await response.json();
      if (!isEditResult(result)) {
        failedRef.current = pending;
        pendingRef.current = pending;
        setError("The backend returned invalid save data.");
        setRetryAvailable(true);
        break;
      }
      savedContentRef.current = pending.content;
      revisionRef.current = {
        nodeId: result.node_id,
        revisionId: result.revision_id,
      };
      failedRef.current = null;
      setRetryAvailable(false);
      setError(null);
      const notice = result.copied
        ? `Created ${result.name ?? "a copy"} from ${node?.name ?? "the selected event data"} after editing because it has downstream use. The original remains available in lineage.`
        : "Event changes saved.";
      setNotice(notice);
      onNotice?.(notice);
      onRevisionChange(
        source.nodeId,
        source.revisionId,
        result.node_id,
        result.revision_id,
        selectedId,
        timeUs,
      );
    }
    savingRef.current = false;
    setSaving(false);
  }, [node?.name, onNotice, onRevisionChange, profileName, selectedId, timeUs]);

  useEffect(() => {
    savePendingRef.current = savePending;
  }, [savePending]);

  useEffect(
    () => () => {
      if (saveTimerRef.current !== null)
        window.clearTimeout(saveTimerRef.current);
      if (pendingRef.current !== null) void savePendingRef.current();
    },
    [],
  );

  const queueSave = useCallback(
    (nextEvents: EventRecord[]) => {
      if (!editable || savedContentRef.current === null) return;
      const nextContent = { ...savedContentRef.current, events: nextEvents };
      setEvents(nextEvents);
      pendingRef.current = { content: nextContent, key: crypto.randomUUID() };
      failedRef.current = null;
      setRetryAvailable(false);
      if (saveTimerRef.current !== null)
        window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        saveTimerRef.current = null;
        void savePending();
      }, 250);
    },
    [editable, savePending],
  );

  const changeEvent = useCallback(
    (eventId: string, field: "start_us" | "end_us", raw: string) => {
      const value = Number(raw);
      if (!Number.isSafeInteger(value) || value < 0 || value > durationUs)
        return;
      const next = events.map((event) =>
        event.event_id === eventId ? { ...event, [field]: value } : event,
      );
      if (next.some((event) => event.end_us < event.start_us)) return;
      queueSave(next);
    },
    [durationUs, events, queueSave],
  );

  const addEvent = useCallback(() => {
    const start = Math.max(0, Math.min(durationUs, Math.round(timeUs)));
    const event: EventRecord = {
      event_id: crypto.randomUUID(),
      event_type: "card_state_changed",
      start_us: start,
      end_us: start,
    };
    setLocalSelectedId(event.event_id);
    onPositionChange(event.event_id, start);
    queueSave([...events, event]);
  }, [durationUs, events, onPositionChange, queueSave, timeUs]);

  const stepFrame = useCallback(
    (direction: -1 | 1) => {
      if (frameState.state !== "ready") return;
      const currentFrameIndex = Number(
        frameState.frame.identity.frameId.split("@")[0],
      );
      const nextFrameIndex = currentFrameIndex + direction;
      if (nextFrameIndex < 0) return;
      completedFrameStepRef.current = null;
      setStepFrameIndex(nextFrameIndex);
    },
    [frameState],
  );

  const deleteEvent = useCallback(
    (eventId: string) => {
      const next = events.filter((event) => event.event_id !== eventId);
      const nextSelected = next[0] ?? null;
      setLocalSelectedId(nextSelected?.event_id ?? null);
      onPositionChange(nextSelected?.event_id ?? null, timeUs);
      queueSave(next);
    },
    [events, onPositionChange, queueSave, timeUs],
  );

  const recordReview = useCallback(
    async (
      kind: "item" | "coverage" | "overall",
      itemId?: string,
      decision?: string,
    ) => {
      if (node === null || saving || pendingRef.current !== null) return;
      setReviewBusy(true);
      try {
        const current = revisionRef.current;
        const reviewId = crypto.randomUUID();
        const evidence = {
          policy: REVIEW_POLICY,
          source_video_sha256: node.source.video_sha256,
          duration_us: durationUs,
        };
        const endpoint = kind === "item" ? "item" : kind;
        const payload = {
          review_id: reviewId,
          revision_id: current.revisionId,
          question:
            kind === "item"
              ? REVIEW_QUESTION
              : kind === "coverage"
                ? "Was the full recording inspected?"
                : "Is this event data set complete and correct?",
          ...(itemId === undefined ? {} : { item_id: itemId }),
          ...(decision === undefined ? {} : { decision }),
          ...(kind === "coverage"
            ? {
                coverage: {
                  kind: "full_recording",
                  intervals: [{ start_us: 0, end_us: durationUs }],
                },
              }
            : {}),
          reviewer: { kind: "human", id: actorId(profileName) },
          evidence,
        };
        const response = await fetch(
          `/api/pipeline/nodes/${encodeURIComponent(current.nodeId)}/reviews/${endpoint}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
        );
        if (!response.ok)
          throw new Error("The review decision could not be saved.");
        const listResponse = await fetch(
          `/api/pipeline/nodes/${encodeURIComponent(current.nodeId)}/revisions/${encodeURIComponent(current.revisionId)}/reviews`,
        );
        const list: unknown = await listResponse.json();
        if (Array.isArray(list)) setReviews(list.filter(isReview));
        setNotice(
          kind === "item"
            ? `Event marked ${decision}.`
            : "Review decision saved.",
        );
      } catch (reason: unknown) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Review could not be saved.",
        );
      } finally {
        setReviewBusy(false);
      }
    },
    [durationUs, node, profileName, saving],
  );

  const retrySave = useCallback(() => {
    if (failedRef.current !== null) {
      pendingRef.current = failedRef.current;
      failedRef.current = null;
      setError(null);
      setRetryAvailable(false);
      void savePending();
    }
  }, [savePending]);

  const currentCoverage = reviews.some(
    (review) =>
      review.kind === "coverage" &&
      coversRecording(review.coverage, durationUs),
  );

  const eventEditor = (
    <section aria-label="Event data set editor">
      <header>
        <p className={styles.statusLabel}>{node?.name ?? "Event data"}</p>
        <h2>
          {editable ? "Edit event data" : "Inspect historical event data"}
        </h2>
        <p>Revision {revisionId}</p>
        {saving ? <p role="status">Saving event changes…</p> : null}
        {!editable && node !== null ? (
          <p>This revision is historical and read-only.</p>
        ) : null}
      </header>
      {loading ? <p role="status">Loading event data…</p> : null}
      {error !== null ? (
        <div role="alert">
          <p>{error}</p>
          {retryAvailable ? (
            <button onClick={retrySave} type="button">
              Retry save
            </button>
          ) : null}
        </div>
      ) : null}
      {frameState.state === "loading" ? (
        <p role="status">Loading the exact source frame…</p>
      ) : frameState.state === "failed" ? (
        <p role="alert">{frameState.reason}</p>
      ) : null}
      {node !== null ? (
        <div>
          {rejectedItems.length > 0 ? (
            <details>
              <summary>
                Retained rejected events ({rejectedItems.length})
              </summary>
              <ul>
                {rejectedItems.map((item) => (
                  <li key={item.item_id}>
                    {item.item_id} · rejected in an earlier review
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <div>
            <label>
              Full-recording coverage
              <progress
                aria-label="Full-recording coverage"
                max={durationUs}
                value={watchedThroughUs}
              />
              {durationUs > 0
                ? `${Math.floor((watchedThroughUs / durationUs) * 100)}% inspected`
                : "Duration unavailable"}
            </label>
            <button
              disabled={!editable || saving}
              onClick={addEvent}
              type="button"
            >
              Add event at timeline cursor
            </button>
            <button
              disabled={
                !editable ||
                saving ||
                watchedThroughUs < durationUs ||
                durationUs <= 0 ||
                currentCoverage
              }
              onClick={() => void recordReview("coverage")}
              type="button"
            >
              {currentCoverage
                ? "Full recording reviewed"
                : "Record full-recording coverage"}
            </button>
            <button
              disabled={
                !editable ||
                saving ||
                reviewBusy ||
                !currentCoverage ||
                reviews.some((review) => review.kind === "overall") ||
                sortedEvents.some(
                  (event) => reviewState(reviews, event.event_id) === "pending",
                )
              }
              onClick={() =>
                void recordReview("overall", undefined, "accepted")
              }
              type="button"
            >
              Record overall acceptance
            </button>
          </div>
          {sortedEvents.length === 0 ? (
            <p>No events in this data set.</p>
          ) : null}
          <p>
            Overall review:{" "}
            {reviews.find((review) => review.kind === "overall")?.decision ??
              "pending"}
          </p>
          <ol aria-label="Events">
            {sortedEvents.map((event) => (
              <li key={event.event_id}>
                <button
                  aria-pressed={selectedId === event.event_id}
                  onClick={() => {
                    setLocalSelectedId(event.event_id);
                    setTimeUs(event.start_us);
                    onPositionChange(event.event_id, event.start_us);
                  }}
                  type="button"
                >
                  {event.event_id}
                </button>
                <label>
                  Start (µs)
                  <input
                    disabled={!editable || saving}
                    type="number"
                    min={0}
                    max={durationUs}
                    value={event.start_us}
                    onChange={(input) =>
                      changeEvent(
                        event.event_id,
                        "start_us",
                        input.currentTarget.value,
                      )
                    }
                  />
                </label>
                <label>
                  Stable end (µs)
                  <input
                    disabled={!editable || saving}
                    type="number"
                    min={0}
                    max={durationUs}
                    value={event.end_us}
                    onChange={(input) =>
                      changeEvent(
                        event.event_id,
                        "end_us",
                        input.currentTarget.value,
                      )
                    }
                  />
                </label>
                <span>{reviewState(reviews, event.event_id)}</span>
                <button
                  disabled={
                    !editable ||
                    saving ||
                    reviewBusy ||
                    reviewState(reviews, event.event_id) !== "pending"
                  }
                  onClick={() =>
                    void recordReview("item", event.event_id, "accepted")
                  }
                  type="button"
                >
                  Accept
                </button>
                <button
                  disabled={
                    !editable ||
                    saving ||
                    reviewBusy ||
                    reviewState(reviews, event.event_id) !== "pending"
                  }
                  onClick={() =>
                    void recordReview("item", event.event_id, "rejected")
                  }
                  type="button"
                >
                  Reject
                </button>
                <button
                  disabled={!editable || saving}
                  onClick={() => deleteEvent(event.event_id)}
                  type="button"
                >
                  Delete event
                </button>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {notice !== null ? <Toast message={notice} /> : null}
    </section>
  );
  return (
    <>
      {frameState.state === "ready" &&
      (node === null || node.source.video_sha256 === sourceSha256) ? (
        <GeometrySurface
          frame={frameState.frame.identity}
          imageUrl={frameState.frame.imageUrl}
          overlays={[]}
        />
      ) : null}
      {!portalToInspector ? eventEditor : null}
      {portalToInspector && inspectorTarget !== null
        ? createPortal(eventEditor, inspectorTarget)
        : null}
      {seekingSlot !== null ? (
        <TimelineRailSeekingPortal
          slot={seekingSlot}
          groups={[
            {
              label: "Frame stepping",
              controls: [
                {
                  label: "Previous frame",
                  symbol: "−|",
                  shortcut: "Shift+ArrowLeft",
                  disabled:
                    frameState.state !== "ready" ||
                    Number(frameState.frame.identity.frameId.split("@")[0]) <=
                      0,
                  onClick: () => stepFrame(-1),
                },
                {
                  label: "Next frame",
                  symbol: "|+",
                  shortcut: "Shift+ArrowRight",
                  disabled: frameState.state !== "ready",
                  onClick: () => stepFrame(1),
                },
              ],
            },
          ]}
        />
      ) : null}
      {frameStatusSlot !== null && frameState.state === "ready"
        ? createPortal(
            <span className={styles.recordingTimelineTime} role="status">
              Requested {frameState.frame.requestedTimeUs} µs · exact frame{" "}
              {frameState.frame.resolvedTimeUs} µs
            </span>,
            frameStatusSlot,
          )
        : null}
    </>
  );
}

function pointersFor(events: EventRecord[]): Record<string, string> {
  return Object.fromEntries(
    events.map((event, index) => [event.event_id, `/events/${index}`]),
  );
}

function actorId(profileName: string): string {
  const safe = profileName
    .trim()
    .replace(/[^A-Za-z0-9._:-]+/g, "-")
    .replace(/^[^A-Za-z0-9]+/, "")
    .slice(0, 128);
  return safe || "workspace-operator";
}

function operationsBetween(before: EventRecord[], after: EventRecord[]) {
  const previous = new Map(before.map((event) => [event.event_id, event]));
  const next = new Map(after.map((event) => [event.event_id, event]));
  const operations: Array<{ kind: string; before: string[]; after: string[] }> =
    [];
  for (const [id, event] of previous) {
    const replacement = next.get(id);
    if (replacement === undefined)
      operations.push({ kind: "delete", before: [id], after: [] });
    else if (JSON.stringify(event) !== JSON.stringify(replacement))
      operations.push({ kind: "replace", before: [id], after: [id] });
  }
  for (const id of next.keys()) {
    if (!previous.has(id))
      operations.push({ kind: "insert", before: [], after: [id] });
  }
  return operations;
}

function reviewState(
  reviews: unknown,
  itemId: string,
): "accepted" | "rejected" | "corrected" | "added" | "pending" {
  if (!Array.isArray(reviews)) return "pending";
  const review = reviews.find(
    (candidate): candidate is Review =>
      isReview(candidate) &&
      candidate.kind === "item" &&
      candidate.item_id === itemId,
  );
  return review?.decision === "accepted" ||
    review?.decision === "rejected" ||
    review?.decision === "corrected" ||
    review?.decision === "added"
    ? review.decision
    : "pending";
}

function coversRecording(value: unknown, durationUs: number): boolean {
  if (
    !isRecord(value) ||
    value.kind !== "full_recording" ||
    !Array.isArray(value.intervals) ||
    durationUs <= 0
  )
    return false;
  const intervals = value.intervals
    .filter(isRecord)
    .filter(
      (interval) =>
        typeof interval.start_us === "number" &&
        typeof interval.end_us === "number",
    )
    .sort((a, b) => Number(a.start_us) - Number(b.start_us));
  let end = 0;
  for (const interval of intervals) {
    if (Number(interval.start_us) > end) return false;
    end = Math.max(end, Number(interval.end_us));
  }
  return end >= durationUs;
}

function isNodeRevision(value: unknown): value is NodeRevision {
  return (
    isRecord(value) &&
    typeof value.node_id === "string" &&
    typeof value.name === "string" &&
    typeof value.content_type === "string" &&
    typeof value.head_revision_id === "string" &&
    typeof value.revision_id === "string" &&
    isRecord(value.source) &&
    isEventData(value.content)
  );
}

function isEventData(value: unknown): value is EventData {
  return (
    isRecord(value) &&
    value.schema_version === "event-data/v1" &&
    Array.isArray(value.events) &&
    value.events.every(isEventRecord)
  );
}

function isEventRecord(value: unknown): value is EventRecord {
  return (
    isRecord(value) &&
    typeof value.event_id === "string" &&
    value.event_type === "card_state_changed" &&
    Number.isSafeInteger(value.start_us) &&
    Number.isSafeInteger(value.end_us)
  );
}

function isReview(value: unknown): value is Review {
  return (
    isRecord(value) &&
    (value.kind === "item" ||
      value.kind === "coverage" ||
      value.kind === "overall") &&
    typeof value.review_id === "string" &&
    (value.decision === null || typeof value.decision === "string")
  );
}

function isEditResult(value: unknown): value is {
  node_id: string;
  revision_id: string;
  copied: boolean;
  name?: string;
} {
  return (
    isRecord(value) &&
    typeof value.node_id === "string" &&
    typeof value.revision_id === "string" &&
    typeof value.copied === "boolean" &&
    (value.name === undefined || typeof value.name === "string")
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
