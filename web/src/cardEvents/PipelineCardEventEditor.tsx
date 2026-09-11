import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import eventStyles from "./PipelineCardEventEditor.module.css";
import { formatIdentifier } from "./PipelineCardEventFormatting";
import {
  readProfileName,
  subscribeToProfileName,
  useProfileName,
} from "../profile/profile";
import {
  CardEventReviewControls,
  EventSourceSurface,
  GeneratedEventView,
} from "./PipelineCardEventPresentation";
import {
  EventInspectorPortals,
  useEventInspectorSlots,
} from "./PipelineCardEventInspector";
import {
  CARD_STATE_CHANGED_EVENT_TYPE,
  type EditableEvent,
  type EventState,
  type PendingCommand,
  type PipelineEvent,
  type SaveState,
} from "./PipelineCardEventTypes";

export { CARD_STATE_CHANGED_EVENT_TYPE } from "./PipelineCardEventTypes";

export type PipelineCardEventRailItem = {
  itemId: string;
  label: string;
  state: EventState;
  startUs: number;
  endUs: number;
};

const CONTENT_TYPE = "events" as const;
const RETRY_LIMIT = 3;

export type PipelineCardEventEditorProps = {
  recordingId: string;
  videoUrl?: string;
  durationUs: number;
  selectionItemId?: string | null;
  selectionTimeUs?: number | null;
  generatedRevisionId: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
  onRailItemsChange?: (items: PipelineCardEventRailItem[]) => void;
  onReviewRequested?: () => void;
  inspectorEnabled?: boolean;
};

