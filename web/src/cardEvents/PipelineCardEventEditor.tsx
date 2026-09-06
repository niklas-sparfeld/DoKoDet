import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import {
  ApiError,
  createDokoDetectorClient,
  repositoryBundleVideoPath,
  type PipelineEventResult,
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
} from "../api/client";
import styles from "../App.module.css";

export const PIPELINE_CARD_EVENT_TYPES = [
  "card_played",
  "trick_cleared",
  "card_moved",
  "card_removed",
  "card_returned",
  "multiple_cards_dropped",
  "anomalous_state_change",
] as const;

type PipelineCardEventType = (typeof PIPELINE_CARD_EVENT_TYPES)[number];
type EventState =
  "pending" | "accepted" | "rejected" | "added" | "corrected" | "affected";
type PipelineEvent = {
  event_id: string;
  event_type: PipelineCardEventType;
  start_us: number;
  end_us: number;
  model_scores?: Array<Record<string, unknown>>;
};
type EditableEvent = {
  localId: string;
  itemId: string;
  baseItemId: string | null;
  reviewState: EventState;
  event: PipelineEvent;
};
type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";
type PendingCommand = {
  commandId: string;
  operation: PipelineReferenceOperation;
  notice: string;
  attempts: number;
};

const CONTENT_TYPE = "events" as const;
const RETRY_LIMIT = 3;

export type PipelineCardEventEditorProps = {
  recordingId: string;
  videoUrl?: string;
  durationUs: number;
  generatedRevisionId: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
};

