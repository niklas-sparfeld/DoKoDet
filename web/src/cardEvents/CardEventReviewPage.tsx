import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type CardEvent,
  type CardEventCommandRequest,
  type CardEventReviewResource,
  type RecordingDetail,
} from "../api/client";
import { RecordingSection, recordingPagePath } from "../recordings";
import styles from "../App.module.css";

const CARD_EVENT_TYPES = [
  "card_played",
  "trick_cleared",
  "card_moved",
  "card_removed",
  "card_returned",
  "multiple_cards_dropped",
  "anomalous_state_change",
] as const;

const CARD_EVENT_CONFIDENCES = [
  "confirmed",
  "uncertain",
  "ignore",
  "proposed",
] as const;

type EventAction = CardEventCommandRequest["action"];
type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";
type EditableEvent = CardEvent & { localId: string };
type UpdateCommand = {
  kind: "update";
  clientCommandId: string;
  eventId: string;
  action: EventAction;
  effectiveTime?: number;
  type?: string;
  confidence?: string | null;
  notes?: string | null;
  notice: string;
  attempts: number;
};
type AddCommand = {
  kind: "add";
  clientCommandId: string;
  localEventId: string;
  effectiveTime: number;
  type: string;
  confidence: string | null;
  notes: string | null;
  notice: string;
  attempts: number;
};
type PendingCommand = UpdateCommand | AddCommand;

const EVENT_TYPE_GUIDANCE: Record<string, string> = {
  card_played: "A card reaches its final position in the trick area.",
  trick_cleared: "The cards from the completed trick leave the play area.",
  card_moved: "An existing card changes position without being played.",
  card_removed: "A card leaves the visible play area for another reason.",
  card_returned: "A card returns to a hand or another known area.",
  multiple_cards_dropped: "Several cards enter the play area together.",
  anomalous_state_change:
    "A visible state change does not match the other types.",
};

