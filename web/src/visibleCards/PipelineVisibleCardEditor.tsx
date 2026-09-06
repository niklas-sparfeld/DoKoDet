import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import {
  ApiError,
  createDokoDetectorClient,
  pipelineDerivedFramePath,
  repositoryBundleVideoPath,
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineVisibleCardResult,
} from "../api/client";
import styles from "../App.module.css";

type Point = { x: number; y: number };
type FrameIdentity = {
  requested_time_us: number;
  frame_index: number;
  presentation_timestamp_us: number;
  width: number;
  height: number;
  image_sha256: string;
  [key: string]: unknown;
};
type Geometry = {
  kind: string;
  box_2d?: { x_min: number; y_min: number; x_max: number; y_max: number };
  visible_region?: { polygons: Point[][] };
};
type Candidate = {
  card_id: string;
  geometry: Geometry;
  normalization: Record<string, unknown>;
  model_scores?: Array<Record<string, unknown>>;
};
type Outcome = {
  event_id: string;
  frame_identity: FrameIdentity | null;
  status: "detected" | "empty" | "failed";
  candidates: Candidate[];
  error: string | null;
};
type FrameReviewState =
  | "pending"
  | "accepted"
  | "rejected"
  | "added"
  | "corrected"
  | "empty"
  | "unusable"
  | "affected";
type EditableFrame = {
  itemId: string;
  baseItemId: string | null;
  reviewState: FrameReviewState;
  outcome: Outcome;
};
type SaveState = "saved" | "saving" | "retrying" | "error" | "conflict";
type PendingCommand = {
  commandId: string;
  operation: PipelineReferenceOperation;
  notice: string;
  attempts: number;
};
type EditorState = {
  frameItemId: string;
  cardId: string | null;
  polygons: Point[][];
  polygonIndex: number;
  selectedPointIndex: number | null;
};

const CONTENT_TYPE = "visible_cards" as const;
const RETRY_LIMIT = 3;

export type PipelineVisibleCardEditorProps = {
  recordingId: string;
  videoUrl?: string;
  durationUs: number;
  generatedRevisionId: string | null;
  displayedRevisionId?: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
};

