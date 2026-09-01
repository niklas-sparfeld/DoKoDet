import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type CardEventReview,
  type CardEventReviewCompletionRequest,
  type CardEventReviewDraftUpdateRequest,
  type RecordingDetail,
} from "../api/client";
import styles from "../App.module.css";

export const CARD_EVENT_TYPES = [
  "card_played",
  "trick_cleared",
  "card_moved",
  "card_removed",
  "card_returned",
  "multiple_cards_dropped",
  "anomalous_state_change",
] as const;

export const CARD_EVENT_CONFIDENCES = [
  "confirmed",
  "uncertain",
  "ignore",
  "proposed",
] as const;

type CardEventType = (typeof CARD_EVENT_TYPES)[number];
type CardEventConfidence = (typeof CARD_EVENT_CONFIDENCES)[number];
type CardEvent = {
  time_s: number;
  type: CardEventType;
  confidence?: CardEventConfidence | null;
  notes?: string | null;
};
type EditableEvent = CardEvent & { localId: string };
type ProposalDecision = "undecided" | "accepted" | "dismissed";
type SaveState = "saving" | "saved" | "error" | "conflict";
type WorkflowState = "idle" | "completing" | "revising";

const EVENT_TYPE_GUIDANCE: Record<CardEventType, string> = {
  card_played: "A card reaches its final position in the trick area.",
  trick_cleared: "The cards from the completed trick leave the play area.",
  card_moved: "An existing card changes position without being played.",
  card_removed: "A card leaves the visible play area for another reason.",
  card_returned: "A card returns to a hand or another known area.",
  multiple_cards_dropped: "Several cards enter the play area together.",
  anomalous_state_change:
    "A visible state change does not match the other types.",
};

export type CardEventEditorProps = {
  recordingId: string;
  videoUrl: string;
  mediaFacts: RecordingDetail["video"]["media_facts"];
  summary: RecordingDetail["card_event_review"];
  videoRef?: RefObject<HTMLVideoElement | null>;
  onSaved?: (review: CardEventReview) => void;
};