export function CardEventReviewPage({ reviewId }: { reviewId: string }) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const reviewRef = useRef<CardEventReviewResource | null>(null);
  const eventsRef = useRef<EditableEvent[]>([]);
  const selectedEventIdRef = useRef<string | null>(null);
  const videoEventListRef = useRef<HTMLOListElement>(null);
  const playheadRef = useRef(0);
  const serverRevisionRef = useRef(0);
  const commandSequenceRef = useRef(0);
  const queueRef = useRef<PendingCommand[]>([]);
  const processingRef = useRef(false);
  const inFlightCommandIdRef = useRef<string | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const processQueueRef = useRef<(() => void) | null>(null);
  const removedEventRef = useRef<EditableEvent | null>(null);
  const [review, setReview] = useState<CardEventReviewResource | null>(null);
  const [recording, setRecording] = useState<RecordingDetail | null>(null);
  const [events, setEvents] = useState<EditableEvent[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [duration, setDuration] = useState(0);
  const [watchedThrough, setWatchedThrough] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [queueLength, setQueueLength] = useState(0);
  const [firstUnappliedCommand, setFirstUnappliedCommand] = useState<
    string | null
  >(null);
  const [reviewerName, setReviewerName] = useState("");
  const [completionBusy, setCompletionBusy] = useState(false);
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [removedEvent, setRemovedEvent] = useState<EditableEvent | null>(null);

  const setSelected = useCallback((eventId: string | null) => {
    selectedEventIdRef.current = eventId;
    setSelectedEventId(eventId);
  }, []);

  const setLocalEvents = useCallback((nextEvents: EditableEvent[]) => {
    const sorted = [...nextEvents].sort(
      (first, second) => first.effective_time_s - second.effective_time_s,
    );
    eventsRef.current = sorted;
    setEvents(sorted);
  }, []);

  const hydrate = useCallback(
    (nextReview: CardEventReviewResource) => {
      const nextEvents = nextReview.events.map((event) => ({
        ...event,
        localId: event.event_id,
      }));
      reviewRef.current = nextReview;
      serverRevisionRef.current = nextReview.draft_revision;
      setReview(nextReview);
      setLocalEvents(nextEvents);
      setSelected(
        selectedEventIdRef.current !== null &&
          nextEvents.some(
            (event) => event.localId === selectedEventIdRef.current,
          )
          ? selectedEventIdRef.current
          : (nextEvents[0]?.localId ?? null),
      );
      setReviewerName(
        (current) => current || nextReview.reviewer || nextReview.operator,
      );
    },
    [setLocalEvents, setSelected],
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const nextReview = await client.getCardEventReviewResource(reviewId, {
          signal,
        });
        const nextRecording = await client.getRecording(
          nextReview.recording_id,
          {
            signal,
          },
        );
        if (!signal?.aborted) {
          hydrate(nextReview);
          setRecording(nextRecording);
          const mediaDuration = nextRecording.video.media_facts?.duration_ms;
          if (mediaDuration !== null && mediaDuration !== undefined) {
            setDuration(mediaDuration / 1000);
          }
          setError(null);
          setSaveState("saved");
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeReviewPageError(reason));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client, hydrate, reviewId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (retryTimerRef.current !== null)
        window.clearTimeout(retryTimerRef.current);
    };
  }, [load]);

  useEffect(() => {
    const video = videoRef.current;
    if (video === null) return;
    const updateTime = () => {
      const current = Number.isFinite(video.currentTime)
        ? Math.max(0, video.currentTime)
        : 0;
      playheadRef.current = current;
      setPlayhead(current);
      setWatchedThrough((previous) => Math.max(previous, current));
      if (Number.isFinite(video.duration) && video.duration > 0) {
        setDuration(video.duration);
      }
    };
    video.addEventListener("timeupdate", updateTime);
    video.addEventListener("loadedmetadata", updateTime);
    video.addEventListener("ended", updateTime);
    updateTime();
    return () => {
      video.removeEventListener("timeupdate", updateTime);
      video.removeEventListener("loadedmetadata", updateTime);
      video.removeEventListener("ended", updateTime);
    };
  }, [recording]);

  const setCurrentTime = useCallback(
    (time: number) => {
      const maximum = duration > 0 ? duration : Number.POSITIVE_INFINITY;
      const nextTime = Math.max(0, Math.min(maximum, time));
      if (videoRef.current !== null) videoRef.current.currentTime = nextTime;
      playheadRef.current = nextTime;
      setPlayhead(nextTime);
    },
    [duration],
  );

  const selectEvent = useCallback(
    (event: EditableEvent, seek = true) => {
      setSelected(event.localId);
      if (seek) setCurrentTime(event.effective_time_s);
    },
    [setCurrentTime, setSelected],
  );

  const updateOptimisticEvent = useCallback(
    (command: UpdateCommand) => {
      const nextEvents = eventsRef.current.flatMap((event) => {
        if (event.localId !== command.eventId) return [event];
        if (command.action === "remove") return [];
        const next = { ...event };
        if (command.action === "accept") {
          next.state = "reviewed";
          if (next.confidence === "proposed") next.confidence = "confirmed";
        } else if (command.action === "dismiss") {
          next.state = "dismissed";
          next.confidence = "ignore";
        } else if (command.action === "undo") {
          next.state = "proposed";
          next.confidence = "proposed";
        } else if (command.action === "retime") {
          next.effective_time_s =
            command.effectiveTime ?? next.effective_time_s;
          if (next.state === "proposed") {
            next.state = "reviewed";
            if (next.confidence === "proposed") next.confidence = "confirmed";
          }
        } else if (command.action === "edit") {
          if (command.type !== undefined) next.type = command.type;
          if (command.confidence !== undefined)
            next.confidence = command.confidence;
          if (command.notes !== undefined) next.notes = command.notes;
          if (next.state === "proposed") {
            next.state = "reviewed";
            if (next.confidence === "proposed") next.confidence = "confirmed";
          }
        }
        return [next];
      });
      setLocalEvents(nextEvents);
    },
    [setLocalEvents],
  );

  const updateLocalReviewRevision = useCallback((revision: number) => {
    serverRevisionRef.current = revision;
    setReview((current) =>
      current === null ? current : { ...current, draft_revision: revision },
    );
    if (reviewRef.current !== null) {
      reviewRef.current = { ...reviewRef.current, draft_revision: revision };
    }
  }, []);

  const processQueue = useCallback(async () => {
    if (processingRef.current || queueRef.current.length === 0) {
      if (queueRef.current.length === 0 && saveState !== "conflict") {
        setQueueLength(0);
        setSaveState("saved");
      }
      return;
    }
    const currentReview = reviewRef.current;
    const command = queueRef.current[0];
    if (currentReview === null || currentReview.review_state === "completed")
      return;
    processingRef.current = true;
    inFlightCommandIdRef.current = command.clientCommandId;
    try {
      const expectedRevision = serverRevisionRef.current;
      const response =
        command.kind === "add"
          ? await client.addCardEvent(reviewId, {
              client_command_id: command.clientCommandId,
              expected_revision: expectedRevision,
              effective_time_s: command.effectiveTime,
              type: command.type,
              confidence: command.confidence,
              notes: command.notes,
            })
          : await client.updateCardEvent(reviewId, command.eventId, {
              client_command_id: command.clientCommandId,
              expected_revision: expectedRevision,
              action: command.action,
              ...(command.effectiveTime === undefined
                ? {}
                : { effective_time_s: command.effectiveTime }),
              ...(command.type === undefined ? {} : { type: command.type }),
              ...(command.confidence === undefined
                ? {}
                : { confidence: command.confidence }),
              ...(command.notes === undefined ? {} : { notes: command.notes }),
            });
      updateLocalReviewRevision(response.draft_revision);
      if (response.changed_event !== null) {
        const changed = { ...response.changed_event };
        if (command.kind === "add") {
          const localChanged = { ...changed, localId: command.localEventId };
          setLocalEvents(
            eventsRef.current.map((event) =>
              event.localId === command.localEventId ? localChanged : event,
            ),
          );
          for (const queued of queueRef.current.slice(1)) {
            if (
              queued.kind === "update" &&
              queued.eventId === command.localEventId
            ) {
              queued.eventId = localChanged.event_id;
            }
          }
        } else {
          setLocalEvents(
            eventsRef.current.map((event) =>
              event.localId === command.eventId
                ? { ...changed, localId: event.localId }
                : event,
            ),
          );
        }
      }
      queueRef.current.shift();
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(
        queueRef.current.length > 0
          ? describeCommand(queueRef.current[0])
          : null,
      );
      setNotice(command.notice);
      setError(null);
      command.attempts = 0;
    } catch (reason: unknown) {
      command.attempts += 1;
      processingRef.current = false;
      inFlightCommandIdRef.current = null;
      if (isConflictError(reason)) {
        setSaveState("conflict");
        setError(describeReviewPageError(reason));
        return;
      }
      if (command.attempts <= 3) {
        setSaveState("retrying");
        setError(describeReviewPageError(reason));
        retryTimerRef.current = window.setTimeout(
          () => {
            retryTimerRef.current = null;
            void processQueueRef.current?.();
          },
          Math.min(1000, 250 * command.attempts),
        );
        return;
      }
      setSaveState("error");
      setError(describeReviewPageError(reason));
      return;
    }
    processingRef.current = false;
    inFlightCommandIdRef.current = null;
    if (queueRef.current.length > 0) {
      setSaveState("saving");
      void processQueueRef.current?.();
    } else {
      setSaveState("saved");
    }
  }, [client, reviewId, saveState, setLocalEvents, updateLocalReviewRevision]);

  useEffect(() => {
    processQueueRef.current = processQueue;
    return () => {
      if (processQueueRef.current === processQueue)
        processQueueRef.current = null;
    };
  }, [processQueue]);

  const enqueue = useCallback(
    (command: PendingCommand, optimisticEvent?: EditableEvent) => {
      if (
        reviewRef.current?.review_state === "completed" ||
        saveState === "conflict"
      )
        return;
      if (optimisticEvent !== undefined)
        setLocalEvents([...eventsRef.current, optimisticEvent]);
      else if (command.kind === "update") updateOptimisticEvent(command);
      const firstQueuedIndex = inFlightCommandIdRef.current === null ? 0 : 1;
      if (
        command.kind === "update" &&
        (command.action === "retime" || command.action === "edit")
      ) {
        let coalescedIndex = -1;
        for (
          let index = queueRef.current.length - 1;
          index >= firstQueuedIndex;
          index -= 1
        ) {
          const queued = queueRef.current[index];
          if (
            queued.kind === "update" &&
            queued.eventId === command.eventId &&
            queued.action === command.action
          ) {
            coalescedIndex = index;
            break;
          }
        }
        if (coalescedIndex >= 0) {
          const previous = queueRef.current[coalescedIndex];
          queueRef.current[coalescedIndex] =
            command.action === "edit" && previous.kind === "update"
              ? {
                  ...previous,
                  ...command,
                  type: command.type ?? previous.type,
                  confidence: command.confidence ?? previous.confidence,
                  notes: command.notes ?? previous.notes,
                }
              : command;
        } else queueRef.current.push(command);
      } else queueRef.current.push(command);
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(describeCommand(queueRef.current[0]));
      setSaveState("saving");
      setError(null);
      void processQueueRef.current?.();
    },
    [saveState, setLocalEvents, updateOptimisticEvent],
  );

  const nextCommandId = useCallback(() => {
    commandSequenceRef.current += 1;
    return `cardevent-command-${Date.now()}-${commandSequenceRef.current}`;
  }, []);

  const queueUpdate = useCallback(
    (
      event: EditableEvent,
      action: EventAction,
      changes: Pick<
        UpdateCommand,
        "effectiveTime" | "type" | "confidence" | "notes"
      > = {},
      notice: string,
    ) => {
      enqueue({
        kind: "update",
        clientCommandId: nextCommandId(),
        eventId: event.localId,
        action,
        ...changes,
        notice,
        attempts: 0,
      });
    },
    [enqueue, nextCommandId],
  );

  const addEvent = useCallback(() => {
    if (reviewRef.current?.review_state === "completed") return;
    const localId = `local-event-${Date.now()}-${commandSequenceRef.current + 1}`;
    const event: EditableEvent = {
      event_id: localId,
      localId,
      effective_time_s: clampTime(playheadRef.current, duration),
      type: "card_played",
      confidence: "confirmed",
      notes: null,
      state: "reviewed",
      origin: "manual",
      proposal: null,
    };
    setSelected(localId);
    enqueue(
      {
        kind: "add",
        clientCommandId: nextCommandId(),
        localEventId: localId,
        effectiveTime: event.effective_time_s,
        type: event.type,
        confidence: event.confidence,
        notes: event.notes ?? null,
        notice: "Event added at the playhead.",
        attempts: 0,
      },
      event,
    );
  }, [duration, enqueue, nextCommandId, setSelected]);

  const jumpToAdjacentMarker = useCallback(
    (direction: "previous" | "next") => {
      const ordered = [...eventsRef.current].sort(
        (first, second) => first.effective_time_s - second.effective_time_s,
      );
      const currentTime = playheadRef.current;
      const marker =
        direction === "previous"
          ? [...ordered]
              .reverse()
              .find((event) => event.effective_time_s < currentTime - 0.001)
          : ordered.find(
              (event) => event.effective_time_s > currentTime + 0.001,
            );
      if (marker !== undefined) selectEvent(marker);
    },
    [selectEvent],
  );

  const selectedEvent = events.find(
    (event) => event.localId === selectedEventId,
  );
  const selected = selectedEventId === null ? undefined : selectedEvent;
  const frameRate = recording?.video.media_facts?.nominal_frame_rate ?? 0;
  const isCompleted = review?.review_state === "completed";
  const isEditable = !isCompleted && saveState !== "conflict";
  const fullVideoReady =
    review?.full_video_acknowledged === true ||
    (duration > 0 &&
      watchedThrough >=
        Math.max(
          0,
          duration - Math.max(0.5, frameRate > 0 ? 1 / frameRate : 0.5),
        ));
  const proposedCount = events.filter(
    (event) => event.state === "proposed",
  ).length;
  const reviewedCount = events.filter(
    (event) => event.state === "reviewed",
  ).length;
  const dismissedCount = events.filter(
    (event) => event.state === "dismissed",
  ).length;
  const canMarkReviewComplete =
    isEditable &&
    fullVideoReady &&
    proposedCount === 0 &&
    reviewerName.trim() !== "" &&
    queueLength === 0 &&
    saveState === "saved" &&
    !completionBusy;
  const completionRequirement = !fullVideoReady
    ? "Watch or seek to the end of the recording before marking this review complete."
    : proposedCount > 0
      ? `${proposedCount} proposed event${proposedCount === 1 ? "" : "s"} still need a decision.`
      : queueLength > 0 || saveState === "saving" || saveState === "retrying"
        ? "Wait for the current timeline changes to save."
        : saveState !== "saved"
          ? "Resolve the timeline save problem before marking this review complete."
          : reviewerName.trim() === ""
            ? "Enter the reviewer name to mark this review complete."
            : null;
  const timelineDuration = duration > 0 ? duration : 1;
  const {
    captureVideoRef,
    captureCanvasRef,
    screenshots,
    unavailableScreenshots,
  } = useEventScreenshots(recording?.video.url ?? "", events, duration);

  useEffect(() => {
    if (selectedEventId === null) return;
    const selectedItem = videoEventListRef.current?.querySelector<HTMLElement>(
      `[data-event-id="${selectedEventId}"]`,
    );
    selectedItem?.scrollIntoView?.({ block: "nearest" });
  }, [selectedEventId]);

  const removeSelected = useCallback(() => {
    const current =
      selectedEventIdRef.current === null
        ? undefined
        : eventsRef.current.find(
            (event) => event.localId === selectedEventIdRef.current,
          );
    if (
      !isEditable ||
      current === undefined ||
      (current.proposal !== null && current.state !== "reviewed")
    )
      return;
    removedEventRef.current = current;
    setRemovedEvent(current);
    const remaining = eventsRef.current.filter(
      (event) => event.localId !== current.localId,
    );
    setLocalEvents(remaining);
    setSelected(remaining[0]?.localId ?? null);
    queueUpdate(
      current,
      "remove",
      {},
      "Event removed. You can undo this action.",
    );
  }, [isEditable, queueUpdate, setLocalEvents, setSelected]);

  const undoRemoval = useCallback(() => {
    const removed = removedEventRef.current;
    if (!isEditable || removed === null) return;
    const pendingIndex = queueRef.current.findIndex(
      (command) =>
        command.kind === "update" &&
        command.eventId === removed.localId &&
        command.action === "remove",
    );
    if (pendingIndex >= 0 && pendingIndex !== 0) {
      queueRef.current.splice(pendingIndex, 1);
      setLocalEvents([...eventsRef.current, removed]);
      setSelected(removed.localId);
      setQueueLength(queueRef.current.length);
      removedEventRef.current = null;
      setRemovedEvent(null);
      return;
    }
    const localId = `local-event-${Date.now()}-${commandSequenceRef.current + 1}`;
    const restored = { ...removed, localId, event_id: localId };
    setSelected(localId);
    enqueue(
      {
        kind: "add",
        clientCommandId: nextCommandId(),
        localEventId: localId,
        effectiveTime: restored.effective_time_s,
        type: restored.type,
        confidence: restored.confidence,
        notes: restored.notes ?? null,
        notice: "Event restored.",
        attempts: 0,
      },
      restored,
    );
    removedEventRef.current = null;
    setRemovedEvent(null);
  }, [enqueue, isEditable, nextCommandId, setLocalEvents, setSelected]);

  const completeReview = useCallback(async () => {
    const current = reviewRef.current;
    if (
      !isEditable ||
      current === null ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      !fullVideoReady ||
      proposedCount > 0 ||
      reviewerName.trim() === "" ||
      saveState !== "saved"
    )
      return;
    setCompletionBusy(true);
    setSaveState("saving");
    try {
      const completed = await client.completeCardEventReviewResource(reviewId, {
        reviewer: reviewerName.trim(),
        expected_revision: serverRevisionRef.current,
        full_video_acknowledged: true,
      });
      hydrate(completed);
      setSaveState("saved");
      setNotice(
        `Reviewed version ${completed.completed_version_id ?? "published"} is immutable.`,
      );
    } catch (reason: unknown) {
      setSaveState(isConflictError(reason) ? "conflict" : "error");
      setError(describeReviewPageError(reason));
    } finally {
      setCompletionBusy(false);
    }
  }, [
    client,
    fullVideoReady,
    hydrate,
    isEditable,
    proposedCount,
    reviewId,
    reviewerName,
    saveState,
  ]);

  const startRevision = useCallback(async () => {
    const current = reviewRef.current;
    if (
      current === null ||
      current.review_state !== "completed" ||
      current.completed_version_id === null
    )
      return;
    setRevisionBusy(true);
    setSaveState("saving");
    setError(null);
    try {
      const collection = await client.listCardEventReviews(
        current.recording_id,
      );
      const existingDraft = collection.reviews.find(
        (item) => item.review_state === "draft",
      );
      const revision =
        existingDraft === undefined
          ? await client.createCardEventReview(current.recording_id, {
              operator: current.operator,
              parent_review_id: current.review_id,
            })
          : existingDraft;
      setRevisionBusy(false);
      window.history.pushState({}, "", revision.review_url);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (reason: unknown) {
      setRevisionBusy(false);
      setSaveState(isConflictError(reason) ? "conflict" : "error");
      setError(describeReviewPageError(reason));
    }
  }, [client]);

  const reloadWinningDraft = useCallback(async () => {
    try {
      const winning = await client.getCardEventReviewResource(reviewId);
      queueRef.current = [];
      setQueueLength(0);
      setFirstUnappliedCommand(null);
      processingRef.current = false;
      inFlightCommandIdRef.current = null;
      hydrate(winning);
      setSaveState("saved");
      setError(null);
      setNotice("Winning draft loaded. Queued local commands were discarded.");
    } catch (reason: unknown) {
      setSaveState("error");
      setError(describeReviewPageError(reason));
    }
  }, [client, hydrate, reviewId]);

  const retryQueue = useCallback(() => {
    if (queueRef.current.length === 0) return;
    queueRef.current[0].attempts = 0;
    setSaveState("saving");
    setError(null);
    void processQueueRef.current?.();
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      )
        return;
      if (event.key === " ") {
        event.preventDefault();
        const video = videoRef.current;
        if (video === null) return;
        if (video.paused) void video.play().catch(() => undefined);
        else video.pause();
      } else if (
        event.altKey &&
        (event.key === "ArrowLeft" || event.key === "ArrowRight")
      ) {
        event.preventDefault();
        jumpToAdjacentMarker(event.key === "ArrowLeft" ? "previous" : "next");
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        setCurrentTime(
          playheadRef.current +
            (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 2 : 0.25),
        );
      } else if (event.key === "a" || event.key === "A") {
        event.preventDefault();
        const current =
          selectedEventIdRef.current === null
            ? undefined
            : eventsRef.current.find(
                (item) => item.localId === selectedEventIdRef.current,
              );
        if (current?.proposal !== null && current?.state === "proposed")
          queueUpdate(current, "accept", {}, "Proposal accepted.");
      } else if (event.key === "d" || event.key === "D") {
        event.preventDefault();
        const current =
          selectedEventIdRef.current === null
            ? undefined
            : eventsRef.current.find(
                (item) => item.localId === selectedEventIdRef.current,
              );
        if (current?.proposal !== null && current?.state === "proposed")
          queueUpdate(current, "dismiss", {}, "Proposal dismissed.");
      } else if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        addEvent();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removeSelected();
      } else if (event.key === "," || event.key === ".") {
        event.preventDefault();
        const current =
          selectedEventIdRef.current === null
            ? undefined
            : eventsRef.current.find(
                (item) => item.localId === selectedEventIdRef.current,
              );
        if (current !== undefined && frameRate > 0) {
          queueUpdate(
            current,
            "retime",
            {
              effectiveTime: clampTime(
                current.effective_time_s +
                  (event.key === "," ? -1 : 1) / frameRate,
              ),
            },
            event.key === ","
              ? "Event nudged one frame earlier."
              : "Event nudged one frame later.",
          );
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    addEvent,
    frameRate,
    jumpToAdjacentMarker,
    queueUpdate,
    removeSelected,
    setCurrentTime,
  ]);

  if (loading && (review === null || recording === null)) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <a className={styles.backLink} href="/">
          ← Recordings
        </a>
        <p className={styles.loading} aria-live="polite">
          Loading CardEvent review…
        </p>
      </main>
    );
  }
  if (error !== null && (review === null || recording === null)) {
    return (
      <main className={`${styles.shell} ${styles.recordingsPage}`}>
        <a className={styles.backLink} href="/">
          ← Recordings
        </a>
        <section className={styles.panel} role="alert">
          <p className={styles.statusLabel}>Unable to load CardEvent review</p>
          <p>{error}</p>
        </section>
      </main>
    );
  }
  if (review === null || recording === null) return null;

  return (
    <main
      className={`${styles.shell} ${styles.recordingsPage} ${styles.cardEventReviewPage}`}
    >
      <a
        className={styles.backLink}
        href={recordingPagePath(recording.recording_id)}
      >
        ← Recording
      </a>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector · CardEvent review</p>
          <h1>CardEvent review</h1>
          <p className={styles.detailContext}>
            {recording.round_id} · Recording {recording.recording_id}
          </p>
        </div>
        <div className={styles.nextAction}>
          <span className={styles.statusLabel}>Review status</span>
          <strong>
            <ReviewStateBadge value={review.review_state} />
          </strong>
        </div>
      </header>

      <section
        className={styles.detailPanel}
        aria-label="CardEvent review summary"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Review resource</p>
            <h2>{isCompleted ? "Completed review" : "Draft review"}</h2>
          </div>
          <span className={styles.countLabel}>
            {events.length} event{events.length === 1 ? "" : "s"}
          </span>
        </div>
        <p className={styles.detailLead}>
          {isCompleted
            ? "This completed version is read-only to preserve its lineage. Start a revision below to edit or remove events; the recording remains unchanged."
            : "Use the unified event table for a fast review loop. Changes appear at once and save in order."}
        </p>
        <dl className={styles.cardEventReviewPageMetadata}>
          <ReviewMetadata label="Operator" value={review.operator} />
          <ReviewMetadata
            label="Created"
            value={formatTimestamp(review.created_at)}
          />
          <ReviewMetadata
            label="Updated"
            value={formatTimestamp(review.updated_at)}
          />
          <ReviewMetadata
            label="Reviewer"
            value={review.reviewer ?? "Not completed"}
          />
          <ReviewMetadata
            label="Completed"
            value={
              review.completed_at === null
                ? "Not completed"
                : formatTimestamp(review.completed_at)
            }
          />
          <ReviewMetadata
            label="Parent review"
            value={review.parent_review_id ?? "Initial review"}
          />
        </dl>
        <details className={styles.sourceDetails}>
          <summary>Technical review details</summary>
          <dl className={styles.cardEventReviewPageMetadata}>
            <ReviewMetadata label="Review ID" value={review.review_id} />
            <ReviewMetadata
              label="Source asset"
              value={review.source_asset_id}
            />
            <ReviewMetadata
              label="Source digest"
              value={review.source_sha256}
            />
            <ReviewMetadata
              label="Draft revision"
              value={String(review.draft_revision)}
            />
            <ReviewMetadata
              label="Parent version"
              value={review.parent_version_id ?? "Not available"}
            />
            <ReviewMetadata
              label="Completed version"
              value={review.completed_version_id ?? "Not available"}
            />
          </dl>
        </details>
      </section>

      <RecordingSection
        recording={recording}
        videoRef={videoRef}
        videoAside={
          <aside
            className={styles.cardEventVideoNavigator}
            aria-label="Event navigator"
          >
            <div className={styles.cardEventVideoNavigatorHeader}>
              <div>
                <p className={styles.statusLabel}>Current event</p>
                <h3>Event navigator</h3>
              </div>
              <span className={styles.countLabel}>
                {events.length} event{events.length === 1 ? "" : "s"}
              </span>
            </div>
            {selected === undefined ? (
              <p className={styles.cardEventVideoNavigatorEmpty}>
                No event is selected.
              </p>
            ) : (
              <>
                <p className={styles.cardEventVideoCurrent} aria-live="polite">
                  <strong>{formatTime(selected.effective_time_s)}</strong>
                  <span>
                    {formatIdentifier(selected.type)} ·{" "}
                    {formatIdentifier(selected.state)}
                  </span>
                </p>
                <div className={styles.cardEventVideoEditor}>
                  <label>
                    Time (seconds)
                    <input
                      type="number"
                      min="0"
                      max={duration > 0 ? duration : undefined}
                      step="0.001"
                      value={selected.effective_time_s}
                      disabled={!isEditable}
                      onChange={(input) => {
                        const value = Number(input.target.value);
                        if (Number.isFinite(value))
                          setLocalEvents(
                            eventsRef.current.map((event) =>
                              event.localId === selected.localId
                                ? { ...event, effective_time_s: value }
                                : event,
                            ),
                          );
                      }}
                      onBlur={() => {
                        const current = eventsRef.current.find(
                          (event) => event.localId === selected.localId,
                        );
                        if (current !== undefined && isEditable)
                          queueUpdate(
                            current,
                            "retime",
                            { effectiveTime: current.effective_time_s },
                            "Event time updated.",
                          );
                      }}
                      aria-label="Time in event navigator"
                    />
                  </label>
                  <label>
                    Event type
                    <select
                      value={selected.type}
                      disabled={!isEditable}
                      onChange={(input) =>
                        queueUpdate(
                          selected,
                          "edit",
                          { type: input.target.value },
                          "Event type updated.",
                        )
                      }
                      aria-label="Event type in event navigator"
                    >
                      {CARD_EVENT_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {formatIdentifier(type)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <details className={styles.cardEventVideoMoreFields}>
                    <summary>More event fields</summary>
                    <label>
                      Confidence
                      <select
                        value={selected.confidence ?? ""}
                        disabled={!isEditable}
                        onChange={(input) =>
                          queueUpdate(
                            selected,
                            "edit",
                            {
                              confidence:
                                input.target.value === ""
                                  ? null
                                  : input.target.value,
                            },
                            "Event confidence updated.",
                          )
                        }
                        aria-label="Confidence in event navigator"
                      >
                        <option value="">Not set</option>
                        {CARD_EVENT_CONFIDENCES.map((confidence) => (
                          <option key={confidence} value={confidence}>
                            {formatIdentifier(confidence)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Notes
                      <textarea
                        rows={2}
                        value={selected.notes ?? ""}
                        disabled={!isEditable}
                        onChange={(input) =>
                          setLocalEvents(
                            eventsRef.current.map((event) =>
                              event.localId === selected.localId
                                ? { ...event, notes: input.target.value }
                                : event,
                            ),
                          )
                        }
                        onBlur={() => {
                          const current = eventsRef.current.find(
                            (event) => event.localId === selected.localId,
                          );
                          if (current !== undefined && isEditable)
                            queueUpdate(
                              current,
                              "edit",
                              { notes: current.notes },
                              "Event notes updated.",
                            );
                        }}
                        aria-label="Notes in event navigator"
                      />
                    </label>
                  </details>
                  {selected.state === "proposed" ? (
                    <div className={styles.cardEventVideoActions}>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() =>
                          queueUpdate(
                            selected,
                            "accept",
                            {},
                            "Proposal accepted.",
                          )
                        }
                        disabled={!isEditable}
                      >
                        Accept
                      </button>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() =>
                          queueUpdate(
                            selected,
                            "dismiss",
                            {},
                            "Proposal dismissed.",
                          )
                        }
                        disabled={!isEditable}
                      >
                        Dismiss
                      </button>
                    </div>
                  ) : selected.proposal !== null ? (
                    <div className={styles.cardEventVideoActions}>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() =>
                          queueUpdate(
                            selected,
                            "undo",
                            {},
                            "Proposal decision undone.",
                          )
                        }
                        disabled={!isEditable}
                      >
                        Undo decision
                      </button>
                    </div>
                  ) : null}
                </div>
              </>
            )}
            <ol ref={videoEventListRef} className={styles.cardEventVideoList}>
              {events.map((event, index) => (
                <li key={event.localId} data-event-id={event.localId}>
                  <button
                    type="button"
                    data-selected={event.localId === selectedEventId}
                    aria-current={
                      event.localId === selectedEventId ? "true" : undefined
                    }
                    aria-label={`Open event ${index + 1} at ${formatTime(event.effective_time_s)}`}
                    onClick={() => selectEvent(event)}
                  >
                    <span>
                      <strong>{formatTime(event.effective_time_s)}</strong>
                      {formatIdentifier(event.type)}
                    </span>
                    <small>{formatIdentifier(event.state)}</small>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
        }
      />

      <section
        className={styles.cardEventReviewPanel}
        aria-label="CardEvent editor"
      >
        <div className={styles.cardEventScreenshotCapture} aria-hidden="true">
          <video
            ref={captureVideoRef}
            preload="metadata"
            muted
            src={recording.video.url}
          />
          <canvas ref={captureCanvasRef} />
        </div>
        <div className={styles.cardEventToolbar}>
          <div className={styles.cardEventTransport}>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => setCurrentTime(playhead - 2)}
            >
              −2 s
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => setCurrentTime(playhead - 0.25)}
            >
              −250 ms
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => setCurrentTime(playhead + 0.25)}
            >
              +250 ms
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => setCurrentTime(playhead + 2)}
            >
              +2 s
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => jumpToAdjacentMarker("previous")}
            >
              Previous marker
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={() => jumpToAdjacentMarker("next")}
            >
              Next marker
            </button>
            {!isCompleted ? (
              <button
                className={styles.primaryButton}
                type="button"
                onClick={addEvent}
              >
                Add event at playhead
              </button>
            ) : null}
          </div>
          <div className={styles.cardEventSaveStatus} aria-live="polite">
            <span data-state={saveState}>
              {saveState === "saving"
                ? "Saving"
                : saveState === "retrying"
                  ? "Retrying"
                  : saveState === "conflict"
                    ? "Conflict"
                    : saveState === "error"
                      ? "Not saved"
                      : "Saved"}
            </span>
            {queueLength > 0
              ? ` · ${queueLength} queued`
              : ` · revision ${review.draft_revision}`}
          </div>
        </div>

        <div className={styles.cardEventTimelineHeader}>
          <div>
            <p className={styles.statusLabel}>Timeline rail</p>
            <p className={styles.cardEventTimeRange}>
              Playhead {formatTime(playhead)} · 0:00.000–
              {formatTime(timelineDuration)}
            </p>
          </div>
          <span className={styles.countLabel}>
            {events.length} event{events.length === 1 ? "" : "s"}
          </span>
          <span className={styles.shortcutLabel}>Alt+Right then A or D</span>
        </div>
        <div
          className={styles.cardEventRail}
          role="group"
          aria-label="CardEvent timeline markers"
        >
          <span className={styles.cardEventRailTrack} />
          <span
            className={styles.cardEventPlayhead}
            style={{
              left: `${(clampTime(playhead, timelineDuration) / timelineDuration) * 100}%`,
            }}
            aria-hidden="true"
          />
          {events.map((event, index) => (
            <button
              key={event.localId}
              className={styles.cardEventMarker}
              data-selected={event.localId === selectedEventId}
              data-state={event.state}
              style={{
                left: `${(clampTime(event.effective_time_s, timelineDuration) / timelineDuration) * 100}%`,
              }}
              type="button"
              title={`Event ${index + 1} at ${formatTime(event.effective_time_s)}`}
              aria-label={`Select event ${index + 1} at ${formatTime(event.effective_time_s)} seconds`}
              onClick={() => selectEvent(event)}
            />
          ))}
        </div>

        <div className={styles.cardEventReviewCounts} aria-label="Event counts">
          <ReviewCount label="Reviewed" value={reviewedCount} />
          <ReviewCount label="Proposed" value={proposedCount} />
          <ReviewCount label="Dismissed" value={dismissedCount} />
        </div>
        <div className={styles.tableScroller}>
          <table
            className={`${styles.cardEventReviewTable} ${styles.cardEventUnifiedTable}`}
          >
            <caption className={styles.visuallyHidden}>
              Unified time-ordered CardEvent review events
            </caption>
            <thead>
              <tr>
                <th scope="col">Screenshot</th>
                <th scope="col">Time</th>
                <th scope="col">Type</th>
                <th scope="col">State</th>
                <th scope="col">Origin</th>
                <th scope="col">Lineage</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr
                  key={event.localId}
                  data-state={event.state}
                  data-selected={event.localId === selectedEventId}
                >
                  <td className={styles.cardEventScreenshotCell}>
                    <button
                      className={styles.cardEventScreenshotButton}
                      type="button"
                      onClick={() => selectEvent(event)}
                      aria-label={`Open screenshot for event at ${formatTime(event.effective_time_s)}`}
                    >
                      {screenshots[event.localId]?.time_s ===
                      event.effective_time_s ? (
                        <img
                          className={styles.cardEventScreenshot}
                          src={screenshots[event.localId].src}
                          alt={`Screenshot at ${formatTime(event.effective_time_s)}`}
                        />
                      ) : unavailableScreenshots[event.localId]?.time_s ===
                        event.effective_time_s ? (
                        <span className={styles.cardEventScreenshotPlaceholder}>
                          Unavailable
                        </span>
                      ) : (
                        <span className={styles.cardEventScreenshotPlaceholder}>
                          Preparing…
                        </span>
                      )}
                    </button>
                  </td>
                  <td>
                    <button
                      className={styles.cardEventTableSelect}
                      type="button"
                      onClick={() => selectEvent(event)}
                    >
                      {formatTime(event.effective_time_s)}
                    </button>
                  </td>
                  <td>{formatIdentifier(event.type)}</td>
                  <td>
                    <ReviewStateBadge value={event.state} />
                  </td>
                  <td>{formatIdentifier(event.origin)}</td>
                  <td>
                    {event.proposal === null
                      ? "Manual"
                      : event.proposal.proposal_id}
                  </td>
                  <td>
                    <div className={styles.cardEventCommandActions}>
                      {event.state === "proposed" ? (
                        <>
                          <button
                            className={styles.secondaryButton}
                            type="button"
                            onClick={() =>
                              queueUpdate(
                                event,
                                "accept",
                                {},
                                "Proposal accepted.",
                              )
                            }
                            disabled={!isEditable}
                          >
                            Accept{" "}
                            <span className={styles.shortcutLabel}>A</span>
                          </button>
                          <button
                            className={styles.secondaryButton}
                            type="button"
                            onClick={() =>
                              queueUpdate(
                                event,
                                "dismiss",
                                {},
                                "Proposal dismissed.",
                              )
                            }
                            disabled={!isEditable}
                          >
                            Dismiss{" "}
                            <span className={styles.shortcutLabel}>D</span>
                          </button>
                        </>
                      ) : event.proposal !== null ? (
                        <button
                          className={styles.secondaryButton}
                          type="button"
                          onClick={() =>
                            queueUpdate(
                              event,
                              "undo",
                              {},
                              "Proposal decision undone.",
                            )
                          }
                          disabled={!isEditable}
                        >
                          Undo
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <section
          className={styles.cardEventFormPanel}
          aria-label="Selected event details"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Selected event</p>
              <h3>Event details</h3>
            </div>
            {selected !== undefined ? (
              <span className={styles.countLabel}>
                {formatTime(selected.effective_time_s)}
              </span>
            ) : null}
          </div>
          {selected === undefined ? (
            <p className={styles.detailEmptyState}>
              Select an event from the table or timeline.
            </p>
          ) : (
            <>
              <div className={styles.cardEventFormGrid}>
                <label>
                  Time (seconds)
                  <input
                    type="number"
                    min="0"
                    max={duration > 0 ? duration : undefined}
                    step="0.001"
                    value={selected.effective_time_s}
                    disabled={!isEditable}
                    onChange={(input) => {
                      const value = Number(input.target.value);
                      if (Number.isFinite(value))
                        setLocalEvents(
                          eventsRef.current.map((event) =>
                            event.localId === selected.localId
                              ? { ...event, effective_time_s: value }
                              : event,
                          ),
                        );
                    }}
                    onBlur={() => {
                      const current = eventsRef.current.find(
                        (event) => event.localId === selected.localId,
                      );
                      if (current !== undefined && isEditable)
                        queueUpdate(
                          current,
                          "retime",
                          { effectiveTime: current.effective_time_s },
                          "Event time updated.",
                        );
                    }}
                    aria-label="Time for selected event"
                  />
                </label>
                <label>
                  Event type
                  <select
                    value={selected.type}
                    disabled={!isEditable}
                    onChange={(input) =>
                      queueUpdate(
                        selected,
                        "edit",
                        { type: input.target.value },
                        "Event type updated.",
                      )
                    }
                    aria-label="Event type for selected event"
                  >
                    {CARD_EVENT_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {formatIdentifier(type)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Confidence
                  <select
                    value={selected.confidence ?? ""}
                    disabled={!isEditable}
                    onChange={(input) =>
                      queueUpdate(
                        selected,
                        "edit",
                        {
                          confidence:
                            input.target.value === ""
                              ? null
                              : input.target.value,
                        },
                        "Event confidence updated.",
                      )
                    }
                    aria-label="Confidence for selected event"
                  >
                    <option value="">Not set</option>
                    {CARD_EVENT_CONFIDENCES.map((confidence) => (
                      <option key={confidence} value={confidence}>
                        {formatIdentifier(confidence)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className={styles.cardEventFrameReadout}>
                  <span>Frame</span>
                  <strong>
                    {frameRate > 0
                      ? Math.round(selected.effective_time_s * frameRate)
                      : "Unavailable"}
                  </strong>
                </div>
              </div>
              <label className={styles.cardEventNotes}>
                Notes
                <textarea
                  rows={3}
                  value={selected.notes ?? ""}
                  disabled={!isEditable}
                  onChange={(input) =>
                    setLocalEvents(
                      eventsRef.current.map((event) =>
                        event.localId === selected.localId
                          ? { ...event, notes: input.target.value }
                          : event,
                      ),
                    )
                  }
                  onBlur={() => {
                    const current = eventsRef.current.find(
                      (event) => event.localId === selected.localId,
                    );
                    if (current !== undefined && isEditable)
                      queueUpdate(
                        current,
                        "edit",
                        { notes: current.notes },
                        "Event notes updated.",
                      );
                  }}
                  aria-label="Notes for selected event"
                />
              </label>
            </>
          )}
        </section>
        <div className={styles.cardEventEditActions}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() =>
              selected !== undefined &&
              queueUpdate(
                selected,
                "retime",
                { effectiveTime: selected.effective_time_s - 1 / frameRate },
                "Event nudged one frame earlier.",
              )
            }
            disabled={!isEditable || selected === undefined || frameRate <= 0}
          >
            Nudge −1 frame <span className={styles.shortcutLabel}>,</span>
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() =>
              selected !== undefined &&
              queueUpdate(
                selected,
                "retime",
                { effectiveTime: selected.effective_time_s + 1 / frameRate },
                "Event nudged one frame later.",
              )
            }
            disabled={!isEditable || selected === undefined || frameRate <= 0}
          >
            Nudge +1 frame <span className={styles.shortcutLabel}>.</span>
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() =>
              selected !== undefined &&
              queueUpdate(
                selected,
                "retime",
                { effectiveTime: playhead },
                "Event moved to the playhead.",
              )
            }
            disabled={!isEditable || selected === undefined}
          >
            Set to playhead
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={removeSelected}
            disabled={
              !isEditable ||
              selected === undefined ||
              (selected.proposal !== null && selected.state !== "reviewed")
            }
          >
            Remove selected event{" "}
            <span className={styles.shortcutLabel}>Delete</span>
          </button>
          {removedEvent !== null ? (
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={undoRemoval}
              disabled={!isEditable}
            >
              Undo removal
            </button>
          ) : null}
        </div>
        {frameRate <= 0 ? (
          <p className={styles.cardEventRequirement} role="status">
            Frame nudging is unavailable because frame rate is unavailable for
            this recording.
          </p>
        ) : null}
        <div className={styles.cardEventGuidance}>
          <details>
            <summary>Keyboard shortcuts</summary>
            <p>
              Space play/pause · ←/→ seek 250 ms · Shift + ←/→ seek 2 s · Alt +
              ←/→ previous/next marker · A accept · D dismiss · N add ·
              comma/period nudge one frame · Delete remove.
            </p>
          </details>
          <details>
            <summary>Event-type guidance</summary>
            <ul>
              {CARD_EVENT_TYPES.map((type) => (
                <li key={type}>
                  <strong>{formatIdentifier(type)}:</strong>{" "}
                  {EVENT_TYPE_GUIDANCE[type]}
                </li>
              ))}
            </ul>
          </details>
        </div>

        {isCompleted ? (
          <section
            className={styles.cardEventReviewPanel}
            aria-label="Correct completed CardEvent review"
          >
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.statusLabel}>Review lifecycle</p>
                <h3>Correct annotations</h3>
              </div>
              <span className={styles.countLabel}>New draft</span>
            </div>
            <p className={styles.cardEventRequirement}>
              The published review stays available as history. Create a new
              draft from it to edit or remove events, including events added by
              mistake.
            </p>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() => void startRevision()}
              disabled={revisionBusy}
            >
              {revisionBusy ? "Starting revision…" : "Correct annotations"}
            </button>
          </section>
        ) : (
          <section
            className={styles.cardEventReviewPanel}
            aria-label="Complete CardEvent review"
          >
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.statusLabel}>Review lifecycle</p>
                <h3>Complete full recording review</h3>
              </div>
              <span className={styles.countLabel}>
                {Math.round(
                  duration > 0
                    ? Math.min(100, (watchedThrough / duration) * 100)
                    : 0,
                )}
                % watched
              </span>
            </div>
            {!fullVideoReady ? (
              <p className={styles.cardEventRequirement}>
                Watch or seek to the end of the recording before you mark this
                review complete.
              </p>
            ) : null}
            {proposedCount > 0 ? (
              <p className={styles.cardEventRequirement}>
                Remaining proposed events: {proposedCount}.
              </p>
            ) : null}
          </section>
        )}
      </section>

      {!isCompleted ? (
        <section
          className={styles.cardEventCompletionBar}
          aria-label="Mark review complete"
        >
          <div>
            <p className={styles.statusLabel}>Review completion</p>
            <strong>Mark this timeline as complete</strong>
            {completionRequirement !== null ? (
              <p className={styles.cardEventCompletionRequirement}>
                {completionRequirement}
              </p>
            ) : null}
          </div>
          <label className={styles.cardEventCompletionReviewer}>
            Reviewer
            <input
              value={reviewerName}
              onChange={(input) => setReviewerName(input.target.value)}
              placeholder="Your name"
              aria-label="Reviewer"
            />
          </label>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => void completeReview()}
            disabled={!canMarkReviewComplete}
          >
            {completionBusy
              ? "Marking review complete…"
              : "Mark review complete"}
          </button>
        </section>
      ) : null}

      {notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {notice}
          {removedEvent !== null ? (
            <button
              className={styles.inlineAction}
              type="button"
              onClick={undoRemoval}
            >
              Undo removal
            </button>
          ) : null}
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
                Reload winning draft
              </button>
            ) : null}
            {saveState === "error" || saveState === "retrying" ? (
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={retryQueue}
              >
                Retry queued commands
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}

function ReviewMetadata({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function ReviewCount({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
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

type EventScreenshot = {
  time_s: number;
  src: string;
};

function useEventScreenshots(
  videoUrl: string,
  events: EditableEvent[],
  duration: number,
) {
  const captureVideoRef = useRef<HTMLVideoElement>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement>(null);
  const screenshotCacheRef = useRef(new Map<string, EventScreenshot>());
  const [screenshots, setScreenshots] = useState<
    Record<string, EventScreenshot>
  >({});
  const [unavailableScreenshots, setUnavailableScreenshots] = useState<
    Record<string, EventScreenshot>
  >({});

  useEffect(() => {
    const video = captureVideoRef.current;
    const canvas = captureCanvasRef.current;
    const activeEvents = events.filter((event) => event.effective_time_s >= 0);
    if (video === null || canvas === null || videoUrl === "") return;

    const activeIds = new Set(activeEvents.map((event) => event.localId));
    for (const eventId of screenshotCacheRef.current.keys()) {
      if (!activeIds.has(eventId)) screenshotCacheRef.current.delete(eventId);
    }

    setScreenshots((current) => keepCurrentScreenshots(current, activeEvents));
    setUnavailableScreenshots((current) =>
      keepCurrentScreenshots(current, activeEvents),
    );

    const controller = new AbortController();
    const captureVideo = video;
    const captureCanvas = canvas;
    const pendingEvents = activeEvents.filter((event) => {
      const cached = screenshotCacheRef.current.get(event.localId);
      return cached?.time_s !== event.effective_time_s;
    });

    async function capture() {
      try {
        await waitForVideoReady(captureVideo, controller.signal);
        const sourceWidth = captureVideo.videoWidth || 640;
        const sourceHeight = captureVideo.videoHeight || 360;
        const targetWidth = Math.min(sourceWidth, 640);
        const targetHeight = Math.max(
          1,
          Math.round((targetWidth * sourceHeight) / sourceWidth),
        );
        captureCanvas.width = targetWidth;
        captureCanvas.height = targetHeight;
        const context = captureCanvas.getContext("2d");
        if (context === null) throw new Error("Canvas is unavailable.");

        for (const event of pendingEvents) {
          if (controller.signal.aborted) return;
          const time = clampTime(event.effective_time_s, duration);
          try {
            await seekVideo(captureVideo, time, controller.signal);
            context.drawImage(captureVideo, 0, 0, targetWidth, targetHeight);
            const screenshot = {
              time_s: event.effective_time_s,
              src: captureCanvas.toDataURL("image/jpeg", 0.78),
            };
            screenshotCacheRef.current.set(event.localId, screenshot);
            if (!controller.signal.aborted) {
              setScreenshots((current) => ({
                ...current,
                [event.localId]: screenshot,
              }));
              setUnavailableScreenshots((current) => {
                const next = { ...current };
                delete next[event.localId];
                return next;
              });
            }
          } catch {
            if (!controller.signal.aborted) {
              setUnavailableScreenshots((current) => ({
                ...current,
                [event.localId]: { time_s: event.effective_time_s, src: "" },
              }));
            }
          }
        }
      } catch {
        if (!controller.signal.aborted) {
          setUnavailableScreenshots(() =>
            Object.fromEntries(
              pendingEvents.map((event) => [
                event.localId,
                { time_s: event.effective_time_s, src: "" },
              ]),
            ),
          );
        }
      }
    }

    void capture();
    return () => controller.abort();
  }, [duration, events, videoUrl]);

  return {
    captureVideoRef,
    captureCanvasRef,
    screenshots,
    unavailableScreenshots,
  };
}

function keepCurrentScreenshots(
  current: Record<string, EventScreenshot>,
  events: EditableEvent[],
): Record<string, EventScreenshot> {
  return Object.fromEntries(
    events.flatMap((event) => {
      const screenshot = current[event.localId];
      return screenshot?.time_s === event.effective_time_s
        ? [[event.localId, screenshot]]
        : [];
    }),
  );
}

function waitForVideoReady(
  video: HTMLVideoElement,
  signal: AbortSignal,
): Promise<void> {
  if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
    return Promise.resolve();
  }
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
  ) {
    return Promise.resolve();
  }
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
    let timeout = 0;
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
    video.addEventListener(eventName, finish);
    video.addEventListener("error", fail);
    signal.addEventListener("abort", abort, { once: true });
    timeout = window.setTimeout(fail, 10000);
  });
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
function formatTime(value: number): string {
  const minutes = Math.floor(value / 60);
  return `${minutes}:${(value % 60).toFixed(3).padStart(6, "0")}`;
}
function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}
function clampTime(value: number, duration = Number.POSITIVE_INFINITY): number {
  return Math.max(
    0,
    Math.min(duration > 0 ? duration : Number.POSITIVE_INFINITY, value),
  );
}
function describeCommand(command: PendingCommand | undefined): string {
  if (command === undefined) return "none";
  return command.kind === "add"
    ? "Add event"
    : `${formatIdentifier(command.action)} ${command.eventId}`;
}
function isConflictError(reason: unknown): boolean {
  return reason instanceof ApiError && reason.status === 409;
}
function describeReviewPageError(reason: unknown): string {
  if (reason instanceof ApiError && reason.body !== null) {
    const body = reason.body as { error?: { message?: string } };
    if (typeof body.error?.message === "string") return body.error.message;
  }
  return reason instanceof Error
    ? reason.message
    : "The CardEvent review could not be saved.";
}