export function PipelineCardEventEditor({
  recordingId,
  videoUrl = repositoryBundleVideoPath(recordingId),
  durationUs,
  selectionItemId,
  selectionTimeUs,
  generatedRevisionId,
  generatedRunId,
  view,
  onRailItemsChange,
  onReviewRequested,
  inspectorEnabled = true,
}: PipelineCardEventEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const profileName = useProfileName();
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
  const [playheadUs, setPlayheadUs] = useState(0);
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
  const [operatorId, setOperatorId] = useState(profileName);
  const [reviewerId, setReviewerId] = useState(profileName);
  const [coverageComplete, setCoverageComplete] = useState(false);
  const [creatingReference, setCreatingReference] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);
  const inspectorSlots = useEventInspectorSlots(inspectorEnabled, view);

  useEffect(
    () =>
      subscribeToProfileName(() => {
        const nextProfileName = readProfileName();
        setOperatorId(nextProfileName);
        setReviewerId(nextProfileName);
      }),
    [],
  );

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
      if (view === "reviewed") {
        watchedThroughUsRef.current = Math.max(
          watchedThroughUsRef.current,
          clamped,
        );
        setWatchedThroughUs(watchedThroughUsRef.current);
        if (clamped >= durationUs && durationUs > 0) setCoverageComplete(true);
      }
      if (view === "generated" && videoRef.current !== null)
        videoRef.current.currentTime = clamped / 1_000_000;
      if (updateUrl) updatePipelineUrl({ t_us: clamped });
    },
    [durationUs, view],
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
    if (view === "reviewed" && reference === null) return;
    const urlState = readPipelineEditorUrlState();
    const requestedItemId =
      selectionItemId === undefined ? urlState.item : selectionItemId;
    const selected =
      view !== "reviewed" || requestedItemId === null
        ? undefined
        : (events.find((event) => event.itemId === requestedItemId) ??
          (view === "reviewed" ? events[0] : undefined));
    const requestedTimeUs =
      selectionTimeUs === undefined ? urlState.tUs : selectionTimeUs;
    const timer = window.setTimeout(() => {
      const selectionChanged =
        selected !== undefined && selected.localId !== selectedIdRef.current;
      if (selectionChanged) {
        setSelected(selected.localId);
      }
      if (requestedTimeUs !== null) {
        setCurrentTime(requestedTimeUs, false);
      } else if (selectionChanged && view === "reviewed") {
        setCurrentTime(selected.event.start_us, false);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    events,
    reference,
    selectionItemId,
    selectionTimeUs,
    setCurrentTime,
    setSelected,
    view,
  ]);

  useEffect(() => {
    if (view !== "reviewed") {
      return;
    }
    onRailItemsChange?.(
      events.map((event) => ({
        itemId: event.itemId,
        label: "Card-state change",
        state: event.reviewState,
        startUs: event.event.start_us,
        endUs: event.event.end_us,
      })),
    );
  }, [events, onRailItemsChange, view]);

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
        event_type: CARD_STATE_CHANGED_EVENT_TYPE,
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
  const seekBy = useCallback(
    (deltaUs: number) => setCurrentTime(playheadUsRef.current + deltaUs),
    [setCurrentTime],
  );
  const selectAdjacent = useCallback(
    (direction: -1 | 1) => {
      const sorted = eventsRef.current;
      const currentUs = playheadUsRef.current;
      const next =
        direction < 0
          ? [...sorted]
              .reverse()
              .find((candidate) => candidate.event.start_us < currentUs - 1_000)
          : sorted.find(
              (candidate) => candidate.event.start_us > currentUs + 1_000,
            );
      if (next !== undefined) selectEvent(next);
    },
    [selectEvent],
  );
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

  const dismissSelected = useCallback(() => {
    if (selectedEvent === undefined) return;
    if (selectedEvent.reviewState === "rejected") undoRemoval();
    else removeSelected();
  }, [removeSelected, selectedEvent, undoRemoval]);

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
        if (view !== "generated") return;
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
        selectAdjacent(event.key === "ArrowLeft" ? -1 : 1);
      } else if (
        !event.altKey &&
        (event.key === "ArrowLeft" || event.key === "ArrowRight")
      ) {
        event.preventDefault();
        seekBy(event.key === "ArrowLeft" ? -250_000 : 250_000);
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
        if (
          selectedEvent?.reviewState === "pending" ||
          selectedEvent?.reviewState === "affected"
        )
          decideEvent(selectedEvent, "accept");
      } else if (event.key === "d" || event.key === "D") {
        event.preventDefault();
        dismissSelected();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    addEvent,
    decideEvent,
    dismissSelected,
    nudgeSelected,
    removeSelected,
    selectedEvent,
    selectAdjacent,
    seekBy,
    view,
  ]);

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
  const hasPreviousEvent = events.some(
    (event) => event.event.start_us < playheadUs - 1_000,
  );
  const hasNextEvent = events.some(
    (event) => event.event.start_us > playheadUs + 1_000,
  );
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

  const selectedGeneratedEvent = selectGeneratedEvent(
    generatedEvents,
    selectionItemId ?? readPipelineEditorUrlState().item,
    selectionTimeUs ?? readPipelineEditorUrlState().tUs,
  );
  const inspector = (
    <EventInspectorPortals
      slots={inspectorSlots}
      inspectorEnabled={inspectorEnabled}
      view={view}
      reference={reference}
      generatedEvents={generatedEvents}
      generatedRevisionId={generatedRevisionId}
      generatedLoading={generatedLoading}
      selectedEvent={selectedEvent}
      selectedGeneratedEvent={selectedGeneratedEvent}
      pendingCount={pendingCount}
      acceptedCount={acceptedCount}
      rejectedCount={rejectedCount}
      saveState={saveState}
      queueLength={queueLength}
      firstUnappliedCommand={firstUnappliedCommand}
      error={error}
      operatorId={operatorId}
      reviewerId={reviewerId}
      setOperatorId={setOperatorId}
      setReviewerId={setReviewerId}
      creatingReference={creatingReference}
      completionBusy={completionBusy}
      completionBlocker={completionBlocker}
      watchedPercent={watchedPercent}
      watchedThroughUs={watchedThroughUs}
      coverageComplete={coverageComplete}
      durationUs={durationUs}
      addEvent={addEvent}
      markCoverage={() => setCoverageComplete(true)}
      retryQueuedCommands={retryQueuedCommands}
      reloadWinningDraft={reloadWinningDraft}
      completeReference={completeReference}
      createReference={createReference}
      onReviewRequested={onReviewRequested}
    />
  );
  if (view === "generated") {
    return (
      <>
        {inspector}
        <GeneratedEventView
          events={generatedEvents}
          loading={generatedLoading}
          revisionId={generatedRevisionId}
          videoUrl={videoUrl}
          durationUs={durationUs}
          selectedEvent={selectedGeneratedEvent}
          videoRef={videoRef}
          recordingId={recordingId}
        />
      </>
    );
  }

  if (loading)
    return (
      <>
        {inspector}
        <p className={styles.detailEmptyState}>
          Loading maintained event reference…
        </p>
      </>
    );
  if (reference === null) {
    return (
      <>
        {inspector}
        <EventSourceSurface
          recordingId={recordingId}
          requestedTimeUs={playheadUs}
          durationUs={durationUs}
          watchedPercent={watchedPercent}
          watchedThroughUs={watchedThroughUs}
          coverageComplete={coverageComplete}
          onAddEvent={addEvent}
          onMarkCoverage={() => setCoverageComplete(true)}
          showCoverageControls={onRailItemsChange === undefined}
        />
        <section
          className={eventStyles.reviewPanel}
          aria-label="Start event review"
        >
          <p className={styles.detailLead}>
            No maintained event reference exists yet. Use the primary action in
            the inspector to start review.
          </p>
        </section>
      </>
    );
  }

  return (
    <>
      {inspector}
      <section
        className={eventStyles.pipelineEditor}
        aria-label="CardEvent maintained reference editor"
      >
        <div className={eventStyles.reviewWorkbench}>
          <CardEventReviewControls
            hasPrevious={hasPreviousEvent}
            hasNext={hasNextEvent}
            selectedState={selectedEvent?.reviewState ?? null}
            onPrevious={() => selectAdjacent(-1)}
            onNext={() => selectAdjacent(1)}
            onSeek={seekBy}
            onNudge={nudgeSelected}
            onAccept={() => {
              if (selectedEvent !== undefined)
                decideEvent(selectedEvent, "accept");
            }}
            onDismiss={dismissSelected}
            onAddEvent={addEvent}
          />
          <EventSourceSurface
            recordingId={recordingId}
            requestedTimeUs={playheadUs}
            durationUs={durationUs}
            watchedPercent={watchedPercent}
            watchedThroughUs={watchedThroughUs}
            coverageComplete={coverageComplete}
            onAddEvent={addEvent}
            onMarkCoverage={() => setCoverageComplete(true)}
            showCoverageControls={onRailItemsChange === undefined}
          />
        </div>

        {notice !== null ? (
          <p className={styles.recordingNotice} role="status">
            {notice}
          </p>
        ) : null}
        {inspectorSlots === null && error !== null ? (
          <div className={eventStyles.error} role="alert">
            <p>
              {saveState === "conflict"
                ? `Conflict: the first unapplied command is ${firstUnappliedCommand ?? "unknown"}. ${error}`
                : error}
            </p>
          </div>
        ) : null}
      </section>
    </>
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

function selectGeneratedEvent(
  events: PipelineEvent[],
  itemId: string | null,
  timeUs: number | null,
): PipelineEvent | undefined {
  if (events.length === 0) return undefined;
  const byId =
    itemId === null
      ? undefined
      : events.find((event) => event.event_id === itemId);
  if (byId !== undefined) return byId;
  if (timeUs === null) return events[0];
  return events.reduce((closest, event) =>
    Math.abs(event.start_us - timeUs) < Math.abs(closest.start_us - timeUs)
      ? event
      : closest,
  );
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
    eventType !== CARD_STATE_CHANGED_EVENT_TYPE ||
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
  window.dispatchEvent(new PopStateEvent("popstate"));
}