export function CardEventEditor({
  recordingId,
  videoUrl,
  mediaFacts,
  summary,
  videoRef,
  onSaved,
}: CardEventEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const playerRef = videoRef ?? localVideoRef;
  const reviewRef = useRef<CardEventReview | null>(null);
  const eventsRef = useRef<EditableEvent[]>([]);
  const decisionsRef = useRef<Record<string, ProposalDecision>>({});
  const nextLocalId = useRef(1);
  const [review, setReview] = useState<CardEventReview | null>(null);
  const [events, setEvents] = useState<EditableEvent[]>([]);
  const [decisions, setDecisions] = useState<Record<string, ProposalDecision>>(
    {},
  );
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [duration, setDuration] = useState(
    mediaFacts === null ? 0 : mediaFacts.duration_ms / 1000,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [workflowState, setWorkflowState] = useState<WorkflowState>("idle");
  const [pendingSave, setPendingSave] =
    useState<CardEventReviewDraftUpdateRequest | null>(null);
  const [removedEvent, setRemovedEvent] = useState<EditableEvent | null>(null);
  const [reviewerName, setReviewerName] = useState("");
  const [watchedThrough, setWatchedThrough] = useState(0);

  const applyReview = useCallback(
    (nextReview: CardEventReview, previousEvents = eventsRef.current) => {
      const nextEvents = mergeEditableEvents(
        nextReview,
        previousEvents,
        nextLocalId,
      );
      const nextDecisions = Object.fromEntries(
        nextReview.proposals.map((proposal) => [
          proposal.proposal_id,
          proposal.decision,
        ]),
      ) as Record<string, ProposalDecision>;
      reviewRef.current = nextReview;
      eventsRef.current = nextEvents;
      decisionsRef.current = nextDecisions;
      setReview(nextReview);
      setEvents(nextEvents);
      setDecisions(nextDecisions);
      if (
        nextReview.review_state === "completed" &&
        nextReview.reviewer !== null
      ) {
        setReviewerName(nextReview.reviewer);
      } else if (
        nextReview.review_state === "draft" &&
        nextReview.parent_version_id !== null
      ) {
        setReviewerName("");
      }
      setSelectedEventId((current) =>
        nextEvents.some((event) => event.localId === current)
          ? current
          : (nextEvents[0]?.localId ?? null),
      );
    },
    [],
  );

  const loadReview = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const nextReview = await client.getCardEventReview(recordingId, {
          signal,
        });
        if (!signal?.aborted) {
          applyReview(nextReview);
          setError(null);
          setSaveState("saved");
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          setError(describeReviewError(reason));
        }
      } finally {
        if (!signal?.aborted) {
          setLoading(false);
        }
      }
    },
    [applyReview, client, recordingId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadReview(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadReview]);

  useEffect(() => {
    const video = playerRef.current;
    if (video === null) {
      return;
    }
    const updateTime = () => {
      const currentTime = Number.isFinite(video.currentTime)
        ? Math.max(0, video.currentTime)
        : 0;
      setPlayhead(currentTime);
      setWatchedThrough((current) => Math.max(current, currentTime));
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
  }, [playerRef, review]);

  const selectedEvent = events.find(
    (event) => event.localId === selectedEventId,
  );
  const frameRate = mediaFacts?.nominal_frame_rate ?? 0;
  const timelineDuration = duration > 0 ? duration : 1;
  const hasShortGap = hasEventGapUnder(events, 0.1);
  const proposals = review?.proposals ?? [];
  const isSaving = saveState === "saving";
  const isCompleted = review?.review_state === "completed";
  const undecidedProposals = proposals.filter((proposal) => {
    const decision = decisions[proposal.proposal_id] ?? proposal.decision;
    return decision === "undecided";
  });
  const watchedPercent =
    duration > 0 ? Math.min(100, (watchedThrough / duration) * 100) : 0;
  const fullVideoReady =
    review?.full_video_acknowledged === true ||
    (duration > 0 &&
      watchedThrough >=
        Math.max(
          0,
          duration - Math.max(0.5, frameRate > 0 ? 1 / frameRate : 0.5),
        ));
  const completionPayload: CardEventReviewCompletionRequest | null =
    review === null
      ? null
      : {
          reviewer: reviewerName.trim(),
          expected_revision: review.draft_revision,
          full_video_acknowledged: review.full_video_acknowledged,
        };
  const canComplete =
    !isCompleted &&
    completionPayload !== null &&
    completionPayload.reviewer.length > 0 &&
    completionPayload.full_video_acknowledged &&
    undecidedProposals.length === 0;

  const persist = useCallback(
    async (
      nextEvents: EditableEvent[],
      nextDecisions: Record<string, ProposalDecision>,
      actionNotice: string | null,
      expectedRevision = reviewRef.current?.draft_revision,
      fullVideoAcknowledged = reviewRef.current?.full_video_acknowledged ??
        false,
    ) => {
      const currentReview = reviewRef.current;
      if (
        currentReview === null ||
        currentReview.review_state === "completed" ||
        expectedRevision === undefined
      ) {
        return;
      }
      const payload: CardEventReviewDraftUpdateRequest = {
        annotation: {
          schema_version: "cardevent-annotation/v2",
          video: currentReview.video,
          events: nextEvents.map(toApiEvent),
        },
        proposals: currentReview.proposals.map((proposal) => ({
          proposal_id: proposal.proposal_id,
          decision: nextDecisions[proposal.proposal_id] ?? "undecided",
        })),
        expected_revision: expectedRevision,
        full_video_acknowledged: fullVideoAcknowledged,
      };
      setPendingSave(payload);
      setSaveState("saving");
      setError(null);
      try {
        const saved = await client.updateCardEventReviewDraft(
          recordingId,
          payload,
        );
        applyReview(saved, nextEvents);
        setPendingSave(null);
        setSaveState("saved");
        setNotice(actionNotice ?? "Draft saved.");
        onSaved?.(saved);
      } catch (reason: unknown) {
        setSaveState(isConflictError(reason) ? "conflict" : "error");
        setError(describeReviewError(reason));
      }
    },
    [applyReview, client, onSaved, recordingId],
  );

  const mutateEvents = useCallback(
    (
      mutator: (current: EditableEvent[]) => EditableEvent[],
      actionNotice: string,
    ) => {
      if (reviewRef.current?.review_state === "completed") {
        return;
      }
      const nextEvents = sortEvents(mutator(eventsRef.current));
      eventsRef.current = nextEvents;
      setEvents(nextEvents);
      void persist(nextEvents, decisionsRef.current, actionNotice);
    },
    [persist],
  );

  const setCurrentTime = useCallback(
    (time: number) => {
      const video = readVideo(playerRef);
      const maximum = duration > 0 ? duration : Number.POSITIVE_INFINITY;
      const nextTime = clamp(time, 0, maximum);
      if (video !== null) {
        video.currentTime = nextTime;
      }
      setPlayhead(nextTime);
    },
    [duration, playerRef],
  );

  const selectEvent = useCallback(
    (event: EditableEvent, seek = true) => {
      setSelectedEventId(event.localId);
      if (seek) {
        setCurrentTime(event.time_s);
      }
    },
    [setCurrentTime],
  );

  const moveSelected = useCallback(
    (nextTime: number, actionNotice: string) => {
      if (selectedEventId === null) {
        return;
      }
      mutateEvents(
        (current) =>
          current.map((event) =>
            event.localId === selectedEventId
              ? {
                  ...event,
                  time_s: clamp(
                    nextTime,
                    0,
                    duration || Number.POSITIVE_INFINITY,
                  ),
                }
              : event,
          ),
        actionNotice,
      );
    },
    [duration, mutateEvents, selectedEventId],
  );

  const addEvent = useCallback(() => {
    if (reviewRef.current?.review_state === "completed") {
      return;
    }
    const event: EditableEvent = {
      localId: `event-${nextLocalId.current++}`,
      time_s: clamp(playhead, 0, duration || Number.POSITIVE_INFINITY),
      type: "card_played",
      confidence: "confirmed",
    };
    const nextEvents = sortEvents([...eventsRef.current, event]);
    eventsRef.current = nextEvents;
    setEvents(nextEvents);
    setSelectedEventId(event.localId);
    void persist(
      nextEvents,
      decisionsRef.current,
      "Event added at the playhead.",
    );
  }, [duration, persist, playhead]);

  const jumpToAdjacentMarker = useCallback(
    (direction: "previous" | "next") => {
      const markerTimes = [
        ...eventsRef.current.map((event) => event.time_s),
        ...(reviewRef.current?.proposals ?? []).map(
          (proposal) => proposal.time_s,
        ),
      ].sort((first, second) => first - second);
      const nextMarker =
        direction === "previous"
          ? [...markerTimes].reverse().find((time) => time < playhead - 0.001)
          : markerTimes.find((time) => time > playhead + 0.001);
      if (nextMarker !== undefined) {
        setCurrentTime(nextMarker);
      }
    },
    [playhead, setCurrentTime],
  );

  const removeSelected = useCallback(() => {
    if (
      selectedEventId === null ||
      reviewRef.current?.review_state === "completed"
    ) {
      return;
    }
    const removed = eventsRef.current.find(
      (event) => event.localId === selectedEventId,
    );
    if (removed === undefined) {
      return;
    }
    const nextEvents = eventsRef.current.filter(
      (event) => event.localId !== selectedEventId,
    );
    eventsRef.current = nextEvents;
    setEvents(nextEvents);
    setSelectedEventId(nextEvents[0]?.localId ?? null);
    setRemovedEvent(removed);
    void persist(
      nextEvents,
      decisionsRef.current,
      "Event removed. You can undo this action.",
    );
  }, [persist, selectedEventId]);

  const undoRemove = useCallback(() => {
    if (
      removedEvent === null ||
      reviewRef.current?.review_state === "completed"
    ) {
      return;
    }
    const nextEvents = sortEvents([...eventsRef.current, removedEvent]);
    eventsRef.current = nextEvents;
    setEvents(nextEvents);
    setSelectedEventId(removedEvent.localId);
    setRemovedEvent(null);
    void persist(nextEvents, decisionsRef.current, "Event restored.");
  }, [persist, removedEvent]);

  const updateSelectedField = useCallback(
    (changes: Partial<CardEvent>, actionNotice: string) => {
      if (
        selectedEventId === null ||
        reviewRef.current?.review_state === "completed"
      ) {
        return;
      }
      mutateEvents(
        (current) =>
          current.map((event) =>
            event.localId === selectedEventId
              ? { ...event, ...changes }
              : event,
          ),
        actionNotice,
      );
    },
    [mutateEvents, selectedEventId],
  );

  const updateNotesLocally = useCallback(
    (notes: string) => {
      if (
        selectedEventId === null ||
        reviewRef.current?.review_state === "completed"
      ) {
        return;
      }
      const nextEvents = eventsRef.current.map((event) =>
        event.localId === selectedEventId ? { ...event, notes } : event,
      );
      eventsRef.current = nextEvents;
      setEvents(nextEvents);
    },
    [selectedEventId],
  );

  const acceptProposal = useCallback(
    (proposalId: string) => {
      if (reviewRef.current?.review_state === "completed") {
        return;
      }
      const nextDecisions = {
        ...decisionsRef.current,
        [proposalId]: "accepted" as const,
      };
      decisionsRef.current = nextDecisions;
      setDecisions(nextDecisions);
      void persist(
        eventsRef.current,
        nextDecisions,
        "Proposal accepted as a human event.",
      );
    },
    [persist],
  );

  const dismissProposal = useCallback(
    (proposalId: string) => {
      if (reviewRef.current?.review_state === "completed") {
        return;
      }
      const nextDecisions = {
        ...decisionsRef.current,
        [proposalId]: "dismissed" as const,
      };
      decisionsRef.current = nextDecisions;
      setDecisions(nextDecisions);
      void persist(
        eventsRef.current,
        nextDecisions,
        "Proposal dismissed without creating an event.",
      );
    },
    [persist],
  );

  const reloadWinningDraft = useCallback(async () => {
    setSaveState("saving");
    try {
      const winning = await client.getCardEventReview(recordingId);
      applyReview(winning);
      setPendingSave(null);
      setError(null);
      setNotice(
        "Winning draft loaded. Your unsaved local action was not applied.",
      );
      setSaveState("saved");
      onSaved?.(winning);
    } catch (reason: unknown) {
      setSaveState("error");
      setError(describeReviewError(reason));
    }
  }, [applyReview, client, onSaved, recordingId]);

  const retryLastSave = useCallback(async () => {
    const pending = pendingSave;
    if (pending === null) {
      return;
    }
    setSaveState("saving");
    try {
      const winning = await client.getCardEventReview(recordingId);
      reviewRef.current = winning;
      setReview(winning);
      const retriedPayload = {
        ...pending,
        expected_revision: winning.draft_revision,
      };
      const retriedEvents = eventsRef.current;
      const saved = await client.updateCardEventReviewDraft(
        recordingId,
        retriedPayload,
      );
      applyReview(saved, retriedEvents);
      setPendingSave(null);
      setSaveState("saved");
      setError(null);
      setNotice("The local action was retried and saved.");
      onSaved?.(saved);
    } catch (reason: unknown) {
      setSaveState(isConflictError(reason) ? "conflict" : "error");
      setError(describeReviewError(reason));
    }
  }, [applyReview, client, onSaved, pendingSave, recordingId]);

  const acknowledgeFullVideo = useCallback(
    (acknowledged: boolean) => {
      if (
        reviewRef.current === null ||
        reviewRef.current.review_state === "completed"
      ) {
        return;
      }
      void persist(
        eventsRef.current,
        decisionsRef.current,
        acknowledged
          ? "Full recording acknowledgement saved."
          : "Full recording acknowledgement removed.",
        undefined,
        acknowledged,
      );
    },
    [persist],
  );

  const completeReview = useCallback(async () => {
    const currentReview = reviewRef.current;
    if (
      currentReview === null ||
      currentReview.review_state === "completed" ||
      reviewerName.trim() === ""
    ) {
      return;
    }
    setWorkflowState("completing");
    setSaveState("saving");
    setPendingSave(null);
    setError(null);
    try {
      const completed = await client.completeCardEventReview(recordingId, {
        reviewer: reviewerName.trim(),
        expected_revision: currentReview.draft_revision,
        full_video_acknowledged: currentReview.full_video_acknowledged,
      });
      applyReview(completed);
      setSaveState("saved");
      setWorkflowState("idle");
      setNotice(
        `Reviewed version ${completed.completed_version_id ?? "published"} is immutable.`,
      );
      onSaved?.(completed);
    } catch (reason: unknown) {
      setWorkflowState("idle");
      setSaveState(isConflictError(reason) ? "conflict" : "error");
      setError(describeReviewError(reason));
    }
  }, [applyReview, client, onSaved, recordingId, reviewerName]);

  const startRevision = useCallback(async () => {
    const currentReview = reviewRef.current;
    if (
      currentReview === null ||
      currentReview.review_state !== "completed" ||
      currentReview.completed_version_id === null
    ) {
      return;
    }
    setWorkflowState("revising");
    setSaveState("saving");
    setError(null);
    try {
      const revision = await client.startCardEventReviewRevision(recordingId, {
        parent_version_id: currentReview.completed_version_id,
        expected_revision: currentReview.draft_revision,
      });
      applyReview(revision);
      setSaveState("saved");
      setWorkflowState("idle");
      setNotice(
        `Revision started from ${currentReview.completed_version_id}. The completed version remains unchanged.`,
      );
      onSaved?.(revision);
    } catch (reason: unknown) {
      setWorkflowState("idle");
      setSaveState(isConflictError(reason) ? "conflict" : "error");
      setError(describeReviewError(reason));
    }
  }, [applyReview, client, onSaved, recordingId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      if (event.key === " ") {
        event.preventDefault();
        const video = playerRef.current;
        if (video === null) {
          return;
        }
        if (video.paused) {
          void video.play().catch(() => undefined);
        } else {
          video.pause();
        }
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const amount = event.shiftKey ? 2 : 0.25;
        setCurrentTime(
          playhead + (event.key === "ArrowLeft" ? -amount : amount),
        );
      } else if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        addEvent();
      } else if (event.key === "j" || event.key === "J") {
        event.preventDefault();
        jumpToAdjacentMarker("previous");
      } else if (event.key === "k" || event.key === "K") {
        event.preventDefault();
        jumpToAdjacentMarker("next");
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        removeSelected();
      } else if (event.key === "[") {
        event.preventDefault();
        if (selectedEvent !== undefined && frameRate > 0) {
          moveSelected(
            selectedEvent.time_s - 1 / frameRate,
            "Event nudged one frame earlier.",
          );
        }
      } else if (event.key === "]") {
        event.preventDefault();
        if (selectedEvent !== undefined && frameRate > 0) {
          moveSelected(
            selectedEvent.time_s + 1 / frameRate,
            "Event nudged one frame later.",
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
    moveSelected,
    playhead,
    playerRef,
    removeSelected,
    selectedEvent,
    setCurrentTime,
  ]);

  if (loading && review === null) {
    return (
      <p className={styles.detailEmptyState} aria-live="polite">
        {summary.state === "not_started"
          ? "No CardEvent review has been started."
          : "Loading CardEvent review…"}
      </p>
    );
  }

  if (review === null) {
    return (
      <>
        <p className={styles.detailEmptyState}>
          {summary.state === "not_started"
            ? "No CardEvent review has been started."
            : "The CardEvent review is not available."}
        </p>
        {error !== null ? <p className={styles.errorMessage}>{error}</p> : null}
      </>
    );
  }

  const selectedProposalDecisions = new Map(
    proposals.map((proposal) => [
      proposal.proposal_id,
      decisions[proposal.proposal_id] ?? proposal.decision,
    ]),
  );

  return (
    <div className={styles.cardEventEditor}>
      {videoRef === undefined ? (
        <video
          ref={localVideoRef}
          className={styles.cardEventVideo}
          controls
          preload="metadata"
          src={videoUrl}
          aria-label={`CardEvent source video ${recordingId}`}
        />
      ) : null}

      <div className={styles.cardEventToolbar}>
        <div className={styles.cardEventTransport}>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => setCurrentTime(playhead - 2)}
            disabled={isSaving}
          >
            −2 s
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => setCurrentTime(playhead - 0.25)}
            disabled={isSaving}
          >
            −250 ms
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => setCurrentTime(playhead + 0.25)}
            disabled={isSaving}
          >
            +250 ms
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => setCurrentTime(playhead + 2)}
            disabled={isSaving}
          >
            +2 s
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => jumpToAdjacentMarker("previous")}
            disabled={isSaving}
          >
            Previous marker
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={() => jumpToAdjacentMarker("next")}
            disabled={isSaving}
          >
            Next marker
          </button>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={addEvent}
            disabled={isSaving || isCompleted}
          >
            Add event at playhead
          </button>
        </div>
        <div className={styles.cardEventSaveStatus} aria-live="polite">
          <span data-state={saveState}>
            {saveState === "saving"
              ? workflowState === "completing"
                ? "Publishing"
                : workflowState === "revising"
                  ? "Starting revision"
                  : "Saving"
              : saveState === "saved"
                ? "Saved"
                : saveState === "conflict"
                  ? "Conflict"
                  : "Not saved"}
          </span>
          {review.draft_revision > 0 ? ` · draft ${review.draft_revision}` : ""}
        </div>
      </div>

      <section
        className={styles.cardEventReviewPanel}
        aria-label="Full recording review"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Review lifecycle</p>
            <h3>
              {isCompleted
                ? "Reviewed annotation"
                : "Complete full recording review"}
            </h3>
          </div>
          <span className={styles.countLabel}>
            {isCompleted ? "Reviewed" : "Draft"}
          </span>
        </div>
        {isCompleted ? (
          <>
            <p className={styles.cardEventReviewSummary} role="status">
              This reviewed annotation is immutable. Start a revision to make a
              later correction.
            </p>
            <dl className={styles.cardEventReviewMetadata}>
              <ReviewMetadata
                label="Reviewed version"
                value={review.completed_version_id ?? "Not available"}
              />
              <ReviewMetadata
                label="Reviewer"
                value={review.reviewer ?? "Not available"}
              />
              <ReviewMetadata
                label="Reviewed at"
                value={
                  review.completed_at === null
                    ? "Not available"
                    : formatTimestamp(review.completed_at)
                }
              />
              <ReviewMetadata
                label="Annotation digest"
                value={review.reviewed_annotation_digest ?? "Not available"}
              />
              <ReviewMetadata
                label="Version digest"
                value={review.completed_version_digest ?? "Not available"}
              />
              <ReviewMetadata
                label="Proposal decisions"
                value={review.proposal_decision_digest ?? "Not available"}
              />
              <ReviewMetadata
                label="Lifecycle receipt"
                value={review.completion_receipt_id ?? "Not available"}
              />
            </dl>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() => void startRevision()}
              disabled={isSaving}
            >
              Start a new revision
            </button>
          </>
        ) : (
          <>
            <p className={styles.cardEventReviewSummary}>
              Review the source from start to finish. Then acknowledge the full
              recording and identify the operator who completed the review.
            </p>
            <div className={styles.cardEventProgressBlock}>
              <div className={styles.cardEventProgressHeader}>
                <span>Full-video progress</span>
                <strong>{Math.round(watchedPercent)}%</strong>
              </div>
              <progress
                max="100"
                value={watchedPercent}
                aria-label="Full-video review progress"
              />
              <p className={styles.cardEventProgressMeta}>
                Watched through {formatTime(watchedThrough)} of{" "}
                {duration > 0 ? formatTime(duration) : "an unknown duration"}.
                {duration <= 0
                  ? " Media duration is not available yet."
                  : " Play or seek to the end before acknowledging the full recording."}
              </p>
            </div>
            <label className={styles.cardEventAcknowledgement}>
              <input
                type="checkbox"
                checked={review.full_video_acknowledged}
                disabled={isSaving || !fullVideoReady}
                onChange={(event) => acknowledgeFullVideo(event.target.checked)}
              />
              <span>
                I reviewed the full recording and confirm that this timeline is
                ready for completion.
              </span>
            </label>
            {!fullVideoReady && !review.full_video_acknowledged ? (
              <p className={styles.cardEventRequirement}>
                Full-video acknowledgement becomes available after the player
                reaches the end of the recording.
              </p>
            ) : null}
            {undecidedProposals.length > 0 ? (
              <p className={styles.cardEventRequirement} role="status">
                Remaining proposal decisions ({undecidedProposals.length}):{" "}
                {undecidedProposals
                  .map((proposal) => formatTime(proposal.time_s))
                  .join(", ")}
                .
              </p>
            ) : (
              <p className={styles.cardEventRequirement}>
                All proposal decisions are complete.
              </p>
            )}
            <label className={styles.cardEventReviewer}>
              Reviewer
              <input
                value={reviewerName}
                onChange={(event) => setReviewerName(event.target.value)}
                placeholder="Operator name"
                disabled={isSaving}
                aria-label="Reviewer"
              />
            </label>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={() => void completeReview()}
              disabled={isSaving || !canComplete}
            >
              Complete full recording review
            </button>
            {!canComplete ? (
              <p className={styles.cardEventRequirement}>
                Completion is blocked until the full recording is acknowledged,
                every proposal has a decision, and a reviewer is named.
              </p>
            ) : null}
          </>
        )}
      </section>

      <div className={styles.cardEventTimelineHeader}>
        <div>
          <p className={styles.statusLabel}>Timeline rail</p>
          <p className={styles.cardEventTimeRange}>
            Playhead {formatTime(playhead)} · visible range 0:00.000–
            {formatTime(timelineDuration)}
          </p>
        </div>
        <span className={styles.countLabel}>
          {events.length} saved · {proposals.length} proposals
        </span>
      </div>
      <div
        className={styles.cardEventRail}
        role="group"
        aria-label="CardEvent timeline rail"
      >
        <span className={styles.cardEventRailTrack} />
        <span
          className={styles.cardEventPlayhead}
          style={{
            left: `${(clamp(playhead, 0, timelineDuration) / timelineDuration) * 100}%`,
          }}
          aria-hidden="true"
        />
        {events.map((event, index) => (
          <button
            key={event.localId}
            className={styles.cardEventMarker}
            data-selected={event.localId === selectedEventId}
            style={{ left: `${(event.time_s / timelineDuration) * 100}%` }}
            type="button"
            title={`Event ${index + 1} at ${formatTime(event.time_s)}`}
            aria-label={`Select event ${index + 1} at ${formatTime(event.time_s)} seconds`}
            onClick={() => selectEvent(event)}
          />
        ))}
        {proposals.map((proposal) => (
          <button
            key={proposal.proposal_id}
            className={styles.cardEventProposalMarker}
            data-decision={selectedProposalDecisions.get(proposal.proposal_id)}
            style={{ left: `${(proposal.time_s / timelineDuration) * 100}%` }}
            type="button"
            title={`Proposal at ${formatTime(proposal.time_s)}`}
            aria-label={`Jump to proposal at ${formatTime(proposal.time_s)} seconds`}
            onClick={() => setCurrentTime(proposal.time_s)}
          />
        ))}
      </div>

      <div className={styles.cardEventWorkspace}>
        <section className={styles.cardEventListPanel}>
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Saved events</p>
              <h3>Ordered event list</h3>
            </div>
            <span className={styles.countLabel}>{events.length}</span>
          </div>
          {events.length === 0 ? (
            <p className={styles.detailEmptyState}>
              No saved events. Move the playhead and add the first event.
            </p>
          ) : (
            <ol className={styles.cardEventList} aria-label="Saved CardEvents">
              {events.map((event, index) => (
                <li key={event.localId}>
                  <button
                    className={styles.cardEventListItem}
                    data-selected={event.localId === selectedEventId}
                    type="button"
                    onClick={() => selectEvent(event)}
                  >
                    <span>
                      Event {index + 1} · {formatTime(event.time_s)}
                    </span>
                    <small>{formatIdentifier(event.type)}</small>
                  </button>
                </li>
              ))}
            </ol>
          )}
          <div className={styles.cardEventProposalSection}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.statusLabel}>Model or device output</p>
                <h3>Proposals</h3>
              </div>
              <span className={styles.countLabel}>{proposals.length}</span>
            </div>
            {proposals.length === 0 ? (
              <p className={styles.detailEmptyState}>
                No proposals were supplied.
              </p>
            ) : (
              <ul
                className={styles.cardEventProposalList}
                aria-label="CardEvent proposals"
              >
                {proposals.map((proposal) => {
                  const decision =
                    selectedProposalDecisions.get(proposal.proposal_id) ??
                    "undecided";
                  return (
                    <li
                      key={proposal.proposal_id}
                      className={styles.cardEventProposal}
                      aria-label={`Proposal at ${formatTime(proposal.time_s)} seconds`}
                    >
                      <div>
                        <strong>
                          Proposal at {formatTime(proposal.time_s)}
                        </strong>
                        <span>
                          {Math.round(proposal.probability * 100)}% ·{" "}
                          {formatIdentifier(decision)}
                        </span>
                      </div>
                      <div className={styles.cardEventProposalActions}>
                        <button
                          className={styles.secondaryButton}
                          type="button"
                          onClick={() => acceptProposal(proposal.proposal_id)}
                          disabled={
                            isSaving || isCompleted || decision === "accepted"
                          }
                        >
                          Accept proposal
                        </button>
                        <button
                          className={styles.secondaryButton}
                          type="button"
                          onClick={() => dismissProposal(proposal.proposal_id)}
                          disabled={
                            isSaving || isCompleted || decision === "dismissed"
                          }
                        >
                          Dismiss proposal
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <section
          className={styles.cardEventFormPanel}
          aria-label="Selected event"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Selected event</p>
              <h3>Event details</h3>
            </div>
            {selectedEvent !== undefined ? (
              <span className={styles.countLabel}>
                {formatTime(selectedEvent.time_s)}
              </span>
            ) : null}
          </div>
          {selectedEvent === undefined ? (
            <p className={styles.detailEmptyState}>
              Select an event from the list or rail to edit it.
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
                    value={selectedEvent.time_s}
                    disabled={isSaving || isCompleted}
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (Number.isFinite(value)) {
                        const nextEvents = sortEvents(
                          eventsRef.current.map((current) =>
                            current.localId === selectedEvent.localId
                              ? { ...current, time_s: value }
                              : current,
                          ),
                        );
                        eventsRef.current = nextEvents;
                        setEvents(nextEvents);
                      }
                    }}
                    onBlur={() => {
                      const current = eventsRef.current.find(
                        (event) => event.localId === selectedEvent.localId,
                      );
                      if (current !== undefined) {
                        void persist(
                          eventsRef.current,
                          decisionsRef.current,
                          "Event time updated.",
                        );
                      }
                    }}
                    aria-label="Time for selected event"
                  />
                </label>
                <label>
                  Event type
                  <select
                    value={selectedEvent.type}
                    disabled={isSaving || isCompleted}
                    onChange={(event) =>
                      updateSelectedField(
                        { type: event.target.value as CardEventType },
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
                    value={selectedEvent.confidence ?? ""}
                    disabled={isSaving || isCompleted}
                    onChange={(event) =>
                      updateSelectedField(
                        {
                          confidence:
                            event.target.value === ""
                              ? null
                              : (event.target.value as CardEventConfidence),
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
                      ? Math.round(selectedEvent.time_s * frameRate)
                      : "Unavailable"}
                  </strong>
                </div>
              </div>
              <label className={styles.cardEventNotes}>
                Notes
                <textarea
                  value={selectedEvent.notes ?? ""}
                  rows={3}
                  disabled={isSaving || isCompleted}
                  onChange={(event) => updateNotesLocally(event.target.value)}
                  onBlur={() =>
                    void persist(
                      eventsRef.current,
                      decisionsRef.current,
                      "Event notes updated.",
                    )
                  }
                  aria-label="Notes for selected event"
                />
              </label>
              <div className={styles.cardEventEditActions}>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() =>
                    frameRate > 0
                      ? moveSelected(
                          selectedEvent.time_s - 1 / frameRate,
                          "Event nudged one frame earlier.",
                        )
                      : undefined
                  }
                  disabled={isSaving || isCompleted || frameRate <= 0}
                >
                  Nudge −1 frame
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() =>
                    frameRate > 0
                      ? moveSelected(
                          selectedEvent.time_s + 1 / frameRate,
                          "Event nudged one frame later.",
                        )
                      : undefined
                  }
                  disabled={isSaving || isCompleted || frameRate <= 0}
                >
                  Nudge +1 frame
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() =>
                    moveSelected(playhead, "Event moved to the playhead.")
                  }
                  disabled={isSaving || isCompleted}
                >
                  Set to playhead
                </button>
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={removeSelected}
                  disabled={isSaving || isCompleted}
                >
                  Remove selected event
                </button>
              </div>
            </>
          )}
        </section>
      </div>

      <div className={styles.cardEventGuidance}>
        <details>
          <summary>Timing and event-type guidance</summary>
          <p>
            Use the first frame where the card has substantially reached its
            final position in the trick area. Event time is stored in seconds;
            the editor also shows milliseconds and the derived frame number.
          </p>
          <ul>
            {CARD_EVENT_TYPES.map((type) => (
              <li key={type}>
                <strong>{formatIdentifier(type)}:</strong>{" "}
                {EVENT_TYPE_GUIDANCE[type]}
              </li>
            ))}
          </ul>
        </details>
        <details>
          <summary>Keyboard shortcuts</summary>
          <p>
            Space play/pause · ←/→ seek 250 ms · Shift + ←/→ seek 2 s · J/K
            previous/next marker · N add event · [ / ] nudge one frame · Delete
            remove selected event.
          </p>
        </details>
      </div>

      {hasShortGap ? (
        <p className={styles.cardEventWarning} role="status">
          Warning: two saved events are less than 100 ms apart. The backend
          rejects only effective duplicates of 10 ms or less.
        </p>
      ) : null}
      {notice !== null ? (
        <p className={styles.recordingNotice} role="status">
          {notice}
          {removedEvent !== null ? (
            <button
              className={styles.inlineAction}
              type="button"
              onClick={undoRemove}
              disabled={isSaving}
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
              ? `Conflict: your local action was not saved. ${error}`
              : error}
          </p>
          {pendingSave !== null ? (
            <div className={styles.cardEventErrorActions}>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => void retryLastSave()}
                disabled={isSaving}
              >
                Retry last save
              </button>
              {saveState === "conflict" ? (
                <button
                  className={styles.secondaryButton}
                  type="button"
                  onClick={() => void reloadWinningDraft()}
                  disabled={isSaving}
                >
                  Reload winning draft
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
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

function mergeEditableEvents(
  review: CardEventReview,
  previous: EditableEvent[],
  nextLocalId: { current: number },
): EditableEvent[] {
  const used = new Set<string>();
  return parseEvents(review).map((event) => {
    const match = previous.find(
      (candidate) =>
        !used.has(candidate.localId) && sameEvent(candidate, event),
    );
    if (match !== undefined) {
      used.add(match.localId);
      return { ...event, localId: match.localId };
    }
    return { ...event, localId: `event-${nextLocalId.current++}` };
  });
}

function parseEvents(review: CardEventReview): CardEvent[] {
  const rawEvents = review.annotation.events;
  if (!Array.isArray(rawEvents)) {
    throw new Error("The CardEvent review returned no valid event list.");
  }
  return rawEvents.map((rawEvent, index) => {
    if (typeof rawEvent !== "object" || rawEvent === null) {
      throw new Error(`CardEvent ${index + 1} is not an object.`);
    }
    const event = rawEvent as Record<string, unknown>;
    if (
      typeof event.time_s !== "number" ||
      typeof event.type !== "string" ||
      !CARD_EVENT_TYPES.includes(event.type as CardEventType)
    ) {
      throw new Error(`CardEvent ${index + 1} is invalid.`);
    }
    return {
      time_s: event.time_s,
      type: event.type as CardEventType,
      confidence:
        typeof event.confidence === "string"
          ? (event.confidence as CardEventConfidence)
          : event.confidence === null
            ? null
            : undefined,
      notes:
        typeof event.notes === "string"
          ? event.notes
          : event.notes === null
            ? null
            : undefined,
    };
  });
}

function toApiEvent(event: EditableEvent): CardEvent {
  const { localId: _localId, ...apiEvent } = event;
  void _localId;
  return apiEvent;
}

function sameEvent(first: CardEvent, second: CardEvent): boolean {
  return (
    first.time_s === second.time_s &&
    first.type === second.type &&
    first.confidence === second.confidence &&
    first.notes === second.notes
  );
}

function sortEvents(events: EditableEvent[]): EditableEvent[] {
  return [...events].sort((first, second) => first.time_s - second.time_s);
}

function hasEventGapUnder(events: EditableEvent[], threshold: number): boolean {
  return events.some(
    (event, index) =>
      index > 0 && event.time_s - events[index - 1].time_s < threshold,
  );
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function readVideo(
  ref: RefObject<HTMLVideoElement | null>,
): HTMLVideoElement | null {
  return ref.current;
}

function formatTime(value: number): string {
  const milliseconds = Math.round(value * 1000);
  const minutes = Math.floor(milliseconds / 60000);
  const seconds = Math.floor((milliseconds % 60000) / 1000);
  const remainder = milliseconds % 1000;
  return `${minutes}:${seconds.toString().padStart(2, "0")}.${remainder
    .toString()
    .padStart(3, "0")}`;
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function isConflictError(reason: unknown): boolean {
  return reason instanceof ApiError && reason.status === 409;
}

function describeReviewError(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (
      typeof reason.body === "object" &&
      reason.body !== null &&
      "error" in reason.body &&
      typeof reason.body.error === "object" &&
      reason.body.error !== null &&
      "message" in reason.body.error &&
      typeof reason.body.error.message === "string"
    ) {
      return reason.body.error.message;
    }
    return `The backend returned HTTP ${reason.status}.`;
  }
  return reason instanceof Error
    ? reason.message
    : "The backend could not be reached.";
}