export function PipelineCardEventEditor({
  recordingId,
  videoUrl = repositoryBundleVideoPath(recordingId),
  durationUs,
  generatedRevisionId,
  generatedRunId,
  view,
}: PipelineCardEventEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const referenceRef = useRef<PipelineReferenceResource | null>(null);
  const eventsRef = useRef<EditableEvent[]>([]);
  const selectedIdRef = useRef<string | null>(null);
  const playheadUsRef = useRef(0);
  const watchedThroughUsRef = useRef(0);
  const serverRevisionRef = useRef(0);
  const queueRef = useRef<PendingCommand[]>([]);
  const processingRef = useRef(false);
  const processQueueRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const commandSequenceRef = useRef(0);
  const [reference, setReference] = useState<PipelineReferenceResource | null>(
    null,
  );
  const [generatedEvents, setGeneratedEvents] = useState<PipelineEvent[]>([]);
  const [events, setEvents] = useState<EditableEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [, setPlayheadUs] = useState(0);
  const [watchedThroughUs, setWatchedThroughUs] = useState(0);
  const [loading, setLoading] = useState(view === "reviewed");
  const [generatedLoading, setGeneratedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [queueLength, setQueueLength] = useState(0);
  const [firstUnappliedCommand, setFirstUnappliedCommand] = useState<
    string | null
  >(null);
  const [operatorId, setOperatorId] = useState("");
  const [reviewerId, setReviewerId] = useState("");
  const [coverageComplete, setCoverageComplete] = useState(false);
  const [creatingReference, setCreatingReference] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);

  const frameRate = 30;

  const setLocalEvents = useCallback((nextEvents: EditableEvent[]) => {
    const sorted = [...nextEvents].sort(compareEvents);
    eventsRef.current = sorted;
    setEvents(sorted);
  }, []);

  const setSelected = useCallback((eventId: string | null) => {
    selectedIdRef.current = eventId;
    setSelectedId(eventId);
  }, []);

  const setCurrentTime = useCallback(
    (nextUs: number, updateUrl = true) => {
      const clamped = clampMicroseconds(nextUs, durationUs);
      playheadUsRef.current = clamped;
      setPlayheadUs(clamped);
      if (videoRef.current !== null)
        videoRef.current.currentTime = clamped / 1_000_000;
      if (updateUrl) updatePipelineUrl({ t_us: clamped });
    },
    [durationUs],
  );

  const selectEvent = useCallback(
    (event: EditableEvent, seek = true) => {
      setSelected(event.localId);
      updatePipelineUrl({ item: event.itemId });
      if (seek) setCurrentTime(event.event.start_us);
    },
    [setCurrentTime, setSelected],
  );

  const hydrateReference = useCallback(
    (nextReference: PipelineReferenceResource, preserveSelection = true) => {
      const nextEvents = nextReference.draft.items
        .map(toEditableEvent)
        .filter((event): event is EditableEvent => event !== null);
      referenceRef.current = nextReference;
      serverRevisionRef.current = nextReference.draft.revision;
      setReference(nextReference);
      setLocalEvents(nextEvents);
      const currentId = preserveSelection ? selectedIdRef.current : null;
      const selected =
        nextEvents.find((event) => event.localId === currentId) ??
        nextEvents[0];
      setSelected(selected?.localId ?? null);
      if (nextReference.draft.coverage?.kind === "event_intervals") {
        const intervals = nextReference.draft.coverage.intervals;
        setCoverageComplete(
          Array.isArray(intervals) &&
            intervals.some(
              (interval) =>
                isRecord(interval) &&
                interval.start_us === 0 &&
                isInteger(interval.end_us) &&
                interval.end_us >= durationUs,
            ),
        );
      }
    },
    [durationUs, setLocalEvents, setSelected],
  );

  const loadGenerated = useCallback(
    async (signal?: AbortSignal) => {
      if (generatedRunId === null || generatedRevisionId === null) {
        setGeneratedEvents([]);
        setGeneratedLoading(false);
        return;
      }
      setGeneratedLoading(true);
      try {
        const result = await client.getEventResult(
          recordingId,
          generatedRunId,
          {
            signal,
          },
        );
        if (!signal?.aborted) {
          setGeneratedEvents(readEventsFromResult(result, generatedRevisionId));
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describePipelineEventError(reason));
      } finally {
        if (!signal?.aborted) setGeneratedLoading(false);
      }
    },
    [client, generatedRevisionId, generatedRunId, recordingId],
  );

  const loadReference = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const nextReference = await client.getPipelineReference(
          recordingId,
          CONTENT_TYPE,
          { signal },
        );
        if (!signal?.aborted) {
          hydrateReference(nextReference);
          setError(null);
          setSaveState("saved");
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          if (reason instanceof ApiError && reason.status === 404) {
            referenceRef.current = null;
            setReference(null);
            setLocalEvents([]);
            setError(null);
          } else {
            setError(describePipelineEventError(reason));
          }
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client, hydrateReference, recordingId, setLocalEvents],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (view === "reviewed") void loadReference(controller.signal);
      else setLoading(false);
      void loadGenerated(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (retryTimerRef.current !== null)
        window.clearTimeout(retryTimerRef.current);
    };
  }, [loadGenerated, loadReference, view]);

  useEffect(() => {
    if (view !== "reviewed" || reference === null) return;
    const urlState = readPipelineEditorUrlState();
    const selected =
      (urlState.item === null
        ? undefined
        : events.find((event) => event.itemId === urlState.item)) ?? events[0];
    const timer = window.setTimeout(() => {
      if (
        selected !== undefined &&
        selected.localId !== selectedIdRef.current
      ) {
        setSelected(selected.localId);
      }
      if (urlState.tUs !== null) setCurrentTime(urlState.tUs, false);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [events, reference, setCurrentTime, setSelected, view]);

  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;
    const update = () => {
      const currentUs = clampMicroseconds(
        Number.isFinite(video.currentTime)
          ? Math.round(video.currentTime * 1_000_000)
          : 0,
        durationUs,
      );
      playheadUsRef.current = currentUs;
      setPlayheadUs(currentUs);
      watchedThroughUsRef.current = Math.max(
        watchedThroughUsRef.current,
        currentUs,
      );
      setWatchedThroughUs(watchedThroughUsRef.current);
      if (currentUs >= durationUs && durationUs > 0) setCoverageComplete(true);
    };
    video.addEventListener("timeupdate", update);
    video.addEventListener("loadedmetadata", update);
    video.addEventListener("ended", update);
    update();
    return () => {
      video.removeEventListener("timeupdate", update);
      video.removeEventListener("loadedmetadata", update);
      video.removeEventListener("ended", update);
    };
  }, [durationUs, reference]);

  const nextCommandId = useCallback(() => {
    commandSequenceRef.current += 1;
    return `pipeline-event-${Date.now()}-${commandSequenceRef.current}`;
  }, []);

  const hydrateAndContinue = useCallback(
    (nextReference: PipelineReferenceResource) => {
      hydrateReference(nextReference);
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(
        queueRef.current.length === 0
          ? null
          : describeCommand(queueRef.current[0]),
      );
    },
    [hydrateReference],
  );

  const processQueue = useCallback(async () => {
    if (processingRef.current || queueRef.current.length === 0) {
      if (queueRef.current.length === 0 && saveState !== "conflict") {
        setQueueLength(0);
        setFirstUnappliedCommand(null);
        if (!completionBusy) setSaveState("saved");
      }
      return;
    }
    const command = queueRef.current[0];
    const current = referenceRef.current;
    if (current === null) return;
    processingRef.current = true;
    try {
      const nextReference = await client.updatePipelineReferenceDraft(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: operatorId.trim(),
          command_id: command.commandId,
          operations: [command.operation],
        },
      );
      hydrateAndContinue(nextReference);
      queueRef.current.shift();
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(
        queueRef.current.length === 0
          ? null
          : describeCommand(queueRef.current[0]),
      );
      setNotice(command.notice);
      setError(null);
      command.attempts = 0;
    } catch (reason: unknown) {
      command.attempts += 1;
      processingRef.current = false;
      if (reason instanceof ApiError && reason.status === 409) {
        setSaveState("conflict");
        setFirstUnappliedCommand(describeCommand(command));
        setError(describePipelineEventError(reason));
        return;
      }
      if (isRetryableError(reason) && command.attempts <= RETRY_LIMIT) {
        setSaveState("retrying");
        setError(describePipelineEventError(reason));
        retryTimerRef.current = window.setTimeout(
          () => {
            retryTimerRef.current = null;
            void processQueueRef.current?.();
          },
          Math.min(500, 100 * command.attempts),
        );
        return;
      }
      setSaveState("error");
      setFirstUnappliedCommand(describeCommand(command));
      setError(describePipelineEventError(reason));
      return;
    }
    processingRef.current = false;
    if (queueRef.current.length > 0) {
      setSaveState("saving");
      void processQueueRef.current?.();
    } else {
      setSaveState("saved");
    }
  }, [
    client,
    completionBusy,
    hydrateAndContinue,
    operatorId,
    recordingId,
    saveState,
  ]);

  useEffect(() => {
    processQueueRef.current = processQueue;
    return () => {
      if (processQueueRef.current === processQueue)
        processQueueRef.current = null;
    };
  }, [processQueue]);

  const enqueue = useCallback(
    (
      operation: PipelineReferenceOperation,
      noticeText: string,
      optimistic: (current: EditableEvent[]) => EditableEvent[],
    ) => {
      if (referenceRef.current === null) {
        return;
      }
      const nextEvents = optimistic(eventsRef.current);
      setLocalEvents(nextEvents);
      const command: PendingCommand = {
        commandId: nextCommandId(),
        operation,
        notice: noticeText,
        attempts: 0,
      };
      queueRef.current.push(command);
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(describeCommand(queueRef.current[0]));
      setSaveState("saving");
      setError(null);
      void processQueueRef.current?.();
    },
    [nextCommandId, setLocalEvents],
  );

  const updateEvent = useCallback(
    (
      event: EditableEvent,
      changes: Partial<PipelineEvent>,
      noticeText: string,
    ) => {
      const nextEvent = { ...event.event, ...changes };
      if (!validEvent(nextEvent, durationUs)) {
        setError(
          "Event times must be inside the recording and end at or after start.",
        );
        return;
      }
      enqueue(
        {
          operation: "correct",
          item_id: event.itemId,
          item: nextEvent,
        },
        noticeText,
        (current) =>
          current.map((candidate) =>
            candidate.localId === event.localId
              ? { ...candidate, reviewState: "corrected", event: nextEvent }
              : candidate,
          ),
      );
    },
    [durationUs, enqueue],
  );

  const addEvent = useCallback(() => {
    const startUs = clampMicroseconds(playheadUsRef.current, durationUs);
    const event: EditableEvent = {
      localId: `manual-${Date.now()}-${commandSequenceRef.current + 1}`,
      itemId: `manual-${Date.now()}-${commandSequenceRef.current + 1}`,
      baseItemId: null,
      reviewState: "added",
      event: {
        event_id: `manual-${Date.now()}-${commandSequenceRef.current + 1}`,
        event_type: "card_played",
        start_us: startUs,
        end_us: startUs,
      },
    };
    setSelected(event.localId);
    enqueue(
      { operation: "add", item: event.event },
      "Event added at the playhead.",
      (current) => [...current, event],
    );
  }, [durationUs, enqueue, setSelected]);

  const decideEvent = useCallback(
    (event: EditableEvent, operation: "accept" | "reject") => {
      enqueue(
        { operation, item_id: event.itemId },
        operation === "accept"
          ? "Suggestion accepted."
          : "Event removed from the reference.",
        (current) =>
          current.map((candidate) =>
            candidate.localId === event.localId
              ? {
                  ...candidate,
                  reviewState: operation === "accept" ? "accepted" : "rejected",
                }
              : candidate,
          ),
      );
    },
    [enqueue],
  );

  const selectedEvent = events.find((event) => event.localId === selectedId);
  const nudgeSelected = useCallback(
    (delta: -1 | 1) => {
      if (selectedEvent === undefined) return;
      const frameUs = Math.round(1_000_000 / frameRate);
      const shift = delta * frameUs;
      const startUs = clampMicroseconds(
        selectedEvent.event.start_us + shift,
        durationUs,
      );
      const endUs = clampMicroseconds(
        selectedEvent.event.end_us + shift,
        durationUs,
      );
      if (endUs < startUs) return;
      setCurrentTime(startUs);
      updateEvent(
        selectedEvent,
        { start_us: startUs, end_us: endUs },
        delta < 0
          ? "Event nudged one frame earlier."
          : "Event nudged one frame later.",
      );
    },
    [durationUs, selectedEvent, setCurrentTime, updateEvent],
  );

  const removeSelected = useCallback(() => {
    if (selectedEvent !== undefined) decideEvent(selectedEvent, "reject");
  }, [decideEvent, selectedEvent]);

  const undoRemoval = useCallback(() => {
    if (selectedEvent?.reviewState === "rejected")
      decideEvent(selectedEvent, "accept");
  }, [decideEvent, selectedEvent]);

  const reloadWinningDraft = useCallback(async () => {
    try {
      const winning = await client.getPipelineReference(
        recordingId,
        CONTENT_TYPE,
      );
      hydrateReference(winning);
      setSaveState("saving");
      setError(null);
      setNotice(
        "Winning draft loaded. The queued commands will be retried in order.",
      );
      window.setTimeout(() => void processQueueRef.current?.(), 0);
    } catch (reason: unknown) {
      setSaveState("error");
      setError(describePipelineEventError(reason));
    }
  }, [client, hydrateReference, recordingId]);

  const retryQueuedCommands = useCallback(() => {
    if (queueRef.current.length === 0) return;
    queueRef.current[0].attempts = 0;
    setSaveState("saving");
    setError(null);
    void processQueueRef.current?.();
  }, []);

  const completeReference = useCallback(async () => {
    const current = referenceRef.current;
    if (
      current === null ||
      operatorId.trim() === "" ||
      reviewerId.trim() === "" ||
      !coverageComplete ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      saveState !== "saved" ||
      current.draft.items.some(
        (item) =>
          item.review_state === "pending" || item.review_state === "affected",
      )
    ) {
      return;
    }
    setCompletionBusy(true);
    setSaveState("saving");
    try {
      const completed = await client.completePipelineReference(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: reviewerId.trim(),
          coverage: {
            kind: "full_recording",
            intervals: [{ start_us: 0, end_us: durationUs }],
          },
        },
      );
      hydrateReference(completed, false);
      setSaveState("saved");
      setNotice(
        `Completed reference ${completed.state.selected_completed_revision_id ?? "published"} is immutable.`,
      );
    } catch (reason: unknown) {
      setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      setError(describePipelineEventError(reason));
    } finally {
      setCompletionBusy(false);
    }
  }, [
    client,
    coverageComplete,
    durationUs,
    hydrateReference,
    operatorId,
    recordingId,
    reviewerId,
    saveState,
  ]);

  const createReference = useCallback(async () => {
    if (operatorId.trim() === "") return;
    setCreatingReference(true);
    setError(null);
    try {
      const created = await client.createPipelineReference(
        recordingId,
        CONTENT_TYPE,
        {
          operator_id: operatorId.trim(),
          seed: generatedRevisionId === null ? "empty" : "selected_generated",
          ...(generatedRevisionId === null
            ? {}
            : { source_revision_id: generatedRevisionId }),
        },
      );
      hydrateReference(created, false);
      setReviewerId((current) => current || operatorId.trim());
      setNotice(
        "Maintained event reference created from the selected generated result.",
      );
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadReference();
      } else {
        setError(describePipelineEventError(reason));
      }
    } finally {
      setCreatingReference(false);
    }
  }, [
    client,
    generatedRevisionId,
    hydrateReference,
    loadReference,
    operatorId,
    recordingId,
  ]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      )
        return;
      if (event.key === " ") {
        event.preventDefault();
        if (videoRef.current === null) return;
        if (videoRef.current.paused)
          void videoRef.current.play().catch(() => undefined);
        else videoRef.current.pause();
      } else if (
        event.altKey &&
        (event.key === "ArrowLeft" || event.key === "ArrowRight")
      ) {
        event.preventDefault();
        const sorted = eventsRef.current;
        const currentUs = playheadUsRef.current;
        const next =
          event.key === "ArrowLeft"
            ? [...sorted]
                .reverse()
                .find(
                  (candidate) => candidate.event.start_us < currentUs - 1_000,
                )
            : sorted.find(
                (candidate) => candidate.event.start_us > currentUs + 1_000,
              );
        if (next !== undefined) selectEvent(next);
      } else if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        addEvent();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removeSelected();
      } else if (event.key === "," || event.key === ".") {
        event.preventDefault();
        nudgeSelected(event.key === "," ? -1 : 1);
      } else if (event.key === "a" || event.key === "A") {
        event.preventDefault();
        if (selectedEvent?.reviewState === "pending")
          decideEvent(selectedEvent, "accept");
      } else if (event.key === "d" || event.key === "D") {
        event.preventDefault();
        if (selectedEvent?.reviewState === "pending")
          decideEvent(selectedEvent, "reject");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    addEvent,
    decideEvent,
    nudgeSelected,
    removeSelected,
    selectedEvent,
    selectEvent,
  ]);

  const { captureVideoRef, captureCanvasRef, screenshots } =
    usePipelineEventScreenshots(videoUrl, events, durationUs);
  const pendingCount = events.filter(
    (event) =>
      event.reviewState === "pending" || event.reviewState === "affected",
  ).length;
  const acceptedCount = events.filter((event) =>
    ["accepted", "added", "corrected"].includes(event.reviewState),
  ).length;
  const rejectedCount = events.filter(
    (event) => event.reviewState === "rejected",
  ).length;
  const watchedPercent =
    durationUs > 0 ? Math.min(100, (watchedThroughUs / durationUs) * 100) : 0;
  const completionBlocker =
    reference === null
      ? null
      : reference.state.draft_state === "completed"
        ? "Reference is already complete; make a correction before publishing."
        : pendingCount > 0
          ? `${pendingCount} event${pendingCount === 1 ? "" : "s"} still need a decision.`
          : !coverageComplete
            ? "Watch the complete recording to record full-video coverage."
            : queueLength > 0 ||
                saveState === "saving" ||
                saveState === "retrying"
              ? "Wait for all event commands to save."
              : saveState !== "saved"
                ? "Resolve the event save problem before completing the reference."
                : reviewerId.trim() === ""
                  ? "Enter the reviewer ID before completing the reference."
                  : null;

  if (view === "generated") {
    return (
      <GeneratedEventView
        events={generatedEvents}
        loading={generatedLoading}
        revisionId={generatedRevisionId}
        videoUrl={videoUrl}
        durationUs={durationUs}
      />
    );
  }

  if (loading)
    return (
      <p className={styles.detailEmptyState}>
        Loading maintained event reference…
      </p>
    );
  if (reference === null) {
    return (
      <section
        className={styles.cardEventReviewPanel}
        aria-label="Start event review"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Maintained reference</p>
            <h3>Start event review</h3>
          </div>
          <span className={styles.countLabel}>
            {generatedEvents.length} suggestions
          </span>
        </div>
        <p className={styles.detailLead}>
          Review changes stay in one recording-owned reference. The selected
          generated result is only a suggestion source.
        </p>
        <label className={styles.cardEventReviewer}>
          Operator ID
          <input
            value={operatorId}
            onChange={(event) => setOperatorId(event.target.value)}
            placeholder="operator-01"
          />
        </label>
        {error !== null ? (
          <p className={styles.errorMessage} role="alert">
            {error}
          </p>
        ) : null}
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void createReference()}
          disabled={creatingReference || operatorId.trim() === ""}
        >
          {creatingReference ? "Starting review…" : "Start review"}
        </button>
      </section>
    );
  }

  return (
    <section
      className={styles.cardEventPipelineEditor}
      aria-label="CardEvent maintained reference editor"
    >
      <div className={styles.cardEventReviewHeader}>
        <div>
          <p className={styles.statusLabel}>Maintained reference</p>
          <h3>CardEvent review</h3>
          <p className={styles.detailLead}>
            {reference.draft.source_revision_id === null
              ? "Manual event reference"
              : `Used generated events ${reference.draft.source_revision_id}`}
          </p>
        </div>
        <div className={styles.cardEventReviewCounts} aria-label="Event counts">
          <ReviewCount label="Accepted" value={acceptedCount} />
          <ReviewCount label="Pending" value={pendingCount} />
          <ReviewCount label="Rejected" value={rejectedCount} />
        </div>
      </div>

      <div className={styles.cardEventPipelineVideoGrid}>
        <div>
          <video
            ref={videoRef}
            className={styles.cardEventSourceVideo}
            src={videoUrl}
            controls
            preload="metadata"
            aria-label={`CardEvent source video ${recordingId}`}
          />
          <div className={styles.cardEventTimeline} aria-label="Event timeline">
            {events.map((event, index) => (
              <button
                key={event.localId}
                className={styles.cardEventMarker}
                data-selected={event.localId === selectedId}
                data-state={event.reviewState}
                style={{
                  left: `${(event.event.start_us / Math.max(durationUs, 1)) * 100}%`,
                }}
                type="button"
                aria-label={`Select event ${index + 1} at ${formatMicroseconds(event.event.start_us)}`}
                onClick={() => selectEvent(event)}
              />
            ))}
          </div>
          <div className={styles.cardEventCoverage}>
            <span>Full-recording coverage</span>
            <strong>{Math.round(watchedPercent)}% watched</strong>
            <progress
              max={100}
              value={watchedPercent}
              aria-label="Full-recording coverage"
            />
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={addEvent}
            >
              Add event at playhead
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={durationUs <= 0 || watchedThroughUs < durationUs}
              onClick={() => setCoverageComplete(true)}
            >
              {coverageComplete
                ? "Full recording covered"
                : "Mark full recording covered"}
            </button>
          </div>
        </div>
        {selectedEvent === undefined ? (
          <p className={styles.detailEmptyState}>
            Select an event from the timeline or table.
          </p>
        ) : (
          <EventDetails
            event={selectedEvent}
            durationUs={durationUs}
            editable
            onChange={(changes) =>
              updateEvent(selectedEvent, changes, "Event corrected.")
            }
            onAccept={() => decideEvent(selectedEvent, "accept")}
            onReject={() => decideEvent(selectedEvent, "reject")}
            onUndo={undoRemoval}
            onNudge={nudgeSelected}
          />
        )}
      </div>

      <div className={styles.tableScroller}>
        <table
          className={`${styles.cardEventReviewTable} ${styles.cardEventUnifiedTable}`}
        >
          <caption className={styles.visuallyHidden}>
            Maintained event reference
          </caption>
          <thead>
            <tr>
              <th scope="col">Screenshot</th>
              <th scope="col">Start</th>
              <th scope="col">End</th>
              <th scope="col">Type</th>
              <th scope="col">State</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event, index) => (
              <tr
                key={event.localId}
                data-state={event.reviewState}
                data-selected={event.localId === selectedId}
              >
                <td className={styles.cardEventScreenshotCell}>
                  <button
                    className={styles.cardEventScreenshotButton}
                    type="button"
                    onClick={() => selectEvent(event)}
                    aria-label={`Open screenshot for event ${index + 1}`}
                  >
                    {screenshots[event.localId] === undefined ? (
                      <span className={styles.cardEventScreenshotPlaceholder}>
                        Preparing…
                      </span>
                    ) : (
                      <img
                        className={styles.cardEventScreenshot}
                        src={screenshots[event.localId].src}
                        alt={`Screenshot at ${formatMicroseconds(event.event.start_us)}`}
                      />
                    )}
                  </button>
                </td>
                <td>
                  <button
                    className={styles.cardEventTableSelect}
                    type="button"
                    onClick={() => selectEvent(event)}
                  >
                    {formatMicroseconds(event.event.start_us)}
                  </button>
                </td>
                <td>{formatMicroseconds(event.event.end_us)}</td>
                <td>{formatIdentifier(event.event.event_type)}</td>
                <td>
                  <ReviewStateBadge value={event.reviewState} />
                </td>
                <td>
                  {event.baseItemId === null
                    ? "Manual"
                    : (reference.draft.source_revision_id ?? "Generated")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section
        className={styles.cardEventCompletionBar}
        aria-label="Complete maintained event reference"
      >
        <div>
          <p className={styles.statusLabel}>Review completion</p>
          <strong>
            {reference.state.draft_state === "completed"
              ? "Publish a corrected reference"
              : "Complete full recording review"}
          </strong>
          {completionBlocker !== null ? (
            <p className={styles.cardEventCompletionRequirement}>
              {completionBlocker}
            </p>
          ) : null}
        </div>
        <label className={styles.cardEventCompletionReviewer}>
          Operator ID
          <input
            value={operatorId}
            onChange={(event) => setOperatorId(event.target.value)}
            placeholder="operator-01"
          />
        </label>
        <label className={styles.cardEventCompletionReviewer}>
          Reviewer ID
          <input
            value={reviewerId}
            onChange={(event) => setReviewerId(event.target.value)}
            placeholder="reviewer-01"
          />
        </label>
        <button
          className={styles.primaryButton}
          type="button"
          onClick={() => void completeReference()}
          disabled={completionBusy || completionBlocker !== null}
        >
          {completionBusy
            ? "Completing reference…"
            : reference.state.draft_state === "completed"
              ? "Publish corrected reference"
              : "Complete reference"}
        </button>
      </section>

      <div className={styles.cardEventGuidance}>
        <details>
          <summary>Keyboard shortcuts</summary>
          <p>
            Space play/pause · Alt + ←/→ previous/next event · A accept · D
            reject · N add · comma/period nudge one frame · Delete remove.
          </p>
        </details>
        <details>
          <summary>Event-type guidance</summary>
          <ul>
            {PIPELINE_CARD_EVENT_TYPES.map((type) => (
              <li key={type}>
                <strong>{formatIdentifier(type)}:</strong>{" "}
                {eventTypeGuidance(type)}
              </li>
            ))}
          </ul>
        </details>
      </div>

      {notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {notice}
        </p>
      ) : null}
      {error !== null ? (
        <div className={styles.cardEventError} role="alert">
          <p>
            {saveState === "conflict"
              ? `Conflict: the first unapplied command is ${firstUnappliedCommand ?? "unknown"}. ${error}`
              : error}
          </p>
          <div className={styles.cardEventErrorActions}>
            {saveState === "conflict" ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => void reloadWinningDraft()}
              >
                Reload winning draft and retry
              </button>
            ) : null}
            {queueLength > 0 &&
            (saveState === "error" || saveState === "retrying") ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={retryQueuedCommands}
              >
                Retry queued commands
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      <video
        ref={captureVideoRef}
        className={styles.visuallyHidden}
        src={videoUrl}
        preload="metadata"
        muted
        aria-hidden="true"
      />
      <canvas
        ref={captureCanvasRef}
        className={styles.visuallyHidden}
        aria-hidden="true"
      />
    </section>
  );
}