export function PipelineVisibleCardEditor({
  recordingId,
  videoUrl = repositoryBundleVideoPath(recordingId),
  durationUs,
  generatedRevisionId,
  displayedRevisionId = generatedRevisionId,
  generatedRunId,
  view,
}: PipelineVisibleCardEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const referenceRef = useRef<PipelineReferenceResource | null>(null);
  const framesRef = useRef<EditableFrame[]>([]);
  const selectedFrameIdRef = useRef<string | null>(null);
  const serverRevisionRef = useRef(0);
  const queueRef = useRef<PendingCommand[]>([]);
  const processingRef = useRef(false);
  const processQueueRef = useRef<(() => void) | null>(null);
  const retryTimerRef = useRef<number | null>(null);
  const commandSequenceRef = useRef(0);
  const inspectedFrameKeysRef = useRef(new Set<string>());
  const editorRef = useRef<EditorState | null>(null);
  const saveEditorRef = useRef<(() => void) | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    polygonIndex: number;
    pointIndex: number;
    dirty: boolean;
  } | null>(null);
  const [reference, setReference] = useState<PipelineReferenceResource | null>(
    null,
  );
  const [frames, setFrames] = useState<EditableFrame[]>([]);
  const [generatedFrames, setGeneratedFrames] = useState<EditableFrame[]>([]);
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [playheadUs, setPlayheadUs] = useState(0);
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
  const [inspectedFrameKeys, setInspectedFrameKeys] = useState<Set<string>>(
    new Set(),
  );
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [creatingReference, setCreatingReference] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);

  const setLocalFrames = useCallback((nextFrames: EditableFrame[]) => {
    framesRef.current = nextFrames;
    setFrames(nextFrames);
  }, []);

  const setSelected = useCallback((itemId: string | null) => {
    selectedFrameIdRef.current = itemId;
    setSelectedFrameId(itemId);
  }, []);

  const markInspected = useCallback((frame: EditableFrame) => {
    const key = frameCoverageKey(frame);
    inspectedFrameKeysRef.current.add(key);
    setInspectedFrameKeys(new Set(inspectedFrameKeysRef.current));
  }, []);

  const setCurrentTime = useCallback(
    (nextUs: number, updateUrl = true) => {
      const clamped = clamp(nextUs, durationUs);
      setPlayheadUs(clamped);
      if (videoRef.current !== null) {
        videoRef.current.currentTime = clamped / 1_000_000;
      }
      if (updateUrl) updatePipelineUrl({ t_us: clamped });
    },
    [durationUs],
  );

  const selectFrame = useCallback(
    (frame: EditableFrame, seek = true) => {
      setSelected(frame.itemId);
      markInspected(frame);
      updatePipelineUrl({ item: frame.itemId });
      if (seek && frame.outcome.frame_identity !== null) {
        setCurrentTime(frame.outcome.frame_identity.requested_time_us);
      }
    },
    [markInspected, setCurrentTime, setSelected],
  );

  const hydrateReference = useCallback(
    (nextReference: PipelineReferenceResource, preserveSelection = true) => {
      const nextFrames = nextReference.draft.items
        .map(toEditableFrame)
        .filter((frame): frame is EditableFrame => frame !== null);
      referenceRef.current = nextReference;
      serverRevisionRef.current = nextReference.draft.revision;
      setReference(nextReference);
      setLocalFrames(nextFrames);
      if (!preserveSelection) {
        inspectedFrameKeysRef.current = new Set();
        setInspectedFrameKeys(new Set());
      }
      for (const entry of coverageEntries(nextReference.draft.coverage)) {
        inspectedFrameKeysRef.current.add(
          frameCoverageKeyFromIdentity(entry.frame_identity, entry.item_id),
        );
      }
      setInspectedFrameKeys(new Set(inspectedFrameKeysRef.current));
      const current = preserveSelection ? selectedFrameIdRef.current : null;
      const selected =
        nextFrames.find((frame) => frame.itemId === current) ?? nextFrames[0];
      setSelected(selected?.itemId ?? null);
    },
    [setLocalFrames, setSelected],
  );

  const loadGenerated = useCallback(
    async (signal?: AbortSignal) => {
      if (generatedRunId === null || displayedRevisionId === null) {
        setGeneratedFrames([]);
        setGeneratedLoading(false);
        return;
      }
      setGeneratedLoading(true);
      try {
        const result = await client.getVisibleCardResult(
          recordingId,
          generatedRunId,
          { signal },
        );
        if (!signal?.aborted) {
          setGeneratedFrames(readFramesFromResult(result, displayedRevisionId));
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setGeneratedLoading(false);
      }
    },
    [client, displayedRevisionId, generatedRunId, recordingId],
  );

  const loadReference = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const loaded = await client.getPipelineReference(
          recordingId,
          CONTENT_TYPE,
          { signal },
        );
        if (!signal?.aborted) {
          hydrateReference(loaded);
          setSaveState("saved");
          setError(null);
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) {
          if (reason instanceof ApiError && reason.status === 404) {
            referenceRef.current = null;
            setReference(null);
            setLocalFrames([]);
            setSelected(null);
            setError(null);
          } else {
            setError(describeError(reason));
          }
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [client, hydrateReference, recordingId, setLocalFrames, setSelected],
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
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
      }
    };
  }, [loadGenerated, loadReference, view]);

  useEffect(() => {
    const candidates = view === "reviewed" ? frames : generatedFrames;
    const urlState = readPipelineEditorUrlState();
    const selected =
      (urlState.item === null
        ? undefined
        : candidates.find((frame) => frame.itemId === urlState.item)) ??
      candidates[0];
    const timer = window.setTimeout(() => {
      if (selected !== undefined) selectFrame(selected, false);
      if (urlState.tUs !== null) setCurrentTime(urlState.tUs, false);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [frames, generatedFrames, setCurrentTime, selectFrame, view]);

  const nextCommandId = useCallback(() => {
    commandSequenceRef.current += 1;
    return `pipeline-visible-card-${Date.now()}-${commandSequenceRef.current}`;
  }, []);

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
    if (referenceRef.current === null) return;
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
      hydrateReference(nextReference);
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
        setError(describeError(reason));
        return;
      }
      if (isRetryableError(reason) && command.attempts <= RETRY_LIMIT) {
        setSaveState("retrying");
        setError(describeError(reason));
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
      setError(describeError(reason));
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
    hydrateReference,
    operatorId,
    recordingId,
    saveState,
  ]);

  useEffect(() => {
    processQueueRef.current = processQueue;
    return () => {
      if (processQueueRef.current === processQueue) {
        processQueueRef.current = null;
      }
    };
  }, [processQueue]);

  const enqueue = useCallback(
    (
      operation: PipelineReferenceOperation,
      noticeText: string,
      optimistic: (current: EditableFrame[]) => EditableFrame[],
    ) => {
      if (referenceRef.current === null) return;
      setLocalFrames(optimistic(framesRef.current));
      queueRef.current.push({
        commandId: nextCommandId(),
        operation,
        notice: noticeText,
        attempts: 0,
      });
      setQueueLength(queueRef.current.length);
      setFirstUnappliedCommand(describeCommand(queueRef.current[0]));
      setSaveState("saving");
      setError(null);
      void processQueueRef.current?.();
    },
    [nextCommandId, setLocalFrames],
  );

  const setFrameReview = useCallback(
    (frame: EditableFrame, outcome: Outcome, noticeText: string) => {
      const operation: PipelineReferenceOperation = {
        operation: "set_frame_review",
        item_id: frame.itemId,
        item: outcome,
      };
      enqueue(operation, noticeText, (current) =>
        current.map((candidate) =>
          candidate.itemId === frame.itemId
            ? { ...candidate, outcome, reviewState: "corrected" }
            : candidate,
        ),
      );
    },
    [enqueue],
  );

  const acceptSuggestions = useCallback(
    (frame: EditableFrame) => {
      enqueue(
        { operation: "accept_frame_suggestions", item_id: frame.itemId },
        "Visible-card suggestions accepted.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? { ...candidate, reviewState: "accepted" }
              : candidate,
          ),
      );
    },
    [enqueue],
  );

  const setFrameOutcome = useCallback(
    (frame: EditableFrame, outcome: "empty" | "unusable") => {
      const nextOutcome: Outcome = {
        ...frame.outcome,
        status: outcome === "empty" ? "empty" : "failed",
        candidates: [],
        error: outcome === "empty" ? null : "Reviewed unusable frame.",
      };
      enqueue(
        {
          operation:
            outcome === "empty" ? "set_frame_empty" : "set_frame_unusable",
          item_id: frame.itemId,
        },
        outcome === "empty"
          ? "Frame marked as reviewed empty."
          : "Frame marked as unusable.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? {
                  ...candidate,
                  outcome: nextOutcome,
                  reviewState: outcome,
                }
              : candidate,
          ),
      );
    },
    [enqueue],
  );

  const openEditor = useCallback(
    (frame: EditableFrame, candidate: Candidate | null) => {
      if (frame.outcome.frame_identity === null) return;
      setEditorError(null);
      setEditor({
        frameItemId: frame.itemId,
        cardId: candidate?.card_id ?? null,
        polygons:
          candidate === null ? [[]] : geometryPolygons(candidate.geometry),
        polygonIndex: 0,
        selectedPointIndex: null,
      });
    },
    [],
  );

  const saveEditor = useCallback(() => {
    const currentEditor = editorRef.current;
    const frame = framesRef.current.find(
      (candidate) => candidate.itemId === currentEditor?.frameItemId,
    );
    if (currentEditor === null || frame === undefined) return;
    const validation = validatePolygons(currentEditor.polygons);
    if (validation !== null) {
      setEditorError(validation);
      return;
    }
    const candidates = frame.outcome.candidates.map((candidate) =>
      candidate.card_id === currentEditor.cardId
        ? {
            ...candidate,
            geometry: reviewedGeometry(currentEditor.polygons),
          }
        : candidate,
    );
    if (currentEditor.cardId === null) {
      candidates.push({
        card_id: nextManualCardId(frame),
        geometry: reviewedGeometry(currentEditor.polygons),
        normalization: {
          width: frame.outcome.frame_identity?.width ?? 1,
          height: frame.outcome.frame_identity?.height ?? 1,
          policy_id: "full-frame-0-1000/v1",
        },
      });
    }
    setFrameReview(
      frame,
      {
        ...frame.outcome,
        status: "detected",
        candidates,
        error: null,
      },
      currentEditor.cardId === null
        ? "Missed visible card added."
        : "Visible-card geometry saved.",
    );
    setEditor(null);
    setEditorError(null);
  }, [setFrameReview]);

  useEffect(() => {
    editorRef.current = editor;
    saveEditorRef.current = saveEditor;
  }, [editor, saveEditor]);

  const removeCard = useCallback(
    (frame: EditableFrame, cardId: string) => {
      const candidates = frame.outcome.candidates.filter(
        (candidate) => candidate.card_id !== cardId,
      );
      setFrameReview(
        frame,
        {
          ...frame.outcome,
          status: candidates.length === 0 ? "empty" : "detected",
          candidates,
          error: null,
        },
        "Visible card removed from the frame review.",
      );
    },
    [setFrameReview],
  );

  const handleCanvasPointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      const point = pointFromEvent(event);
      if (point === null) return;
      setEditor((current) => {
        if (current === null) return current;
        const polygons = current.polygons.map((polygon) => [...polygon]);
        const polygon = polygons[drag.polygonIndex];
        if (polygon?.[drag.pointIndex] === undefined) return current;
        polygon[drag.pointIndex] = point;
        drag.dirty = true;
        return { ...current, polygons };
      });
    },
    [],
  );

  const stopCanvasPointer = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      dragRef.current = null;
      if (drag.dirty) {
        window.setTimeout(() => void saveEditorRef.current?.(), 0);
      }
    },
    [],
  );

  const startPointDrag = useCallback(
    (
      event: ReactPointerEvent<SVGCircleElement>,
      polygonIndex: number,
      pointIndex: number,
    ) => {
      event.preventDefault();
      event.stopPropagation();
      dragRef.current = {
        pointerId: event.pointerId,
        polygonIndex,
        pointIndex,
        dirty: false,
      };
      event.currentTarget.setPointerCapture?.(event.pointerId);
      setEditor((current) =>
        current === null
          ? current
          : { ...current, polygonIndex, selectedPointIndex: pointIndex },
      );
    },
    [],
  );

  const completeReference = useCallback(async () => {
    const current = referenceRef.current;
    const currentFrames = framesRef.current;
    const pending = currentFrames.filter(
      (frame) =>
        frame.reviewState === "pending" || frame.reviewState === "affected",
    );
    const missingCoverage = currentFrames.filter(
      (frame) =>
        !inspectedFrameKeysRef.current.has(frameCoverageKey(frame)) ||
        frameDecision(frame) === null,
    );
    if (
      current === null ||
      current.state.draft_state === "completed" ||
      reviewerId.trim() === "" ||
      pending.length > 0 ||
      missingCoverage.length > 0 ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      saveState !== "saved"
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
            kind: "visible_frames",
            frames: currentFrames.map((frame) => ({
              item_id: frame.itemId,
              frame_identity: frame.outcome.frame_identity,
              decision: frameDecision(frame) as "cards" | "empty" | "unusable",
            })),
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
      setError(describeError(reason));
    } finally {
      setCompletionBusy(false);
    }
  }, [client, hydrateReference, recordingId, reviewerId, saveState]);

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
        "Maintained visible-card reference created from the selected generated result.",
      );
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 409) {
        await loadReference();
      } else {
        setError(describeError(reason));
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
        "Winning draft loaded. The queued visible-card commands will be retried in order.",
      );
      window.setTimeout(() => void processQueueRef.current?.(), 0);
    } catch (reason: unknown) {
      setSaveState("error");
      setError(describeError(reason));
    }
  }, [client, hydrateReference, recordingId]);

  const retryQueuedCommands = useCallback(() => {
    if (queueRef.current.length === 0) return;
    queueRef.current[0].attempts = 0;
    setSaveState("saving");
    setError(null);
    void processQueueRef.current?.();
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      ) {
        return;
      }
      const current = framesRef.current;
      const index = current.findIndex(
        (frame) => frame.itemId === selectedFrameIdRef.current,
      );
      if (event.key === " " && videoRef.current !== null) {
        event.preventDefault();
        if (videoRef.current.paused) {
          void videoRef.current.play().catch(() => undefined);
        } else {
          videoRef.current.pause();
        }
      } else if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        selectFrame(current[index - 1]);
      } else if (
        event.key === "ArrowRight" &&
        index >= 0 &&
        index < current.length - 1
      ) {
        event.preventDefault();
        selectFrame(current[index + 1]);
      } else if (event.key === "n" || event.key === "N") {
        const frame = current[index >= 0 ? index : 0];
        if (frame !== undefined) {
          event.preventDefault();
          openEditor(frame, null);
        }
      } else if (event.key === "a" || event.key === "A") {
        const frame = current[index];
        if (frame?.outcome.status === "detected") {
          event.preventDefault();
          acceptSuggestions(frame);
        }
      } else if (event.key === "e" || event.key === "E") {
        const frame = current[index];
        if (frame !== undefined) {
          event.preventDefault();
          setFrameOutcome(frame, "empty");
        }
      } else if (event.key === "u" || event.key === "U") {
        const frame = current[index];
        if (frame !== undefined) {
          event.preventDefault();
          setFrameOutcome(frame, "unusable");
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [acceptSuggestions, openEditor, selectFrame, setFrameOutcome]);

  const activeFrame =
    (view === "reviewed" ? frames : generatedFrames).find(
      (frame) => frame.itemId === selectedFrameId,
    ) ?? null;
  const reviewed = view === "reviewed";
  const pendingCount = frames.filter(
    (frame) =>
      frame.reviewState === "pending" || frame.reviewState === "affected",
  ).length;
  const completedFrameCount = frames.filter(
    (frame) => frameDecision(frame) !== null,
  ).length;
  const coveragePercent =
    frames.length === 0 ? 0 : (inspectedFrameKeys.size / frames.length) * 100;
  const completionBlocker =
    !reviewed || reference === null
      ? null
      : reference.state.draft_state === "completed"
        ? "Reference is already complete; make a correction before publishing."
        : pendingCount > 0
          ? `${pendingCount} frame${pendingCount === 1 ? "" : "s"} still need a review decision.`
          : completedFrameCount < frames.length || coveragePercent < 100
            ? "Inspect and decide every resolved frame, including empty and unusable frames."
            : queueLength > 0 ||
                saveState === "saving" ||
                saveState === "retrying"
              ? "Wait for all visible-card commands to save."
              : saveState !== "saved"
                ? "Resolve the visible-card save problem before completing the reference."
                : reviewerId.trim() === ""
                  ? "Enter the reviewer ID before completing the reference."
                  : null;

  if (!reviewed) {
    return (
      <GeneratedVisibleCardView
        frames={generatedFrames}
        loading={generatedLoading}
        revisionId={displayedRevisionId}
        recordingId={recordingId}
        onSelect={(frame) => selectFrame(frame)}
      />
    );
  }
  if (loading) {
    return (
      <p className={styles.detailEmptyState}>
        Loading maintained visible-card reference…
      </p>
    );
  }
  if (reference === null) {
    return (
      <section
        className={styles.cardEventReviewPanel}
        aria-label="Start visible-card review"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Maintained reference</p>
            <h3>Start visible-card review</h3>
          </div>
          <span className={styles.countLabel}>
            {generatedFrames.length} frame suggestions
          </span>
        </div>
        <p className={styles.detailLead}>
          Review visible regions in one recording-owned reference. Generated
          detector output stays immutable.
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
      aria-label="Visible-card maintained reference editor"
    >
      <div className={styles.cardEventReviewHeader}>
        <div>
          <p className={styles.statusLabel}>Maintained reference</p>
          <h3>Visible-card review</h3>
          <p className={styles.detailLead}>
            {reference.draft.source_revision_id === null
              ? "Manual visible-card reference"
              : `Used visible-card suggestions ${reference.draft.source_revision_id}`}
          </p>
        </div>
        <div
          className={styles.cardEventReviewCounts}
          aria-label="Visible-card counts"
        >
          <ReviewCount label="Decided" value={completedFrameCount} />
          <ReviewCount label="Pending" value={pendingCount} />
          <ReviewCount
            label="Coverage"
            value={Math.round(coveragePercent)}
            suffix="%"
          />
        </div>
      </div>

      <div className={styles.cardEventPipelineVideoGrid}>
        <aside
          className={styles.visibleCardItemRail}
          aria-label="Resolved frames"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Source items</p>
              <h4>Resolved frames</h4>
            </div>
            <span className={styles.countLabel}>{frames.length}</span>
          </div>
          <ol className={styles.visibleCardItemList}>
            {frames.map((frame, index) => (
              <li key={frame.itemId}>
                <button
                  className={styles.visibleCardItemButton}
                  type="button"
                  data-selected={frame.itemId === selectedFrameId}
                  onClick={() => selectFrame(frame)}
                >
                  <span>Frame {index + 1}</span>
                  <strong>{formatFrameTime(frame)}</strong>
                  <small>{formatFrameState(frame)}</small>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <div>
          <video
            ref={videoRef}
            className={styles.cardEventSourceVideo}
            src={videoUrl}
            controls
            preload="metadata"
            aria-label={`Visible-card source video ${recordingId}`}
            onTimeUpdate={(event) => {
              const value = clamp(
                event.currentTarget.currentTime * 1_000_000,
                durationUs,
              );
              setPlayheadUs(value);
              updatePipelineUrl({ t_us: value });
            }}
          />
          <div
            className={styles.cardEventTimeline}
            aria-label="Resolved-frame timeline"
          >
            {frames.map((frame) => (
              <button
                key={frame.itemId}
                className={styles.cardEventMarker}
                type="button"
                data-selected={frame.itemId === selectedFrameId}
                data-state={frame.reviewState}
                style={{
                  left: `${((frame.outcome.frame_identity?.requested_time_us ?? 0) / Math.max(durationUs, 1)) * 100}%`,
                }}
                aria-label={`Select frame ${formatFrameTime(frame)}`}
                onClick={() => selectFrame(frame)}
              />
            ))}
          </div>
          <p className={styles.pipelineUrlState}>
            Playhead {formatMicroseconds(playheadUs)} ·{" "}
            {inspectedFrameKeys.size}/{frames.length} resolved frames inspected
          </p>

          {activeFrame === null ? (
            <p className={styles.detailEmptyState}>Select a resolved frame.</p>
          ) : (
            <VisibleCardFramePanel
              recordingId={recordingId}
              frame={activeFrame}
              editor={
                editor?.frameItemId === activeFrame.itemId ? editor : null
              }
              editorError={editorError}
              onOpenEditor={(candidate) => openEditor(activeFrame, candidate)}
              onSaveEditor={saveEditor}
              onCancelEditor={() => setEditor(null)}
              onAccept={() => acceptSuggestions(activeFrame)}
              onEmpty={() => setFrameOutcome(activeFrame, "empty")}
              onUnusable={() => setFrameOutcome(activeFrame, "unusable")}
              onRemoveCard={(cardId) => removeCard(activeFrame, cardId)}
              onPointerMove={handleCanvasPointerMove}
              onPointerUp={stopCanvasPointer}
              onPointPointerDown={startPointDrag}
              disabled={false}
            />
          )}
        </div>
      </div>

      <section
        className={styles.cardEventCoverage}
        aria-label="Visible-card review coverage"
      >
        <span>Resolved-frame coverage</span>
        <strong>{Math.round(coveragePercent)}% inspected</strong>
        <progress
          max={100}
          value={coveragePercent}
          aria-label="Resolved-frame coverage"
        />
        <p>
          Each frame needs an explicit cards, reviewed empty, or unusable
          decision.
        </p>
      </section>
      <section
        className={styles.cardEventCompletionBar}
        aria-label="Complete maintained visible-card reference"
      >
        <div>
          <p className={styles.statusLabel}>Review completion</p>
          <strong>Complete resolved-frame review</strong>
          {completionBlocker !== null ? (
            <p className={styles.cardEventCompletionRequirement}>
              {completionBlocker}
            </p>
          ) : null}
        </div>
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
          {completionBusy ? "Completing reference…" : "Complete reference"}
        </button>
      </section>

      <details className={styles.cardEventGuidance}>
        <summary>Keyboard shortcuts</summary>
        <p>
          Space play/pause · ←/→ previous/next frame · A accept suggestions · E
          reviewed empty · U unusable · N add missed card.
        </p>
      </details>
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
    </section>
  );
}

function VisibleCardFramePanel({
  recordingId,
  frame,
  editor,
  editorError,
  onOpenEditor,
  onSaveEditor,
  onCancelEditor,
  onAccept,
  onEmpty,
  onUnusable,
  onRemoveCard,
  onPointerMove,
  onPointerUp,
  onPointPointerDown,
  disabled,
}: {
  recordingId: string;
  frame: EditableFrame;
  editor: EditorState | null;
  editorError: string | null;
  onOpenEditor: (candidate: Candidate | null) => void;
  onSaveEditor: () => void;
  onCancelEditor: () => void;
  onAccept: () => void;
  onEmpty: () => void;
  onUnusable: () => void;
  onRemoveCard: (cardId: string) => void;
  onPointerMove: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerUp: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointPointerDown: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  disabled: boolean;
}) {
  const identity = frame.outcome.frame_identity;
  const width = identity?.width ?? 1;
  const height = identity?.height ?? 1;
  const sourceUrl =
    identity === null
      ? null
      : pipelineDerivedFramePath(recordingId, identity.requested_time_us);
  return (
    <section
      className={styles.visibleCardFramePanel}
      aria-label="Selected visible-card frame"
    >
      <header className={styles.visibleCardFrameHeader}>
        <div>
          <p className={styles.statusLabel}>Source item {frame.itemId}</p>
          <h3>{formatFrameTime(frame)} · resolved frame</h3>
        </div>
        <span className={styles.status} data-state={frame.reviewState}>
          {formatIdentifier(frame.reviewState)}
        </span>
      </header>
      {sourceUrl !== null ? (
        <div
          className={styles.visibleCardCanvasViewport}
          style={{ aspectRatio: `${width} / ${height}` }}
        >
          <img
            className={styles.visibleCardCanvasImage}
            src={sourceUrl}
            width={width}
            height={height}
            alt={`Resolved source frame at ${formatFrameTime(frame)}`}
          />
          <svg
            className={styles.visibleCardOverlay}
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`${frame.outcome.candidates.length} visible-card proposal${frame.outcome.candidates.length === 1 ? "" : "s"}`}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            style={{ pointerEvents: editor === null ? "none" : "auto" }}
          >
            {frame.outcome.candidates.map((candidate) => (
              <CandidateOverlay
                key={candidate.card_id}
                candidate={candidate}
                width={width}
                height={height}
              />
            ))}
            {editor?.polygons.map((polygon, polygonIndex) => (
              <g key={`editor-${polygonIndex}`}>
                {polygon.length >= 2 ? (
                  <polygon
                    points={polygon
                      .map(
                        (point) =>
                          `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
                      )
                      .join(" ")}
                    fill="rgba(255, 210, 79, 0.25)"
                    stroke="#ffd24f"
                    strokeWidth={Math.max(1, width / 250)}
                  />
                ) : null}
                {polygon.map((point, pointIndex) => (
                  <circle
                    key={`${point.x}:${point.y}:${pointIndex}`}
                    cx={(point.x * width) / 1000}
                    cy={(point.y * height) / 1000}
                    r={Math.max(3, width / 55)}
                    fill="#ffd24f"
                    tabIndex={0}
                    role="button"
                    aria-label={`Polygon ${polygonIndex + 1}, point ${pointIndex + 1} at ${point.x}, ${point.y}`}
                    onPointerDown={(event) =>
                      onPointPointerDown(event, polygonIndex, pointIndex)
                    }
                    onClick={(event) => event.stopPropagation()}
                  />
                ))}
              </g>
            ))}
          </svg>
        </div>
      ) : (
        <p className={styles.detailBlocker}>
          {frame.outcome.error ??
            "No resolved source frame is available. Mark this frame unusable."}
        </p>
      )}
      <div
        className={styles.visibleCardOutcomeButtons}
        aria-label="Frame outcome"
      >
        <button
          className={styles.primaryButton}
          type="button"
          onClick={onAccept}
          disabled={disabled || frame.outcome.status !== "detected"}
        >
          Accept frame suggestions
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onEmpty}
          disabled={disabled}
        >
          Reviewed empty frame
        </button>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={onUnusable}
          disabled={disabled}
        >
          Unusable frame
        </button>
      </div>
      {frame.outcome.error !== null ? (
        <p className={styles.detailBlocker}>{frame.outcome.error}</p>
      ) : null}
      <section
        className={styles.visibleCardProposalList}
        aria-label="Visible-card proposals"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Detector output</p>
            <h4>Proposal overlays</h4>
          </div>
          <span className={styles.countLabel}>
            {frame.outcome.candidates.length}
          </span>
        </div>
        {frame.outcome.candidates.length === 0 ? (
          <p className={styles.detailEmptyState}>
            No visible-card proposals. Use Add missed card or mark the frame
            reviewed empty.
          </p>
        ) : (
          <ol className={styles.visibleCardProposalItems}>
            {frame.outcome.candidates.map((candidate, index) => (
              <li key={candidate.card_id}>
                <div className={styles.visibleCardProposalRow}>
                  <span>
                    <strong>Proposal {index + 1}</strong>
                    <small>
                      {candidate.card_id} ·{" "}
                      {formatIdentifier(candidate.geometry.kind)}
                    </small>
                  </span>
                  <div className={styles.visibleCardActionButtons}>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => onOpenEditor(candidate)}
                    >
                      Reshape proposal {index + 1}
                    </button>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => onRemoveCard(candidate.card_id)}
                    >
                      Remove card {index + 1}
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
      <button
        className={styles.primaryButton}
        type="button"
        onClick={() => onOpenEditor(null)}
        disabled={identity === null}
      >
        Add missed card
      </button>
      {editor !== null ? (
        <section
          className={styles.visibleCardEditor}
          aria-label="Visible region editor"
        >
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.statusLabel}>Geometry editor</p>
              <h4>
                {editor.cardId === null
                  ? "Add missed card"
                  : "Reshape visible region"}
              </h4>
            </div>
          </div>
          <p className={styles.visibleCardEditorHelp}>
            Drag a polygon point. The complete visible region is saved once when
            the pointer is released.
          </p>
          {editorError !== null ? (
            <p className={styles.inlineFormError}>{editorError}</p>
          ) : null}
          <div className={styles.visibleCardActionButtons}>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={onSaveEditor}
            >
              Save visible region
            </button>
            <button
              className={styles.secondaryButton}
              type="button"
              onClick={onCancelEditor}
            >
              Cancel
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}

function CandidateOverlay({
  candidate,
  width,
  height,
}: {
  candidate: Candidate;
  width: number;
  height: number;
}) {
  const geometry = candidate.geometry;
  if (
    geometry.kind === "reviewed-visible-region/v1" &&
    geometry.visible_region !== undefined
  ) {
    return (
      <g data-card-id={candidate.card_id}>
        <polygon
          points={geometry.visible_region.polygons
            .flat()
            .map(
              (point) =>
                `${(point.x * width) / 1000},${(point.y * height) / 1000}`,
            )
            .join(" ")}
          fill="rgba(59, 209, 154, 0.2)"
          stroke="#3bd19a"
          strokeWidth={Math.max(1, width / 250)}
        />
      </g>
    );
  }
  const box = geometry.box_2d;
  if (box === undefined) return null;
  return (
    <rect
      data-card-id={candidate.card_id}
      x={(box.x_min * width) / 1000}
      y={(box.y_min * height) / 1000}
      width={((box.x_max - box.x_min) * width) / 1000}
      height={((box.y_max - box.y_min) * height) / 1000}
      fill="rgba(255, 133, 84, 0.16)"
      stroke="#ff8554"
      strokeWidth={Math.max(1, width / 250)}
    />
  );
}

function GeneratedVisibleCardView({
  frames,
  loading,
  revisionId,
  recordingId,
  onSelect,
}: {
  frames: EditableFrame[];
  loading: boolean;
  revisionId: string | null;
  recordingId: string;
  onSelect: (frame: EditableFrame) => void;
}) {
  return (
    <section
      className={styles.cardEventReviewPanel}
      aria-label="Generated visible-card result"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Generated result</p>
          <h3>Visible-card suggestions</h3>
        </div>
        <span className={styles.countLabel}>{frames.length} frames</span>
      </div>
      <p className={styles.detailLead}>
        Generated detector output is immutable. Choose Review to copy this exact
        result into the maintained reference.
      </p>
      {revisionId !== null ? (
        <p className={styles.pipelineUrlState}>Source revision {revisionId}</p>
      ) : null}
      {loading ? (
        <p className={styles.detailEmptyState}>
          Loading generated visible cards…
        </p>
      ) : frames.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No generated visible-card result is selected.
        </p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.cardEventReviewTable}>
            <caption className={styles.visuallyHidden}>
              Generated visible-card suggestions
            </caption>
            <thead>
              <tr>
                <th scope="col">Frame</th>
                <th scope="col">Resolved time</th>
                <th scope="col">Status</th>
                <th scope="col">Cards</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {frames.map((frame, index) => (
                <tr key={frame.itemId}>
                  <td>
                    <button
                      className={styles.cardEventTableSelect}
                      type="button"
                      onClick={() => onSelect(frame)}
                    >
                      Frame {index + 1}
                    </button>
                  </td>
                  <td>{formatFrameTime(frame)}</td>
                  <td>{formatIdentifier(frame.outcome.status)}</td>
                  <td>{frame.outcome.candidates.length}</td>
                  <td>
                    {frame.outcome.frame_identity === null
                      ? "Unavailable"
                      : pipelineDerivedFramePath(
                          recordingId,
                          frame.outcome.frame_identity.requested_time_us,
                        )}
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

function toEditableFrame(item: PipelineReferenceItem): EditableFrame | null {
  const outcome = readOutcome(item.item);
  if (outcome === null || !isFrameReviewState(item.review_state)) return null;
  return {
    itemId: item.item_id,
    baseItemId: item.base_item_id,
    reviewState: item.review_state,
    outcome,
  };
}

function readFramesFromResult(
  result: PipelineVisibleCardResult,
  revisionId: string,
): EditableFrame[] {
  const revision =
    result.revisions.find(
      (candidate) => candidate.manifest.revision_id === revisionId,
    ) ?? result.revisions[0];
  const outcomes = revision?.content.outcomes;
  if (!Array.isArray(outcomes)) return [];
  const frames: Array<EditableFrame | null> = outcomes.map((item) => {
    const outcome = readOutcome(item);
    return outcome === null
      ? null
      : {
          itemId: outcome.event_id,
          baseItemId: null,
          reviewState: "pending" as const,
          outcome,
        };
  });
  return frames.filter((frame): frame is EditableFrame => frame !== null);
}

function readOutcome(value: Record<string, unknown>): Outcome | null {
  const eventId = value.event_id;
  const status = value.status;
  const rawFrame = value.frame_identity;
  const rawCandidates = value.candidates;
  if (
    typeof eventId !== "string" ||
    !["detected", "empty", "failed"].includes(String(status)) ||
    !Array.isArray(rawCandidates)
  )
    return null;
  const frame = rawFrame === null ? null : readFrameIdentity(rawFrame);
  if (rawFrame !== null && frame === null) return null;
  const candidates = rawCandidates
    .map(readCandidate)
    .filter((candidate): candidate is Candidate => candidate !== null);
  return {
    event_id: eventId,
    frame_identity: frame,
    status: status as Outcome["status"],
    candidates,
    error: typeof value.error === "string" ? value.error : null,
  };
}

function readFrameIdentity(value: unknown): FrameIdentity | null {
  if (
    !isRecord(value) ||
    !isInteger(value.requested_time_us) ||
    !isInteger(value.frame_index) ||
    !isInteger(value.presentation_timestamp_us) ||
    !isInteger(value.width) ||
    !isInteger(value.height)
  )
    return null;
  return value as FrameIdentity;
}

function readCandidate(value: unknown): Candidate | null {
  if (
    !isRecord(value) ||
    typeof value.card_id !== "string" ||
    !isRecord(value.geometry) ||
    !isRecord(value.normalization)
  )
    return null;
  const geometry = readGeometry(value.geometry);
  if (geometry === null) return null;
  return {
    card_id: value.card_id,
    geometry,
    normalization: value.normalization,
    ...(Array.isArray(value.model_scores)
      ? { model_scores: value.model_scores.filter(isRecord) }
      : {}),
  };
}

function readGeometry(value: Record<string, unknown>): Geometry | null {
  const box = isRecord(value.box_2d) ? value.box_2d : null;
  if (
    value.kind === "detector-box/v1" &&
    box !== null &&
    ["x_min", "y_min", "x_max", "y_max"].every((key) => isInteger(box[key]))
  )
    return { kind: String(value.kind), box_2d: box as Geometry["box_2d"] };
  const region = isRecord(value.visible_region) ? value.visible_region : null;
  if (
    value.kind === "reviewed-visible-region/v1" &&
    region !== null &&
    Array.isArray(region.polygons)
  )
    return {
      kind: String(value.kind),
      visible_region: {
        polygons: region.polygons
          .filter(Array.isArray)
          .map(
            (polygon) =>
              polygon
                .filter(isRecord)
                .filter(
                  (point) => isInteger(point.x) && isInteger(point.y),
                ) as Point[],
          ),
      },
    };
  return null;
}

function geometryPolygons(geometry: Geometry): Point[][] {
  if (geometry.visible_region !== undefined)
    return geometry.visible_region.polygons.map((polygon) => [...polygon]);
  const box = geometry.box_2d;
  return box === undefined
    ? [[]]
    : [
        [
          { x: box.x_min, y: box.y_min },
          { x: box.x_max, y: box.y_min },
          { x: box.x_max, y: box.y_max },
          { x: box.x_min, y: box.y_max },
        ],
      ];
}

function reviewedGeometry(polygons: Point[][]): Geometry {
  return {
    kind: "reviewed-visible-region/v1",
    visible_region: {
      polygons: polygons.map((polygon) =>
        polygon.map((point) => ({
          x: Math.round(point.x),
          y: Math.round(point.y),
        })),
      ),
    },
  };
}

function validatePolygons(polygons: Point[][]): string | null {
  if (polygons.length === 0 || polygons.some((polygon) => polygon.length < 3))
    return "Each visible region needs at least three points.";
  if (
    polygons.some((polygon) =>
      polygon.some(
        (point) =>
          point.x < 0 || point.x > 1000 || point.y < 0 || point.y > 1000,
      ),
    )
  )
    return "Polygon points must stay inside the frame.";
  if (polygons.some((polygon) => Math.abs(polygonArea(polygon)) === 0))
    return "Each polygon must have positive area.";
  return null;
}

function polygonArea(polygon: Point[]): number {
  return polygon.reduce((area, point, index) => {
    const next = polygon[(index + 1) % polygon.length];
    return area + point.x * next.y - next.x * point.y;
  }, 0);
}

function pointFromEvent(event: ReactPointerEvent<SVGSVGElement>): Point | null {
  const rect = event.currentTarget.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  return {
    x: clamp(((event.clientX - rect.left) / rect.width) * 1000, 1000),
    y: clamp(((event.clientY - rect.top) / rect.height) * 1000, 1000),
  };
}

function frameCoverageKey(frame: EditableFrame): string {
  return frameCoverageKeyFromIdentity(
    frame.outcome.frame_identity,
    frame.itemId,
  );
}

function frameCoverageKeyFromIdentity(
  identity: FrameIdentity | null,
  itemId: string | null,
): string {
  return identity === null
    ? `item:${itemId ?? "unknown"}`
    : JSON.stringify(identity, Object.keys(identity).sort());
}

function coverageEntries(
  value: Record<string, unknown> | null,
): Array<{ frame_identity: FrameIdentity | null; item_id: string | null }> {
  if (!isRecord(value) || !Array.isArray(value.frames)) return [];
  return value.frames.flatMap((entry) => {
    if (!isRecord(entry)) return [];
    const identity =
      entry.frame_identity === null
        ? null
        : readFrameIdentity(entry.frame_identity);
    return identity !== null || entry.frame_identity === null
      ? [
          {
            frame_identity: identity,
            item_id: typeof entry.item_id === "string" ? entry.item_id : null,
          },
        ]
      : [];
  });
}

function frameDecision(
  frame: EditableFrame,
): "cards" | "empty" | "unusable" | null {
  if (
    frame.outcome.status === "detected" &&
    ["accepted", "added", "corrected"].includes(frame.reviewState) &&
    frame.outcome.candidates.length > 0
  )
    return "cards";
  if (frame.outcome.status === "empty" && frame.reviewState === "empty")
    return "empty";
  if (frame.outcome.status === "failed" && frame.reviewState === "unusable")
    return "unusable";
  return null;
}

function nextManualCardId(frame: EditableFrame): string {
  return `manual-${frame.itemId}-${Date.now()}`;
}

function isFrameReviewState(value: string): value is FrameReviewState {
  return [
    "pending",
    "accepted",
    "rejected",
    "added",
    "corrected",
    "empty",
    "unusable",
    "affected",
  ].includes(value);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}
function clamp(value: number, maximum: number): number {
  return Math.min(
    Math.max(0, Math.round(value)),
    Math.max(0, Math.round(maximum)),
  );
}
function formatFrameTime(frame: EditableFrame): string {
  return formatMicroseconds(
    frame.outcome.frame_identity?.requested_time_us ?? 0,
  );
}
function formatFrameState(frame: EditableFrame): string {
  return `${formatIdentifier(frame.outcome.status)} · ${formatIdentifier(frame.reviewState)}`;
}
function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)} s`;
}
function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}
function describeCommand(command: PendingCommand | undefined): string {
  return command === undefined
    ? "none"
    : `${formatIdentifier(command.operation.operation)} ${command.operation.item_id ?? "frame"}`;
}
function isRetryableError(reason: unknown): boolean {
  return !(
    reason instanceof ApiError &&
    reason.status >= 400 &&
    reason.status < 500
  );
}
function describeError(reason: unknown): string {
  if (
    reason instanceof ApiError &&
    isRecord(reason.body) &&
    isRecord(reason.body.error) &&
    typeof reason.body.error.message === "string"
  )
    return reason.body.error.message;
  return reason instanceof Error
    ? reason.message
    : "The visible-card reference could not be saved.";
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
function ReviewCount({
  label,
  value,
  suffix = "",
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  return (
    <div>
      <span className={styles.statusLabel}>{label}</span>
      <strong>
        {value}
        {suffix}
      </strong>
    </div>
  );
}