function GeneratedEventView({
  events,
  loading,
  revisionId,
  videoUrl,
  durationUs,
}: {
  events: PipelineEvent[];
  loading: boolean;
  revisionId: string | null;
  videoUrl: string;
  durationUs: number;
}) {
  return (
    <section
      className={styles.cardEventReviewPanel}
      aria-label="Generated event result"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Generated result</p>
          <h3>Event suggestions</h3>
        </div>
        <span className={styles.countLabel}>
          {events.length} event{events.length === 1 ? "" : "s"}
        </span>
      </div>
      <p className={styles.detailLead}>
        Generated events are immutable suggestions. Choose Review to copy this
        exact result into the maintained reference.
      </p>
      {revisionId !== null ? (
        <p className={styles.pipelineUrlState}>Source revision {revisionId}</p>
      ) : null}
      {loading ? (
        <p className={styles.detailEmptyState}>Loading generated events…</p>
      ) : events.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No generated event result is selected.
        </p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.cardEventReviewTable}>
            <caption className={styles.visuallyHidden}>
              Generated event suggestions
            </caption>
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">End</th>
                <th scope="col">Type</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id}>
                  <td>{formatMicroseconds(event.start_us)}</td>
                  <td>{formatMicroseconds(event.end_us)}</td>
                  <td>{formatIdentifier(event.event_type)}</td>
                  <td>
                    {videoUrl} · {formatDuration(durationUs)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EventDetails({
  event,
  durationUs,
  editable,
  onChange,
  onAccept,
  onReject,
  onUndo,
  onNudge,
}: {
  event: EditableEvent;
  durationUs: number;
  editable: boolean;
  onChange: (changes: Partial<PipelineEvent>) => void;
  onAccept: () => void;
  onReject: () => void;
  onUndo: () => void;
  onNudge: (delta: -1 | 1) => void;
}) {
  const duration = Math.max(0, durationUs) / 1_000_000;
  const updateNumber = (field: "start_us" | "end_us", value: string) => {
    const seconds = Number(value);
    if (Number.isFinite(seconds))
      onChange({ [field]: Math.round(seconds * 1_000_000) });
  };
  return (
    <section
      className={styles.cardEventFormPanel}
      aria-label="Selected event details"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Selected event</p>
          <h3>Event details</h3>
        </div>
        <ReviewStateBadge value={event.reviewState} />
      </div>
      <div className={styles.cardEventFormGrid}>
        <label>
          Start time (seconds)
          <input
            type="number"
            min="0"
            max={duration}
            step="0.000001"
            value={event.event.start_us / 1_000_000}
            disabled={!editable}
            onChange={(input) => updateNumber("start_us", input.target.value)}
            aria-label="Start time for selected event"
          />
        </label>
        <label>
          End time (seconds)
          <input
            type="number"
            min="0"
            max={duration}
            step="0.000001"
            value={event.event.end_us / 1_000_000}
            disabled={!editable}
            onChange={(input) => updateNumber("end_us", input.target.value)}
            aria-label="End time for selected event"
          />
        </label>
        <label>
          Event type
          <select
            value={event.event.event_type}
            disabled={!editable}
            onChange={(input: ChangeEvent<HTMLSelectElement>) =>
              onChange({
                event_type: input.target.value as PipelineCardEventType,
              })
            }
            aria-label="Event type for selected event"
          >
            {PIPELINE_CARD_EVENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {formatIdentifier(type)}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.cardEventFrameReadout}>
          <span>Start frame</span>
          <strong>{Math.round((event.event.start_us / 1_000_000) * 30)}</strong>
        </div>
      </div>
      <div
        className={styles.cardEventVideoActions}
        aria-label="Selected event actions"
      >
        {event.reviewState === "pending" || event.reviewState === "affected" ? (
          <>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={onAccept}
            >
              Accept suggestion
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onReject}
            >
              Reject suggestion
            </button>
          </>
        ) : event.reviewState === "rejected" ? (
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onUndo}
          >
            Undo rejection
          </button>
        ) : (
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={onReject}
          >
            Remove event
          </button>
        )}
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => onNudge(-1)}
          disabled={!editable}
        >
          Nudge -1 frame
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => onNudge(1)}
          disabled={!editable}
        >
          Nudge +1 frame
        </button>
      </div>
    </section>
  );
}

function ReviewCount({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span className={styles.statusLabel}>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
function ReviewStateBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}

function toEditableEvent(item: PipelineReferenceItem): EditableEvent | null {
  const event = readPipelineEvent(item.item);
  if (event === null) return null;
  if (!isEventState(item.review_state)) return null;
  return {
    localId: item.item_id,
    itemId: item.item_id,
    baseItemId: item.base_item_id,
    reviewState: item.review_state,
    event,
  };
}

function readEventsFromResult(
  result: PipelineEventResult,
  revisionId: string,
): PipelineEvent[] {
  const revision =
    result.revisions.find(
      (candidate) => candidate.manifest.revision_id === revisionId,
    ) ?? result.revisions[0];
  if (revision === undefined || !Array.isArray(revision.content.events))
    return [];
  return revision.content.events
    .map(readPipelineEvent)
    .filter((event): event is PipelineEvent => event !== null);
}

function readPipelineEvent(
  value: Record<string, unknown>,
): PipelineEvent | null {
  const eventId = value.event_id;
  const eventType = value.event_type;
  const startUs = value.start_us;
  const endUs = value.end_us;
  if (
    typeof eventId !== "string" ||
    typeof eventType !== "string" ||
    !isPipelineCardEventType(eventType) ||
    !isInteger(startUs) ||
    !isInteger(endUs)
  )
    return null;
  return {
    event_id: eventId,
    event_type: eventType,
    start_us: startUs,
    end_us: endUs,
    ...(Array.isArray(value.model_scores)
      ? { model_scores: value.model_scores.filter(isRecord) }
      : {}),
  };
}

function isPipelineCardEventType(
  value: string,
): value is PipelineCardEventType {
  return (PIPELINE_CARD_EVENT_TYPES as readonly string[]).includes(value);
}
function isEventState(value: string): value is EventState {
  return [
    "pending",
    "accepted",
    "rejected",
    "added",
    "corrected",
    "affected",
  ].includes(value);
}
function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function validEvent(event: PipelineEvent, durationUs: number): boolean {
  return (
    event.start_us >= 0 &&
    event.end_us >= event.start_us &&
    event.end_us <= durationUs
  );
}
function compareEvents(left: EditableEvent, right: EditableEvent): number {
  return (
    left.event.start_us - right.event.start_us ||
    left.event.end_us - right.event.end_us ||
    left.itemId.localeCompare(right.itemId)
  );
}
function clampMicroseconds(value: number, durationUs: number): number {
  return Math.min(Math.max(0, Math.round(value)), Math.max(0, durationUs));
}
function formatMicroseconds(value: number): string {
  const seconds = value / 1_000_000;
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(6).padStart(9, "0")}`;
}
function formatDuration(value: number): string {
  const seconds = Math.floor(value / 1_000_000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}
function eventTypeGuidance(type: PipelineCardEventType): string {
  return {
    card_played: "A card reaches its final position in the trick area.",
    trick_cleared: "The cards from the completed trick leave the play area.",
    card_moved: "An existing card changes position without being played.",
    card_removed: "A card leaves the visible play area for another reason.",
    card_returned: "A card returns to a hand or another known area.",
    multiple_cards_dropped: "Several cards enter the play area together.",
    anomalous_state_change:
      "A visible state change does not match the other types.",
  }[type];
}
function describeCommand(command: PendingCommand | undefined): string {
  return command === undefined
    ? "none"
    : `${formatIdentifier(command.operation.operation)} ${command.operation.item_id ?? "event"}`;
}
function isRetryableError(reason: unknown): boolean {
  return !(
    reason instanceof ApiError &&
    reason.status >= 400 &&
    reason.status < 500
  );
}
function describePipelineEventError(reason: unknown): string {
  if (
    reason instanceof ApiError &&
    isRecord(reason.body) &&
    isRecord(reason.body.error) &&
    typeof reason.body.error.message === "string"
  )
    return reason.body.error.message;
  return reason instanceof Error
    ? reason.message
    : "The event reference could not be saved.";
}

function readPipelineEditorUrlState(): {
  item: string | null;
  tUs: number | null;
} {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("t_us");
  return {
    item: params.get("item"),
    tUs: raw !== null && /^\d+$/.test(raw) ? Number(raw) : null,
  };
}
function updatePipelineUrl(values: {
  item?: string | null;
  t_us?: number | null;
}): void {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === undefined) params.delete(key);
    else params.set(key, String(value));
  }
  const query = params.toString();
  window.history.replaceState(
    {},
    "",
    `${window.location.pathname}${query === "" ? "" : `?${query}`}`,
  );
}

function usePipelineEventScreenshots(
  videoUrl: string,
  events: EditableEvent[],
  durationUs: number,
) {
  const captureVideoRef = useRef<HTMLVideoElement>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement>(null);
  const cacheRef = useRef(new Map<string, { timeUs: number; src: string }>());
  const [screenshots, setScreenshots] = useState<
    Record<string, { timeUs: number; src: string }>
  >({});
  useEffect(() => {
    const video = captureVideoRef.current;
    const canvas = captureCanvasRef.current;
    if (video === null || canvas === null || videoUrl === "") return;
    const captureVideo = video;
    const captureCanvas = canvas;
    const activeIds = new Set(events.map((event) => event.localId));
    for (const id of cacheRef.current.keys())
      if (!activeIds.has(id)) cacheRef.current.delete(id);
    const pending = events.filter(
      (event) =>
        cacheRef.current.get(event.localId)?.timeUs !== event.event.start_us,
    );
    const controller = new AbortController();
    async function capture() {
      try {
        await waitForVideoReady(captureVideo, controller.signal);
        const width = Math.min(captureVideo.videoWidth || 640, 640);
        const height = Math.max(
          1,
          Math.round(
            (width * (captureVideo.videoHeight || 360)) /
              (captureVideo.videoWidth || 640),
          ),
        );
        captureCanvas.width = width;
        captureCanvas.height = height;
        const context = captureCanvas.getContext("2d");
        if (context === null) throw new Error("Canvas is unavailable.");
        for (const event of pending) {
          if (controller.signal.aborted) return;
          await seekVideo(
            captureVideo,
            clampMicroseconds(event.event.start_us, durationUs) / 1_000_000,
            controller.signal,
          );
          context.drawImage(captureVideo, 0, 0, width, height);
          const screenshot = {
            timeUs: event.event.start_us,
            src: captureCanvas.toDataURL("image/jpeg", 0.78),
          };
          cacheRef.current.set(event.localId, screenshot);
          if (!controller.signal.aborted)
            setScreenshots((current) => ({
              ...current,
              [event.localId]: screenshot,
            }));
        }
      } catch {
        /* The table remains usable when a source frame is unavailable. */
      }
    }
    void capture();
    return () => controller.abort();
  }, [durationUs, events, videoUrl]);
  return { captureVideoRef, captureCanvasRef, screenshots };
}

function waitForVideoReady(
  video: HTMLVideoElement,
  signal: AbortSignal,
): Promise<void> {
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA)
    return Promise.resolve();
  return waitForMediaEvent(video, "loadedmetadata", signal);
}
function seekVideo(
  video: HTMLVideoElement,
  time: number,
  signal: AbortSignal,
): Promise<void> {
  if (
    video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    Math.abs(video.currentTime - time) < 0.001
  )
    return Promise.resolve();
  const ready = waitForMediaEvent(video, "seeked", signal);
  video.currentTime = time;
  return ready;
}
function waitForMediaEvent(
  video: HTMLVideoElement,
  eventName: "loadedmetadata" | "seeked",
  signal: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      video.removeEventListener(eventName, finish);
      video.removeEventListener("error", fail);
      signal.removeEventListener("abort", abort);
      window.clearTimeout(timeout);
    };
    const finish = () => {
      cleanup();
      resolve();
    };
    const fail = () => {
      cleanup();
      reject(new Error("The recording frame could not be loaded."));
    };
    const abort = () => {
      cleanup();
      reject(new Error("Screenshot capture was cancelled."));
    };
    const timeout = window.setTimeout(fail, 10_000);
    video.addEventListener(eventName, finish);
    video.addEventListener("error", fail);
    signal.addEventListener("abort", abort, { once: true });
  });
}
