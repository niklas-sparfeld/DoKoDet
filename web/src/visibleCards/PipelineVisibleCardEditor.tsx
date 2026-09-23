import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import {
  ApiError,
  createDokoDetectorClient,
  type CalibrationRefinementResponse,
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineProposalRunResponse,
  type PipelineVisibleCardResult,
} from "../api/client";
import styles from "../App.module.css";
import {
  findAdjacentUnfinishedItem,
  ignoresReviewNavigationShortcut,
} from "../reviewNavigation";
import { Toast } from "../Toast";
import {
  describeCommand,
  frameReviewStatus,
  formatFrameTime,
} from "./PipelineVisibleCardFormatting";
import {
  readProfileName,
  subscribeToProfileName,
  useProfileName,
} from "../profile/profile";
import {
  VisibleCardInspectorPortals,
  useVisibleCardProposalSlot,
  useVisibleCardInspectorSlots,
} from "./PipelineVisibleCardInspector";
import {
  visibleCardReviewPrewarmUrls,
  VisibleCardReviewNavigation,
} from "./PipelineVisibleCardPresentation";
import visibleStyles from "./PipelineVisibleCardEditor.module.css";
import {
  calibrationFitOutlinesForFrame,
  readCalibrationFitDiagnostics,
  type CalibrationFitDiagnosticOutline,
} from "./CalibrationFitDiagnostics";
import {
  VisibleCardReviewWorkbench,
  type VisibleCardReviewWorkbenchAction,
  type VisibleCardFrameDecision,
} from "./VisibleCardReviewWorkbench";
import type { WorkbenchSelection } from "./VisibleCardReviewWorkbenchState";
import {
  readPoseScene,
  withCalibrationAnchorCommandDigest,
  type CalibrationAnchorCommand,
} from "./PoseBasedVisibleCardScene";
import { usePipelineReviewPrewarm } from "../pipeline/pipelineReviewPrewarm";
import type {
  Candidate,
  EditableFrame,
  IgnoreRegion,
  IgnoreRegionSourceCandidate,
  EditorState,
  FrameIdentity,
  FrameReviewState,
  Geometry,
  Outcome,
  PendingCommand,
  PipelineVisibleCardRailItem,
  Point,
  SaveState,
} from "./PipelineVisibleCardTypes";

export type { PipelineVisibleCardRailItem } from "./PipelineVisibleCardTypes";

const CONTENT_TYPE = "visible_cards" as const;
const RETRY_LIMIT = 3;
const POINT_DRAG_THRESHOLD_PX = 4;
const POLYGON_SWITCH_CLEARANCE_RATIO = 0.08;
export type PipelineVisibleCardEditorProps = {
  recordingId: string;
  durationUs: number;
  selectionItemId?: string | null;
  selectionTimeUs?: number | null;
  generatedRevisionId: string | null;
  displayedRevisionId?: string | null;
  generatedRunId: string | null;
  view: "generated" | "reviewed";
  onRailItemsChange?: (items: PipelineVisibleCardRailItem[]) => void;
  onReviewRequested?: () => void;
  inspectorEnabled?: boolean;
};

export function PipelineVisibleCardEditor({
  recordingId,
  durationUs,
  selectionItemId,
  selectionTimeUs,
  generatedRevisionId,
  displayedRevisionId = generatedRevisionId,
  generatedRunId,
  view,
  onRailItemsChange,
  onReviewRequested,
  inspectorEnabled = true,
}: PipelineVisibleCardEditorProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const profileName = useProfileName();
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
  const saveEditorRef = useRef<((closeEditor?: boolean) => void) | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    polygonIndex: number;
    pointIndex: number;
    startClientX: number;
    startClientY: number;
    dragging: boolean;
    dirty: boolean;
  } | null>(null);
  const [reference, setReference] = useState<PipelineReferenceResource | null>(
    null,
  );
  const [frames, setFrames] = useState<EditableFrame[]>([]);
  const [generatedFrames, setGeneratedFrames] = useState<EditableFrame[]>([]);
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>(
    [],
  );
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
  const [inspectedFrameKeys, setInspectedFrameKeys] = useState<Set<string>>(
    new Set(),
  );
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [creatingReference, setCreatingReference] = useState(false);
  const [rebasingReference, setRebasingReference] = useState(false);
  const [rebasingProposal, setRebasingProposal] = useState(false);
  const [completionBusy, setCompletionBusy] = useState(false);
  const [proposalRun, setProposalRun] =
    useState<PipelineProposalRunResponse | null>(null);
  const [proposalRevisionId, setProposalRevisionId] = useState<string | null>(
    null,
  );
  const [proposalLoading, setProposalLoading] = useState(false);
  const [visibleCalibrationStatuses, setVisibleCalibrationStatuses] = useState<
    CalibrationFitDiagnosticOutline["status"][]
  >(["fit", "held_out", "discarded"]);
  const [proposalError, setProposalError] = useState<string | null>(null);
  const [calibrationRefinement, setCalibrationRefinement] =
    useState<CalibrationRefinementResponse | null>(null);
  const [calibrationLoading, setCalibrationLoading] = useState(false);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const inspectorSlots = useVisibleCardInspectorSlots(inspectorEnabled, view);
  const proposalSlot = useVisibleCardProposalSlot();
  useEffect(
    () =>
      subscribeToProfileName(() => {
        const nextProfileName = readProfileName();
        setOperatorId(nextProfileName);
        setReviewerId(nextProfileName);
      }),
    [],
  );
  const generatedSourceRevisionId = displayedRevisionId ?? generatedRevisionId;
  const referenceNeedsSeed =
    reference !== null &&
    reference.draft.source_revision_id === null &&
    reference.draft.items.length === 0 &&
    generatedSourceRevisionId !== null;
  const usesMaintainedFrames =
    view === "reviewed" && reference !== null && !referenceNeedsSeed;

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
      if (updateUrl) updatePipelineUrl({ t_us: clamped });
    },
    [durationUs],
  );

  const endEditMode = useCallback(() => {
    dragRef.current = null;
    setEditor(null);
    setSelectedCandidateIds([]);
    setEditorError(null);
  }, []);

  const selectFrame = useCallback(
    (frame: EditableFrame, seek = true) => {
      if (selectedFrameIdRef.current !== frame.itemId) endEditMode();
      setSelected(frame.itemId);
      if (view === "reviewed") markInspected(frame);
      updatePipelineUrl({ item: frame.itemId });
      if (seek && frame.outcome.frame_identity !== null) {
        setCurrentTime(frame.outcome.frame_identity.requested_time_us);
      }
    },
    [endEditMode, markInspected, setCurrentTime, setSelected, view],
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
      const revisionId = generatedSourceRevisionId;
      if (generatedRunId === null || revisionId === null) {
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
          setGeneratedFrames(readFramesFromResult(result, revisionId));
        }
      } catch (reason: unknown) {
        if (!signal?.aborted) setError(describeError(reason));
      } finally {
        if (!signal?.aborted) setGeneratedLoading(false);
      }
    },
    [client, generatedSourceRevisionId, generatedRunId, recordingId],
  );

  const settleProposalRun = useCallback(
    async (run: PipelineProposalRunResponse) => {
      return run;
    },
    [],
  );

  const loadProposalRun = useCallback(
    async (signal?: AbortSignal) => {
      if (generatedSourceRevisionId === null) {
        setProposalRun(null);
        setProposalRevisionId(null);
        return;
      }
      setProposalLoading(true);
      setProposalError(null);
      try {
        const response = await client.listProposedCardSceneRuns(recordingId, {
          signal,
        });
        const matching = (Array.isArray(response.runs) ? response.runs : [])
          .filter(
            (run) =>
              readProposalInputRevisionId(run) === generatedSourceRevisionId,
          )
          .at(-1);
        if (matching === undefined) {
          if (!signal?.aborted) {
            setProposalRun(null);
            setProposalRevisionId(null);
          }
          return;
        }
        const settled = await settleProposalRun(matching);
        if (!signal?.aborted) {
          setProposalRun(settled);
          setProposalRevisionId(readProposalRevisionId(settled));
        }
      } catch (reason: unknown) {
        // Proposal history is optional for older recordings. Keep a failed
        // history lookup from masking the selected detector result.
        void reason;
      } finally {
        if (!signal?.aborted) setProposalLoading(false);
      }
    },
    [client, generatedSourceRevisionId, recordingId, settleProposalRun],
  );

  const startProposal = useCallback(async () => {
    if (generatedSourceRevisionId === null) return;
    setProposalLoading(true);
    setProposalError(null);
    try {
      const started = await client.startProposedCardSceneRun(recordingId, {
        run_id: `card-scene-proposal-${Date.now()}`,
        visible_card_revision_id: generatedSourceRevisionId,
      });
      const settled = await settleProposalRun(started);
      setProposalRun(settled);
      setProposalRevisionId(readProposalRevisionId(settled));
      setNotice(
        settled.status === "complete"
          ? "Proposed card scenes are ready to inspect."
          : `Proposal run ${settled.status}.`,
      );
    } catch (reason: unknown) {
      setProposalError(describeError(reason));
    } finally {
      setProposalLoading(false);
    }
  }, [client, generatedSourceRevisionId, recordingId, settleProposalRun]);

  const retryProposal = useCallback(async () => {
    if (
      proposalRun === null ||
      (proposalRun.status !== "failed" && proposalRun.status !== "partial")
    )
      return;
    setProposalLoading(true);
    setProposalError(null);
    try {
      const retried = await client.retryProposedCardSceneRun(
        recordingId,
        proposalRun.run_id,
      );
      const settled = await settleProposalRun(retried);
      setProposalRun(settled);
      setProposalRevisionId(readProposalRevisionId(settled));
      setNotice("Proposal run retried.");
    } catch (reason: unknown) {
      setProposalError(describeError(reason));
    } finally {
      setProposalLoading(false);
    }
  }, [client, proposalRun, recordingId, settleProposalRun]);

  const loadCalibrationRefinement = useCallback(async () => {
    if (proposalRevisionId === null) {
      setCalibrationRefinement(null);
      return;
    }
    try {
      const current = await client.getCalibrationRefinement(
        recordingId,
        proposalRevisionId,
      );
      setCalibrationRefinement(current);
      setCalibrationError(null);
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 404) {
        setCalibrationRefinement(null);
        setCalibrationError(null);
      } else {
        setCalibrationError(describeError(reason));
      }
    }
  }, [client, proposalRevisionId, recordingId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCalibrationRefinement(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCalibrationRefinement]);

  const startCalibrationRefinement = useCallback(async () => {
    if (proposalRevisionId === null) return;
    setCalibrationLoading(true);
    setCalibrationError(null);
    try {
      const started = await client.startCalibrationRefinement(recordingId, {
        proposal_revision_id: proposalRevisionId,
      });
      setCalibrationRefinement(started);
    } catch (reason: unknown) {
      setCalibrationError(describeError(reason));
    } finally {
      setCalibrationLoading(false);
    }
  }, [client, proposalRevisionId, recordingId]);

  const updateCalibrationAnchor = useCallback(
    async (command: CalibrationAnchorCommand) => {
      const current = calibrationRefinement;
      const draftId = current?.draft.draft_id;
      const revision = current?.draft.revision;
      if (
        current === null ||
        typeof draftId !== "string" ||
        typeof revision !== "number"
      ) {
        setCalibrationError(
          "Start a mapping preview before changing calibration anchors.",
        );
        return;
      }
      setCalibrationLoading(true);
      setCalibrationError(null);
      try {
        const digested = await withCalibrationAnchorCommandDigest({
          ...command,
          expected_draft_revision: revision,
        });
        const updated = await client.updateCalibrationRefinement(
          recordingId,
          current.proposal_revision_id,
          {
            draft_id: draftId,
            expected_revision: revision,
            command: digested,
          },
        );
        setCalibrationRefinement(updated);
      } catch (reason: unknown) {
        setCalibrationError(describeError(reason));
      } finally {
        setCalibrationLoading(false);
      }
    },
    [calibrationRefinement, client, recordingId],
  );

  const discardCalibrationRefinement = useCallback(async () => {
    const current = calibrationRefinement;
    if (current === null) return;
    const draftId = current.draft.draft_id;
    if (typeof draftId !== "string") return;
    setCalibrationLoading(true);
    setCalibrationError(null);
    try {
      const reset = await client.discardCalibrationRefinement(recordingId, {
        proposal_revision_id: current.proposal_revision_id,
        draft_id: draftId,
      });
      setCalibrationRefinement(reset);
    } catch (reason: unknown) {
      setCalibrationError(describeError(reason));
    } finally {
      setCalibrationLoading(false);
    }
  }, [calibrationRefinement, client, recordingId]);

  const applyCalibrationRefinement = useCallback(
    async (confirmAffected: boolean) => {
      const current = calibrationRefinement;
      if (current === null) return;
      const draftId = current.draft.draft_id;
      const revision = current.draft.revision;
      const previewDigest = current.preview.preview_digest;
      if (
        typeof draftId !== "string" ||
        typeof revision !== "number" ||
        typeof previewDigest !== "string"
      ) {
        setCalibrationError(
          "The calibration preview is incomplete. Reload it and try again.",
        );
        return;
      }
      setCalibrationLoading(true);
      setCalibrationError(null);
      try {
        const applied = await client.applyCalibrationRefinement(
          recordingId,
          current.proposal_revision_id,
          {
            draft_id: draftId,
            expected_revision: revision,
            preview_digest: previewDigest,
            operator_id: operatorId.trim() || "operator",
            confirm_affected: confirmAffected,
          },
        );
        setProposalRevisionId(applied.proposal_revision_id);
        hydrateReference(applied.reference);
        setCalibrationRefinement(null);
        setNotice(
          `Applied calibration ${applied.calibration_revision_id}; review affected frames before completion.`,
        );
      } catch (reason: unknown) {
        setCalibrationError(describeError(reason));
      } finally {
        setCalibrationLoading(false);
      }
    },
    [calibrationRefinement, client, hydrateReference, operatorId, recordingId],
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
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => void loadProposalRun(controller.signal),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadProposalRun]);

  useEffect(() => {
    if (proposalRun?.status !== "queued" && proposalRun?.status !== "running")
      return;
    const timer = window.setTimeout(() => {
      void client.getProposedCardSceneRun(recordingId, proposalRun.run_id).then(
        (run) => {
          setProposalRun(run);
          setProposalRevisionId(readProposalRevisionId(run));
        },
        (reason: unknown) => setProposalError(describeError(reason)),
      );
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [client, proposalRun, recordingId]);

  useEffect(() => {
    const candidates = usesMaintainedFrames ? frames : generatedFrames;
    const urlState = readPipelineEditorUrlState();
    const requestedItemId =
      selectionItemId === undefined ? urlState.item : selectionItemId;
    const selected =
      (requestedItemId === null
        ? undefined
        : candidates.find((frame) => frame.itemId === requestedItemId)) ??
      candidates[0];
    const requestedTimeUs =
      selectionTimeUs === undefined ? urlState.tUs : selectionTimeUs;
    const timer = window.setTimeout(() => {
      if (selected !== undefined) selectFrame(selected, false);
      if (requestedTimeUs !== null) {
        setCurrentTime(requestedTimeUs, false);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [
    frames,
    generatedFrames,
    selectionItemId,
    selectionTimeUs,
    setCurrentTime,
    selectFrame,
    usesMaintainedFrames,
  ]);

  useEffect(() => {
    const candidates = usesMaintainedFrames ? frames : generatedFrames;
    onRailItemsChange?.(
      candidates.map((frame, index) => ({
        itemId: frame.itemId,
        label: `Frame ${index + 1} · ${formatFrameTime(frame)}`,
        state:
          view === "reviewed" ? frameReviewStatus(frame) : frame.outcome.status,
        timeUs: frame.outcome.frame_identity?.requested_time_us ?? null,
        proposalCount: frame.outcome.candidates.length,
        ignoredRegionCount: frame.outcome.ignored_regions.length,
        decision: view === "reviewed" ? frameDecision(frame) : null,
      })),
    );
  }, [frames, generatedFrames, onRailItemsChange, usesMaintainedFrames, view]);

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
          operations: command.operations,
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

  const enqueueOperations = useCallback(
    (
      operations: PipelineReferenceOperation[],
      noticeText: string,
      optimistic: (current: EditableFrame[]) => EditableFrame[],
    ) => {
      if (referenceRef.current === null) return;
      setLocalFrames(optimistic(framesRef.current));
      queueRef.current.push({
        commandId: nextCommandId(),
        operations,
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

  const enqueue = useCallback(
    (
      operation: PipelineReferenceOperation,
      noticeText: string,
      optimistic: (current: EditableFrame[]) => EditableFrame[],
    ) => {
      enqueueOperations([operation], noticeText, optimistic);
    },
    [enqueueOperations],
  );

  const startReference = useCallback(() => {
    const current = referenceRef.current;
    if (
      current === null ||
      current.draft.source_revision_id !== null ||
      current.draft.items.length > 0 ||
      generatedSourceRevisionId === null ||
      operatorId.trim() === ""
    ) {
      return;
    }
    setReviewerId((currentReviewer) => currentReviewer || operatorId.trim());
    enqueue(
      {
        operation: "rebase",
        source_revision_id: generatedSourceRevisionId,
        ...(proposalRevisionId === null
          ? {}
          : { proposal_revision_id: proposalRevisionId }),
      },
      "Maintained visible-card reference seeded from the selected generated result.",
      (currentFrames) => currentFrames,
    );
  }, [enqueue, generatedSourceRevisionId, operatorId, proposalRevisionId]);

  const rebaseReference = useCallback(async () => {
    const current = referenceRef.current;
    const sourceRevisionId = generatedRevisionId;
    if (
      current === null ||
      sourceRevisionId === null ||
      current.draft.source_revision_id === sourceRevisionId ||
      operatorId.trim() === "" ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      saveState !== "saved"
    ) {
      return;
    }
    setRebasingReference(true);
    setSaveState("saving");
    setError(null);
    setNotice(null);
    try {
      const rebased = await client.updatePipelineReferenceDraft(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: operatorId.trim(),
          command_id: nextCommandId(),
          operations: [
            { operation: "rebase", source_revision_id: sourceRevisionId },
          ],
        },
      );
      hydrateReference(rebased, false);
      setSaveState("saved");
      setNotice(
        "Review switched to the selected generated result. Inspect the visible cards before completing the review.",
      );
    } catch (reason: unknown) {
      setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      setError(describeError(reason));
    } finally {
      setRebasingReference(false);
    }
  }, [
    client,
    generatedRevisionId,
    hydrateReference,
    nextCommandId,
    operatorId,
    recordingId,
    saveState,
  ]);

  const rebaseReferenceToProposal = useCallback(async () => {
    const current = referenceRef.current;
    const sourceRevisionId = generatedSourceRevisionId;
    const targetProposalRevisionId = proposalRevisionId;
    if (
      current === null ||
      sourceRevisionId === null ||
      targetProposalRevisionId === null ||
      current.draft.proposal_revision_id === targetProposalRevisionId ||
      operatorId.trim() === "" ||
      queueRef.current.length > 0 ||
      processingRef.current ||
      saveState !== "saved"
    ) {
      return;
    }
    setRebasingProposal(true);
    setSaveState("saving");
    setError(null);
    setNotice(null);
    try {
      const rebased = await client.updatePipelineReferenceDraft(
        recordingId,
        CONTENT_TYPE,
        {
          expected_revision: serverRevisionRef.current,
          operator_id: operatorId.trim(),
          command_id: nextCommandId(),
          operations: [
            {
              operation: "rebase",
              source_revision_id: sourceRevisionId,
              proposal_revision_id: targetProposalRevisionId,
            },
          ],
        },
      );
      hydrateReference(rebased, false);
      setSaveState("saved");
      setNotice(
        "Proposed card scenes loaded. Inspect the poses and homography before completing the review.",
      );
    } catch (reason: unknown) {
      setSaveState(
        reason instanceof ApiError && reason.status === 409
          ? "conflict"
          : "error",
      );
      setError(describeError(reason));
    } finally {
      setRebasingProposal(false);
    }
  }, [
    client,
    generatedSourceRevisionId,
    hydrateReference,
    nextCommandId,
    operatorId,
    proposalRevisionId,
    recordingId,
    saveState,
  ]);

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

  const updatePoseScene = useCallback(
    (
      frame: EditableFrame,
      cardScene: NonNullable<Outcome["card_scene"]>,
      noticeText: string,
    ) => {
      setFrameReview(
        frame,
        {
          ...frame.outcome,
          status: "detected",
          card_scene: cardScene,
          error: null,
        },
        noticeText,
      );
    },
    [setFrameReview],
  );

  const decideCard = useCallback(
    (frame: EditableFrame, cardId: string, decision: "accept" | "reject") => {
      const cardScene = frame.outcome.card_scene;
      if (cardScene === undefined || cardScene.card_review_states === undefined)
        return;
      const nextState: "accepted" | "rejected" =
        decision === "accept" ? "accepted" : "rejected";
      const nextStates = cardScene.card_review_states.map((state) =>
        state.card_id === cardId ? { ...state, state: nextState } : state,
      );
      const nextScene = {
        ...cardScene,
        card_review_states: nextStates,
        completion_state: nextStates.some((state) => state.state === "pending")
          ? ("pending" as const)
          : ("complete" as const),
        completion_reason: null,
      };
      enqueue(
        {
          operation: decision === "accept" ? "accept_card" : "reject_card",
          item_id: frame.itemId,
          card_id: cardId,
        },
        decision === "accept" ? "Card accepted." : "Card rejected.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? {
                  ...candidate,
                  outcome: { ...candidate.outcome, card_scene: nextScene },
                }
              : candidate,
          ),
      );
    },
    [enqueue],
  );

  const resolveRemainingCards = useCallback(
    (frame: EditableFrame) => {
      const cardScene = frame.outcome.card_scene;
      if (cardScene === undefined || cardScene.card_review_states === undefined)
        return;
      const pending = cardScene.card_review_states.filter(
        (state) => state.state === "pending",
      );
      if (pending.length === 0) return;
      const operations: PipelineReferenceOperation[] = pending.map((state) => ({
        operation: "accept_card",
        item_id: frame.itemId,
        card_id: state.card_id,
      }));
      const nextScene = {
        ...cardScene,
        card_review_states: cardScene.card_review_states.map((state) =>
          state.state === "pending"
            ? { ...state, state: "accepted" as const }
            : state,
        ),
        completion_state: "complete" as const,
        completion_reason: null,
      };
      enqueueOperations(
        operations,
        "All remaining cards accepted.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? {
                  ...candidate,
                  outcome: { ...candidate.outcome, card_scene: nextScene },
                }
              : candidate,
          ),
      );
    },
    [enqueueOperations],
  );

  const acceptSuggestions = useCallback(
    (frame: EditableFrame) => {
      endEditMode();
      enqueue(
        { operation: "accept_frame_suggestions", item_id: frame.itemId },
        "Frame accepted.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? { ...candidate, reviewState: "accepted" }
              : candidate,
          ),
      );
    },
    [endEditMode, enqueue],
  );

  const toggleFrameAcceptance = useCallback(
    (frame: EditableFrame) => {
      if (frameReviewStatus(frame) !== "accepted") {
        acceptSuggestions(frame);
        return;
      }
      endEditMode();
      enqueue(
        { operation: "set_frame_unreviewed", item_id: frame.itemId },
        "Frame returned to unreviewed.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? { ...candidate, reviewState: "pending" }
              : candidate,
          ),
      );
    },
    [acceptSuggestions, endEditMode, enqueue],
  );

  const restoreGeneratedSuggestions = useCallback(
    (frame: EditableFrame) => {
      const generated = generatedFrames.find(
        (candidate) => candidate.itemId === frame.itemId,
      );
      if (generated === undefined) return;
      const outcome = generated.outcome;
      endEditMode();
      enqueue(
        {
          operation: "restore_frame_suggestions",
          item_id: frame.itemId,
          item: outcome,
        },
        "Generated suggestions restored. Accept the frame when it is ready.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId === frame.itemId
              ? {
                  ...candidate,
                  baseItemId: null,
                  outcome,
                  reviewState: "pending",
                }
              : candidate,
          ),
      );
    },
    [endEditMode, enqueue, generatedFrames],
  );

  const setFrameOutcome = useCallback(
    (frame: EditableFrame, outcome: "empty" | "unusable") => {
      endEditMode();
      const nextOutcome: Outcome = {
        ...frame.outcome,
        status: outcome === "empty" ? "empty" : "failed",
        candidates: [],
        ignored_regions: [],
        card_scene: undefined,
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
    [endEditMode, enqueue],
  );

  const openEditor = useCallback(
    (frame: EditableFrame, candidate: Candidate | null, polygonIndex = 0) => {
      if (frame.outcome.frame_identity === null) return;
      setEditorError(null);
      const polygons =
        candidate === null ? [[]] : geometryPolygons(candidate.geometry);
      setEditor({
        frameItemId: frame.itemId,
        cardId: candidate?.card_id ?? null,
        regionId: null,
        ignoreRegion: null,
        polygons,
        polygonIndex: Math.min(Math.max(0, polygonIndex), polygons.length - 1),
        selectedPointIndex: null,
      });
    },
    [],
  );

  const openIgnoreRegionEditor = useCallback(
    (frame: EditableFrame, region: IgnoreRegion | null = null) => {
      if (frame.outcome.frame_identity === null) return;
      const nextRegion =
        region ?? newIgnoreRegion(frame, nextManualRegionId(frame));
      setEditorError(null);
      setSelectedCandidateIds([]);
      setEditor({
        frameItemId: frame.itemId,
        cardId: null,
        regionId: nextRegion.region_id,
        ignoreRegion: region,
        polygons:
          region === null
            ? [[]]
            : region.geometry.polygons.map((polygon) => [...polygon]),
        polygonIndex: 0,
        selectedPointIndex: null,
      });
    },
    [],
  );

  const saveEditor = useCallback(
    (closeEditor = true) => {
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
      if (currentEditor.regionId !== null) {
        const existingRegion = frame.outcome.ignored_regions.find(
          (region) => region.region_id === currentEditor.regionId,
        );
        const hasExistingRegion =
          existingRegion !== undefined || currentEditor.ignoreRegion !== null;
        const region = currentEditor.ignoreRegion ?? existingRegion;
        const nextRegion = {
          ...(region ?? newIgnoreRegion(frame, currentEditor.regionId)),
          geometry: {
            kind: "reviewed-ignore-region/v1" as const,
            polygons: currentEditor.polygons.map((polygon) =>
              polygon.map((point) => ({
                x: Math.round(point.x),
                y: Math.round(point.y),
              })),
            ),
          },
        };
        const operation: PipelineReferenceOperation = {
          operation: !hasExistingRegion
            ? "create_ignore_region"
            : "replace_ignore_region",
          item_id: frame.itemId,
          region_id: !hasExistingRegion ? undefined : currentEditor.regionId,
          region: ignoreRegionMapping(nextRegion),
        };
        enqueue(
          operation,
          !hasExistingRegion
            ? "Ignore region created."
            : "Ignore-region geometry saved.",
          (current) =>
            current.map((candidate) => {
              if (candidate.itemId !== frame.itemId) return candidate;
              const containsRegion = candidate.outcome.ignored_regions.some(
                (currentRegion) =>
                  currentRegion.region_id === nextRegion.region_id,
              );
              const ignoredRegions = containsRegion
                ? candidate.outcome.ignored_regions.map((currentRegion) =>
                    currentRegion.region_id === nextRegion.region_id
                      ? nextRegion
                      : currentRegion,
                  )
                : [...candidate.outcome.ignored_regions, nextRegion];
              return {
                ...candidate,
                outcome: {
                  ...candidate.outcome,
                  status: "detected",
                  ignored_regions: ignoredRegions,
                  candidates: candidate.outcome.candidates.filter(
                    (currentCandidate) =>
                      !candidateIsWithinIgnoreRegions(
                        currentCandidate,
                        ignoredRegions,
                      ),
                  ),
                  error: null,
                },
              };
            }),
        );
        setEditor((current) =>
          current?.regionId === nextRegion.region_id
            ? { ...current, ignoreRegion: nextRegion }
            : current,
        );
        if (closeEditor) setEditor(null);
        setEditorError(null);
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
          side: "unknown",
        });
      }
      setFrameReview(
        frame,
        {
          ...frame.outcome,
          status: "detected",
          candidates,
          ignored_regions: frame.outcome.ignored_regions,
          error: null,
        },
        currentEditor.cardId === null
          ? "Missed visible card added."
          : "Visible-card geometry saved.",
      );
      if (closeEditor) setEditor(null);
      setEditorError(null);
    },
    [enqueue, setFrameReview],
  );

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
          status:
            candidates.length === 0 &&
            frame.outcome.ignored_regions.length === 0
              ? "empty"
              : "detected",
          candidates,
          ignored_regions: frame.outcome.ignored_regions,
          error: null,
        },
        "Visible card removed from the frame review.",
      );
    },
    [setFrameReview],
  );

  const toggleCandidateSelection = useCallback((cardId: string) => {
    setSelectedCandidateIds((current) =>
      current.includes(cardId)
        ? current.filter((candidateId) => candidateId !== cardId)
        : [...current, cardId],
    );
  }, []);

  const convertSelectedToIgnoreRegion = useCallback(
    (frame: EditableFrame) => {
      const detected =
        generatedFrames.find(
          (generated) =>
            generated.itemId === frame.itemId ||
            generated.itemId === frame.baseItemId,
        )?.outcome.candidates ?? [];
      const selectedFromFrame = frame.outcome.candidates.filter((candidate) =>
        selectedCandidateIds.includes(candidate.card_id),
      );
      const selectedFromDetected = detected.filter(
        (candidate) =>
          selectedCandidateIds.includes(candidate.card_id) &&
          !selectedFromFrame.some(
            (frameCandidate) => frameCandidate.card_id === candidate.card_id,
          ),
      );
      const selected = [...selectedFromFrame, ...selectedFromDetected];
      if (selected.length === 0) {
        setNotice(
          "Select proposals with the left-side checkboxes before converting to an ignore region.",
        );
        return;
      }
      const polygons = selected.flatMap((candidate) =>
        geometryPolygons(candidate.geometry),
      );
      if (
        polygons.length === 0 ||
        polygons.some((polygon) => polygon.length < 3)
      ) {
        setError(
          "Selected proposals do not have usable polygon geometry for an ignore region.",
        );
        return;
      }
      const region = newIgnoreRegion(frame, nextManualRegionId(frame));
      const ignoredRegion = {
        ...region,
        geometry: {
          kind: "reviewed-ignore-region/v1" as const,
          polygons,
        },
        source_candidates: selected.map((candidate) => ({
          revision_id: generatedSourceRevisionId ?? "",
          card_id: candidate.card_id,
        })),
      };
      // Convert only when every selected card is already on the maintained frame.
      // Otherwise create from detector fallback geometry — those IDs are not on the draft.
      const operation: PipelineReferenceOperation =
        selectedFromDetected.length === 0
          ? {
              operation: "convert_to_ignore_region",
              item_id: frame.itemId,
              region: ignoreRegionMapping(ignoredRegion),
              candidate_ids: selected.map((candidate) => candidate.card_id),
            }
          : {
              operation: "create_ignore_region",
              item_id: frame.itemId,
              region: ignoreRegionMapping(ignoredRegion),
            };
      endEditMode();
      enqueue(
        operation,
        `Converted ${selected.length} proposal${selected.length === 1 ? "" : "s"} to one untidy-stack ignore region.`,
        (current) =>
          current.map((candidate) => {
            if (candidate.itemId !== frame.itemId) return candidate;
            const remainingCandidates = candidate.outcome.candidates.filter(
              (currentCandidate) =>
                !selectedCandidateIds.includes(currentCandidate.card_id) &&
                !candidateIsWithinIgnoreRegions(currentCandidate, [
                  ...candidate.outcome.ignored_regions,
                  ignoredRegion,
                ]),
            );
            return {
              ...candidate,
              reviewState:
                remainingCandidates.length === 0 &&
                selectedFromDetected.length === 0
                  ? "accepted"
                  : candidate.reviewState,
              outcome: {
                ...candidate.outcome,
                status: "detected",
                candidates: remainingCandidates,
                ignored_regions: [
                  ...candidate.outcome.ignored_regions,
                  ignoredRegion,
                ],
                error: null,
              },
            };
          }),
      );
    },
    [endEditMode, enqueue, generatedFrames, generatedSourceRevisionId, selectedCandidateIds],
  );

  const removeIgnoreRegion = useCallback(
    (frame: EditableFrame, regionId: string) => {
      endEditMode();
      enqueue(
        {
          operation: "delete_ignore_region",
          item_id: frame.itemId,
          region_id: regionId,
        },
        "Ignore region deleted.",
        (current) =>
          current.map((candidate) =>
            candidate.itemId !== frame.itemId
              ? candidate
              : {
                  ...candidate,
                  outcome: {
                    ...candidate.outcome,
                    ignored_regions: candidate.outcome.ignored_regions.filter(
                      (region) => region.region_id !== regionId,
                    ),
                  },
                },
          ),
      );
    },
    [endEditMode, enqueue],
  );

  const copyIgnoreRegions = useCallback(
    (frame: EditableFrame, source: EditableFrame) => {
      if (source.outcome.ignored_regions.length === 0) return;
      const copiedRegions = source.outcome.ignored_regions.map(
        (region, index): IgnoreRegion => ({
          ...region,
          region_id: copiedIgnoreRegionId(frame, index),
          geometry: {
            kind: "reviewed-ignore-region/v1",
            polygons: region.geometry.polygons.map((polygon) =>
              polygon.map((point) => ({ ...point })),
            ),
          },
          normalization: {
            ...region.normalization,
            width:
              frame.outcome.frame_identity?.width ?? region.normalization.width,
            height:
              frame.outcome.frame_identity?.height ??
              region.normalization.height,
          },
          source_candidates: [],
        }),
      );
      const operations: PipelineReferenceOperation[] = [
        ...frame.outcome.ignored_regions.map((region) => ({
          operation: "delete_ignore_region" as const,
          item_id: frame.itemId,
          region_id: region.region_id,
        })),
        ...copiedRegions.map((region) => ({
          operation: "create_ignore_region" as const,
          item_id: frame.itemId,
          region: ignoreRegionMapping(region),
        })),
      ];
      endEditMode();
      enqueueOperations(
        operations,
        `Copied ${copiedRegions.length} ignore region${copiedRegions.length === 1 ? "" : "s"} from the previous reviewed frame.`,
        (current) =>
          current.map((candidate) =>
            candidate.itemId !== frame.itemId
              ? candidate
              : {
                  ...candidate,
                  outcome: {
                    ...candidate.outcome,
                    status: "detected",
                    ignored_regions: copiedRegions,
                    candidates: candidate.outcome.candidates.filter(
                      (currentCandidate) =>
                        !candidateIsWithinIgnoreRegions(
                          currentCandidate,
                          copiedRegions,
                        ),
                    ),
                    error: null,
                  },
                },
          ),
      );
    },
    [endEditMode, enqueueOperations],
  );

  const handleCanvasPointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>, providedPoint?: Point | null) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      if (!drag.dragging) {
        const horizontal = event.clientX - drag.startClientX;
        const vertical = event.clientY - drag.startClientY;
        if (
          horizontal * horizontal + vertical * vertical <=
          POINT_DRAG_THRESHOLD_PX ** 2
        ) {
          return;
        }
        drag.dragging = true;
      }
      const point = pointFromEvent(event, providedPoint);
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

  const handleCanvasPointerLeave = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>, providedPoint?: Point | null) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      if (!drag.dragging) {
        dragRef.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        return;
      }
      const point = pointFromEvent(event, providedPoint);
      if (point === null) return;
      const currentEditor = editorRef.current;
      const polygon = currentEditor?.polygons[drag.polygonIndex];
      if (polygon?.[drag.pointIndex] === undefined) return;
      drag.dirty = true;
      setEditor((current) => {
        if (current === null) return current;
        const polygons = current.polygons.map((polygon) => [...polygon]);
        const polygon = polygons[drag.polygonIndex];
        if (polygon?.[drag.pointIndex] === undefined) return current;
        polygon[drag.pointIndex] = point;
        return { ...current, polygons };
      });
      dragRef.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      window.setTimeout(() => void saveEditorRef.current?.(false), 0);
    },
    [],
  );

  const addVisibleRegionPoint = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>, providedPoint?: Point | null) => {
      const point = pointFromEvent(event, providedPoint);
      if (point === null) return;
      const currentEditor = editorRef.current;
      if (currentEditor === null) return;
      const currentFrame = framesRef.current.find(
        (frame) => frame.itemId === currentEditor.frameItemId,
      );
      if (currentEditor.regionId === null && currentFrame !== undefined) {
        const nextCandidate = findClearlySelectedCandidate(
          currentFrame.outcome.candidates,
          currentEditor.cardId,
          currentEditor.polygons,
          point,
        );
        if (nextCandidate !== null) {
          openEditor(
            currentFrame,
            nextCandidate.candidate,
            nextCandidate.polygonIndex,
          );
          return;
        }
      }
      const nextPolygonIndex = findClearlySelectedPolygon(
        currentEditor.polygons,
        currentEditor.polygonIndex,
        point,
      );
      if (nextPolygonIndex !== null) {
        setEditor((current) =>
          current === null
            ? current
            : {
                ...current,
                polygonIndex: nextPolygonIndex,
                selectedPointIndex: null,
              },
        );
        return;
      }
      const activePolygon =
        currentEditor.polygons[currentEditor.polygonIndex] ?? [];
      if (currentEditor.cardId !== null && activePolygon.length >= 3) {
        setEditor((current) => {
          if (current === null) return current;
          const polygons = current.polygons.map((polygon) => [...polygon]);
          const polygon = polygons[current.polygonIndex] ?? [];
          if (polygon.length < 2) return current;
          polygons[current.polygonIndex] = insertPointOnNearestEdge(
            polygon,
            point,
          );
          return { ...current, polygons };
        });
        window.setTimeout(() => void saveEditorRef.current?.(false), 0);
        return;
      }
      const completed = activePolygon.length + 1 === 3;
      setEditor((current) => {
        if (current === null) return current;
        const polygons = current.polygons.map((polygon) => [...polygon]);
        const polygon = polygons[current.polygonIndex] ?? [];
        polygons[current.polygonIndex] = [...polygon, point];
        return { ...current, polygons };
      });
      if (
        completed ||
        (currentEditor.regionId !== null && activePolygon.length >= 3)
      )
        window.setTimeout(
          () =>
            void saveEditorRef.current?.(
              currentEditor.cardId === null && currentEditor.regionId === null,
            ),
          0,
        );
    },
    [openEditor],
  );

  const stopCanvasPointer = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      dragRef.current = null;
      if (drag.dirty) {
        window.setTimeout(() => void saveEditorRef.current?.(false), 0);
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
      event.currentTarget.focus();
      dragRef.current = {
        pointerId: event.pointerId,
        polygonIndex,
        pointIndex,
        startClientX: event.clientX,
        startClientY: event.clientY,
        dragging: false,
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

  const deleteSelectedPoint = useCallback(
    (event: ReactKeyboardEvent<SVGSVGElement>) => {
      if (event.key !== "Backspace" && event.key !== "Delete") return;
      const currentEditor = editorRef.current;
      if (currentEditor === null || currentEditor.selectedPointIndex === null)
        return;
      const selectedPointIndex = currentEditor.selectedPointIndex;
      const polygon = currentEditor.polygons[currentEditor.polygonIndex];
      if (polygon?.[selectedPointIndex] === undefined) return;
      event.preventDefault();
      const polygons = currentEditor.polygons.map((currentPolygon) => [
        ...currentPolygon,
      ]);
      polygons[currentEditor.polygonIndex].splice(selectedPointIndex, 1);
      const remainingPointCount = polygons[currentEditor.polygonIndex].length;
      const nextEditor = {
        ...currentEditor,
        polygons,
        selectedPointIndex:
          remainingPointCount === 0
            ? null
            : Math.min(selectedPointIndex, remainingPointCount - 1),
      };
      const validation = validatePolygons(nextEditor.polygons);
      setEditor(nextEditor);
      setEditorError(validation);
      if (validation === null)
        window.setTimeout(() => void saveEditorRef.current?.(false), 0);
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
              decision: frameDecision(frame) as
                | "cards"
                | "ignored"
                | "cards_and_ignored"
                | "empty"
                | "unusable",
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
          seed:
            proposalRevisionId !== null
              ? "proposal"
              : generatedSourceRevisionId === null
                ? "empty"
                : "selected_generated",
          ...(proposalRevisionId !== null
            ? { proposal_revision_id: proposalRevisionId }
            : generatedSourceRevisionId === null
              ? {}
              : { source_revision_id: generatedSourceRevisionId }),
        },
      );
      hydrateReference(created, false);
      setReviewerId((current) => current || operatorId.trim());
      setNotice(
        proposalRevisionId !== null
          ? "Maintained visible-card review started from the preserved proposal."
          : "Maintained visible-card reference created from the selected generated result.",
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
    generatedSourceRevisionId,
    hydrateReference,
    loadReference,
    operatorId,
    proposalRevisionId,
    recordingId,
  ]);

  const startReviewFromProposal = useCallback(async () => {
    if (proposalRevisionId === null) return;
    if (referenceRef.current === null) {
      await createReference();
    }
    onReviewRequested?.();
  }, [createReference, onReviewRequested, proposalRevisionId]);

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

  const selectEditorPolygon = useCallback((polygonIndex: number) => {
    setEditor((current) =>
      current === null || current.polygons[polygonIndex] === undefined
        ? current
        : { ...current, polygonIndex, selectedPointIndex: null },
    );
  }, []);

  const addEditorPolygon = useCallback(() => {
    setEditor((current) => {
      if (current === null) return current;
      return {
        ...current,
        polygons: [...current.polygons, []],
        polygonIndex: current.polygons.length,
        selectedPointIndex: null,
      };
    });
    setEditorError(null);
  }, []);

  const removeEditorPolygon = useCallback(() => {
    setEditor((current) => {
      if (current === null || current.polygons.length <= 1) return current;
      const polygons = current.polygons.filter(
        (_, index) => index !== current.polygonIndex,
      );
      const polygonIndex = Math.min(current.polygonIndex, polygons.length - 1);
      const nextEditor = {
        ...current,
        polygons,
        polygonIndex,
        selectedPointIndex: null,
      };
      window.setTimeout(() => void saveEditorRef.current?.(false), 0);
      return nextEditor;
    });
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (ignoresReviewNavigationShortcut(target)) return;
      if (event.key === "Escape" && editorRef.current !== null) {
        event.preventDefault();
        endEditMode();
        return;
      }
      const current = usesMaintainedFrames
        ? framesRef.current
        : generatedFrames;
      const canEdit =
        view === "reviewed" &&
        referenceRef.current !== null &&
        !referenceNeedsSeed;
      const index = current.findIndex(
        (frame) => frame.itemId === selectedFrameIdRef.current,
      );
      if (
        event.metaKey &&
        view === "reviewed" &&
        (event.key === "ArrowLeft" || event.key === "ArrowRight")
      ) {
        event.preventDefault();
        const unfinished = findAdjacentUnfinishedItem(
          current,
          selectedFrameIdRef.current,
          event.key === "ArrowLeft" ? -1 : 1,
          (frame) =>
            frame.reviewState === "pending" || frame.reviewState === "affected",
        );
        if (unfinished !== undefined) selectFrame(unfinished);
      } else if (
        !event.altKey &&
        !event.metaKey &&
        event.key === "ArrowLeft" &&
        index > 0
      ) {
        event.preventDefault();
        selectFrame(current[index - 1]);
      } else if (
        !event.altKey &&
        !event.metaKey &&
        event.key === "ArrowRight" &&
        index >= 0 &&
        index < current.length - 1
      ) {
        event.preventDefault();
        selectFrame(current[index + 1]);
      } else if (canEdit && (event.key === "n" || event.key === "N")) {
        const frame = current[index >= 0 ? index : 0];
        if (frame !== undefined && frame.outcome.card_scene === undefined) {
          event.preventDefault();
          openEditor(frame, null);
        }
      } else if (
        canEdit &&
        (event.key === "i" || event.key === "I") &&
        selectedCandidateIds.length > 0
      ) {
        const frame = current[index];
        if (frame !== undefined) {
          event.preventDefault();
          convertSelectedToIgnoreRegion(frame);
        }
      } else if (canEdit && (event.key === "a" || event.key === "A")) {
        const frame = current[index];
        if (frame?.outcome.status === "detected") {
          event.preventDefault();
          toggleFrameAcceptance(frame);
        }
      } else if (canEdit && (event.key === "e" || event.key === "E")) {
        const frame = current[index];
        if (frame !== undefined) {
          event.preventDefault();
          setFrameOutcome(frame, "empty");
        }
      } else if (canEdit && (event.key === "u" || event.key === "U")) {
        const frame = current[index];
        if (frame !== undefined) {
          event.preventDefault();
          setFrameOutcome(frame, "unusable");
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    generatedFrames,
    convertSelectedToIgnoreRegion,
    endEditMode,
    openEditor,
    referenceNeedsSeed,
    selectFrame,
    setFrameOutcome,
    usesMaintainedFrames,
    view,
    toggleFrameAcceptance,
    selectedCandidateIds.length,
  ]);

  const displayedFrames = usesMaintainedFrames ? frames : generatedFrames;
  const activeFrame =
    displayedFrames.find((frame) => frame.itemId === selectedFrameId) ??
    displayedFrames[0] ??
    null;
  const detectedFrame =
    activeFrame === null
      ? null
      : (generatedFrames.find(
          (frame) =>
            frame.itemId === activeFrame.itemId ||
            frame.itemId === activeFrame.baseItemId,
        ) ?? null);
  const detectedCandidates = detectedFrame?.outcome.candidates ?? [];
  const fitDiagnostics = readCalibrationFitDiagnostics(proposalRun);
  const fitDiagnosticOutlines =
    view === "generated" && activeFrame !== null
      ? calibrationFitOutlinesForFrame(
          fitDiagnostics,
          activeFrame.outcome.event_id,
          new Set(visibleCalibrationStatuses),
        )
      : [];
  const requestedFrameId =
    selectionItemId === undefined
      ? readPipelineEditorUrlState().item
      : selectionItemId;
  const prewarmFrameIndex = displayedFrames.findIndex(
    (frame) => frame.itemId === (selectedFrameId ?? requestedFrameId),
  );
  const activeFrameIndex =
    prewarmFrameIndex >= 0
      ? prewarmFrameIndex
      : activeFrame === null
        ? -1
        : displayedFrames.indexOf(activeFrame);
  const previousReviewedFrame =
    activeFrameIndex <= 0
      ? null
      : ([...displayedFrames]
          .slice(0, activeFrameIndex)
          .reverse()
          .find(
            (frame) =>
              frameReviewStatus(frame) === "accepted" &&
              frame.outcome.ignored_regions.length > 0,
          ) ?? null);
  const canCopyIgnoreRegions =
    activeFrame?.outcome.status === "detected" &&
    previousReviewedFrame !== null;
  const prewarmFrameUrls = useCallback(
    (frame: EditableFrame) => visibleCardReviewPrewarmUrls(recordingId, frame),
    [recordingId],
  );
  usePipelineReviewPrewarm(
    displayedFrames,
    activeFrameIndex,
    prewarmFrameUrls,
    generatedSourceRevisionId,
  );
  const reviewed = view === "reviewed";
  const editable = reviewed && reference !== null && !referenceNeedsSeed;
  const pendingCount = frames.filter(
    (frame) => frameReviewStatus(frame) === "unreviewed",
  ).length;
  const completedFrameCount = frames.filter(
    (frame) => frameDecision(frame) !== null,
  ).length;
  const coveragePercent =
    frames.length === 0 ? 0 : (inspectedFrameKeys.size / frames.length) * 100;
  const completionBlocker =
    !reviewed || reference === null || referenceNeedsSeed
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

  const handleWorkbenchSelection = useCallback(
    (selection: WorkbenchSelection | null) => {
      if (!editable || activeFrame === null || selection === null) return;
      if (selection.type === "ignore_region") {
        const region = activeFrame.outcome.ignored_regions.find(
          (candidate) => candidate.region_id === selection.id,
        );
        if (region !== undefined) openIgnoreRegionEditor(activeFrame, region);
        return;
      }
      if (
        selection.type === "virtual_card" ||
        selection.type === "calibration_anchor"
      )
        return;
      const sourceCandidates =
        activeFrame.outcome.candidates.length > 0
          ? activeFrame.outcome.candidates
          : (generatedFrames.find(
              (frame) =>
                frame.itemId === activeFrame.itemId ||
                frame.itemId === activeFrame.baseItemId,
            )?.outcome.candidates ?? []);
      const candidate = sourceCandidates.find(
        (current) => current.card_id === selection.id,
      );
      if (candidate !== undefined)
        openEditor(
          activeFrame,
          candidate,
          selection.type === "polygon" ? selection.polygonIndex : 0,
        );
    },
    [
      activeFrame,
      editable,
      generatedFrames,
      openEditor,
      openIgnoreRegionEditor,
    ],
  );

  const handleWorkbenchAction = useCallback(
    (
      action: VisibleCardReviewWorkbenchAction,
      selection: WorkbenchSelection | null,
    ) => {
      if (!editable || activeFrame === null) return;
      switch (action) {
        case "add_visible_card":
          openEditor(activeFrame, null);
          break;
        case "add_polygon":
          addEditorPolygon();
          break;
        case "remove_polygon":
          removeEditorPolygon();
          break;
        case "draw_ignore_region":
          openIgnoreRegionEditor(activeFrame);
          break;
        case "convert_to_ignore_region":
          convertSelectedToIgnoreRegion(activeFrame);
          break;
        case "copy_ignore_regions":
          if (canCopyIgnoreRegions && previousReviewedFrame !== null)
            copyIgnoreRegions(activeFrame, previousReviewedFrame);
          break;
        case "delete_selection":
          if (selection?.type === "ignore_region")
            removeIgnoreRegion(activeFrame, selection.id);
          else if (selection?.type === "visible_card")
            removeCard(activeFrame, selection.id);
          else if (selection?.type === "polygon") removeEditorPolygon();
          break;
        case "restore_suggestion":
          restoreGeneratedSuggestions(activeFrame);
          break;
      }
    },
    [
      activeFrame,
      addEditorPolygon,
      canCopyIgnoreRegions,
      convertSelectedToIgnoreRegion,
      copyIgnoreRegions,
      editable,
      openEditor,
      openIgnoreRegionEditor,
      previousReviewedFrame,
      removeCard,
      removeEditorPolygon,
      removeIgnoreRegion,
      restoreGeneratedSuggestions,
    ],
  );

  const inspector = (
    <VisibleCardInspectorPortals
      slots={inspectorSlots}
      inspectorEnabled={inspectorEnabled}
      view={view}
      reference={reference}
      frames={displayedFrames}
      selectedFrame={activeFrame}
      generatedFrames={generatedFrames}
      generatedRevisionId={generatedSourceRevisionId}
      generatedLoading={generatedLoading}
      pendingCount={pendingCount}
      completedFrameCount={completedFrameCount}
      coveragePercent={coveragePercent}
      inspectedCount={inspectedFrameKeys.size}
      saveState={saveState}
      queueLength={queueLength}
      firstUnappliedCommand={firstUnappliedCommand}
      error={error}
      operatorId={operatorId}
      reviewerId={reviewerId}
      setOperatorId={setOperatorId}
      setReviewerId={setReviewerId}
      creatingReference={creatingReference}
      selectedGeneratedRevisionId={generatedRevisionId}
      rebasingReference={rebasingReference}
      rebaseReference={rebaseReference}
      rebasingProposal={rebasingProposal}
      rebaseReferenceToProposal={rebaseReferenceToProposal}
      referenceNeedsSeed={referenceNeedsSeed}
      startReference={startReference}
      completionBusy={completionBusy}
      completionBlocker={completionBlocker}
      proposalRun={proposalRun}
      proposalRevisionId={proposalRevisionId}
      proposalLoading={proposalLoading}
      proposalError={proposalError}
      startProposal={() => void startProposal()}
      retryProposal={() => void retryProposal()}
      startReviewFromProposal={() => void startReviewFromProposal()}
      retryQueuedCommands={retryQueuedCommands}
      reloadWinningDraft={reloadWinningDraft}
      completeReference={completeReference}
      createReference={createReference}
      onReviewRequested={onReviewRequested}
      calibrationRefinement={calibrationRefinement}
      calibrationLoading={calibrationLoading}
      calibrationError={calibrationError}
      startCalibrationRefinement={() => void startCalibrationRefinement()}
      discardCalibrationRefinement={() => void discardCalibrationRefinement()}
      applyCalibrationRefinement={(confirmAffected) =>
        void applyCalibrationRefinement(confirmAffected)
      }
      onSelectCalibrationFrame={(frameId) => {
        const target = displayedFrames.find(
          (frame) => frame.itemId === frameId,
        );
        if (target !== undefined) selectFrame(target);
      }}
      onSelectFitDiagnosticFrame={(frameId) => {
        const target = generatedFrames.find(
          (frame) => frame.outcome.event_id === frameId,
        );
        if (target !== undefined) selectFrame(target);
      }}
      visibleCalibrationStatuses={new Set(visibleCalibrationStatuses)}
      onToggleCalibrationStatus={(status) =>
        setVisibleCalibrationStatuses((current) =>
          current.includes(status)
            ? current.filter((item) => item !== status)
            : [...current, status],
        )
      }
    />
  );

  const activeFrameDecision: VisibleCardFrameDecision | undefined =
    activeFrame !== null && editable
      ? {
          accepted: frameReviewStatus(activeFrame) === "accepted",
          canAccept:
            activeFrame.outcome.status === "detected" &&
            activeFrame.outcome.card_scene?.completion_state !== "pending" &&
            !activeFrame.outcome.card_scene?.card_review_states?.some(
              (state) => state.state === "pending",
            ) &&
            (editor === null || validatePolygons(editor.polygons) === null) &&
            !calibrationLoading &&
            queueLength === 0 &&
            saveState === "saved",
          acceptDisabledReason:
            activeFrame.outcome.status !== "detected"
              ? "Only detected frames can be accepted."
              : activeFrame.outcome.card_scene?.completion_state ===
                    "pending" ||
                  activeFrame.outcome.card_scene?.card_review_states?.some(
                    (state) => state.state === "pending",
                  )
                ? "Resolve every virtual-card decision first."
                : editor !== null && validatePolygons(editor.polygons) !== null
                  ? "Finish the active visible-region polygon first."
                  : calibrationLoading
                    ? "Wait for the mapping operation to finish."
                    : queueLength > 0 || saveState !== "saved"
                      ? "Wait for all frame changes to save."
                      : "Accept this frame.",
          onAccept: () => toggleFrameAcceptance(activeFrame),
          onMarkEmpty: () => setFrameOutcome(activeFrame, "empty"),
          onMarkUnusable: () => setFrameOutcome(activeFrame, "unusable"),
        }
      : undefined;

  const reviewNavigation =
    activeFrame !== null && (view === "generated" || editable) ? (
      <VisibleCardReviewNavigation
        hasPrevious={activeFrameIndex > 0}
        hasNext={
          activeFrameIndex >= 0 && activeFrameIndex < displayedFrames.length - 1
        }
        onPrevious={() => {
          const previous = displayedFrames[activeFrameIndex - 1];
          if (previous !== undefined) selectFrame(previous);
        }}
        onNext={() => {
          const next = displayedFrames[activeFrameIndex + 1];
          if (next !== undefined) selectFrame(next);
        }}
      />
    ) : null;

  if (loading) {
    return (
      <>
        {inspector}
        <p className={styles.detailEmptyState}>
          Loading maintained visible-card reference…
        </p>
      </>
    );
  }

  return (
    <>
      {inspector}
      <section
        className={visibleStyles.reviewPage}
        aria-label={`${reviewed ? "Visible-card maintained reference" : "Generated visible-card result"} workbench`}
      >
        {activeFrame === null ? (
          <p className={styles.detailEmptyState}>
            {view === "generated"
              ? generatedLoading
                ? "Loading generated visible cards…"
                : "Select a proposal from the Timeline Rail."
              : reference === null || referenceNeedsSeed
                ? "Start review to create a maintained visible-card reference."
                : "Select a resolved frame from the Timeline Rail."}
          </p>
        ) : (
          <>
            {reviewNavigation}
            <div className={visibleStyles.reviewWorkbench}>
              <VisibleCardReviewWorkbench
                recordingId={recordingId}
                frame={activeFrame}
                readOnly={!editable}
                frameDecision={activeFrameDecision}
                initialPreferences={{
                  activeTool:
                    activeFrame.outcome.card_scene === undefined
                      ? "visible_regions"
                      : "virtual_cards",
                }}
                enabledEditTools={
                  editable
                    ? ["visible_regions", "virtual_cards", "mapping"]
                    : []
                }
                editor={
                  editor?.frameItemId === activeFrame.itemId ? editor : null
                }
                editorError={editorError}
                selectedCandidateIds={selectedCandidateIds}
                detectedCandidates={detectedCandidates}
                calibrationFitOutlines={fitDiagnosticOutlines}
                proposalSlot={proposalSlot}
                canCopyIgnoreRegions={canCopyIgnoreRegions}
                canRestoreSuggestion={
                  generatedFrames.some(
                    (frame) => frame.itemId === activeFrame.itemId,
                  ) && activeFrame.reviewState !== "pending"
                }
                candidateCalibration={
                  calibrationRefinement?.preview.candidate_calibration ?? null
                }
                calibrationRefinement={calibrationRefinement}
                onAnchorCommand={(command) =>
                  void updateCalibrationAnchor(command)
                }
                onStartMappingPreview={() => void startCalibrationRefinement()}
                onDiscardMappingPreview={() =>
                  void discardCalibrationRefinement()
                }
                onApplyMapping={() =>
                  void applyCalibrationRefinement(
                    calibrationRefinement?.preview.failure?.code ===
                      "reviewed_displacement_exceeded",
                  )
                }
                mappingLoading={calibrationLoading}
                mappingCanApply={
                  calibrationRefinement !== null &&
                  (calibrationRefinement.preview.status === "pass" ||
                    calibrationRefinement.preview.failure?.code ===
                      "reviewed_displacement_exceeded")
                }
                onSelectionChange={handleWorkbenchSelection}
                onAction={handleWorkbenchAction}
                onSceneChange={
                  editable
                    ? (scene, noticeText) =>
                        updatePoseScene(activeFrame, scene, noticeText)
                    : undefined
                }
                onCardDecision={
                  editable
                    ? (cardId, decision) =>
                        decideCard(activeFrame, cardId, decision)
                    : undefined
                }
                onResolveRemaining={
                  editable
                    ? () => resolveRemainingCards(activeFrame)
                    : undefined
                }
                onOpenEditor={
                  editable
                    ? (candidate, polygonIndex) =>
                        openEditor(activeFrame, candidate, polygonIndex)
                    : undefined
                }
                onOpenIgnoreRegion={
                  editable
                    ? (region) => openIgnoreRegionEditor(activeFrame, region)
                    : undefined
                }
                onToggleCandidateSelection={toggleCandidateSelection}
                onSelectEditorPolygon={selectEditorPolygon}
                onPointerMove={handleCanvasPointerMove}
                onPointerLeave={handleCanvasPointerLeave}
                onCanvasPointerDown={addVisibleRegionPoint}
                onPointerUp={stopCanvasPointer}
                onPointPointerDown={startPointDrag}
                onDeleteSelectedPoint={deleteSelectedPoint}
              />
            </div>
          </>
        )}
        {notice !== null ? <Toast message={notice} /> : null}
        {inspectorSlots === null && error !== null ? (
          <div className={styles.cardEventError} role="alert">
            <p>{error}</p>
          </div>
        ) : null}
      </section>
    </>
  );
}

function readProposalInputRevisionId(
  run: PipelineProposalRunResponse,
): string | null {
  const direct = run.request.visible_card_revision_id;
  if (typeof direct === "string") return direct;
  const inputs = run.request.input_revision_ids;
  return Array.isArray(inputs) && typeof inputs[0] === "string"
    ? inputs[0]
    : null;
}

function readProposalRevisionId(
  run: PipelineProposalRunResponse,
): string | null {
  const outputRevisionIds = run.state.output_revision_ids;
  return Array.isArray(outputRevisionIds) &&
    typeof outputRevisionIds[0] === "string"
    ? outputRevisionIds[0]
    : null;
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
  if (!Array.isArray(result.revisions)) return [];
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
  const rawIgnoredRegions = value.ignored_regions;
  if (
    typeof eventId !== "string" ||
    !["detected", "empty", "failed"].includes(String(status)) ||
    !Array.isArray(rawCandidates) ||
    (rawIgnoredRegions !== undefined && !Array.isArray(rawIgnoredRegions))
  )
    return null;
  const frame = rawFrame === null ? null : readFrameIdentity(rawFrame);
  if (rawFrame !== null && frame === null) return null;
  const candidates = rawCandidates
    .map(readCandidate)
    .filter((candidate): candidate is Candidate => candidate !== null);
  const ignoredRegions = (rawIgnoredRegions ?? [])
    .map(readIgnoreRegion)
    .filter((region): region is IgnoreRegion => region !== null);
  const cardScene = readPoseScene(value.card_scene);
  return {
    event_id: eventId,
    frame_identity: frame,
    status: status as Outcome["status"],
    candidates,
    ignored_regions: ignoredRegions,
    ...(cardScene === null ? {} : { card_scene: cardScene }),
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
    !isVisibleCardSide(value.side) ||
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
    side: value.side,
    ...(Array.isArray(value.model_scores)
      ? { model_scores: value.model_scores.filter(isRecord) }
      : {}),
  };
}

function readIgnoreRegion(value: unknown): IgnoreRegion | null {
  if (!isRecord(value)) return null;
  const geometry = value.geometry;
  const normalization = value.normalization;
  const sourceCandidates = value.source_candidates;
  if (
    typeof value.region_id !== "string" ||
    value.reason !== "untidy_stack" ||
    !isRecord(geometry) ||
    geometry.kind !== "reviewed-ignore-region/v1" ||
    !Array.isArray(geometry.polygons) ||
    !isRecord(normalization) ||
    !isInteger(normalization.width) ||
    !isInteger(normalization.height) ||
    typeof normalization.policy_id !== "string" ||
    !Array.isArray(sourceCandidates)
  )
    return null;
  const polygons = geometry.polygons.map((polygon) => {
    if (
      !Array.isArray(polygon) ||
      polygon.some(
        (point) =>
          !isRecord(point) || !isInteger(point.x) || !isInteger(point.y),
      )
    )
      return null;
    return polygon as Point[];
  });
  if (
    polygons.some((polygon): polygon is null => polygon === null) ||
    validatePolygons(polygons as Point[][]) !== null
  )
    return null;
  const sources = sourceCandidates
    .filter(isRecord)
    .filter(
      (source): source is Record<string, unknown> =>
        typeof source.revision_id === "string" &&
        typeof source.card_id === "string",
    ) as IgnoreRegionSourceCandidate[];
  if (sources.length !== sourceCandidates.length) return null;
  return {
    region_id: value.region_id,
    geometry: {
      kind: "reviewed-ignore-region/v1",
      polygons: polygons as Point[][],
    },
    normalization: {
      width: normalization.width,
      height: normalization.height,
      policy_id: normalization.policy_id,
    },
    reason: "untidy_stack",
    source_candidates: sources,
  };
}

function isVisibleCardSide(value: unknown): value is Candidate["side"] {
  return value === "face_up" || value === "face_down" || value === "unknown";
}

function readGeometry(value: Record<string, unknown>): Geometry | null {
  const box = isRecord(value.box_2d) ? value.box_2d : null;
  const region = isRecord(value.visible_region) ? value.visible_region : null;
  const boxGeometry =
    box !== null &&
    ["x_min", "y_min", "x_max", "y_max"].every((key) => isInteger(box[key]))
      ? (box as Geometry["box_2d"])
      : undefined;
  if (region !== null && Array.isArray(region.polygons)) {
    const polygons = region.polygons
      .filter(Array.isArray)
      .map(
        (polygon) =>
          polygon
            .filter(isRecord)
            .filter(
              (point) => isInteger(point.x) && isInteger(point.y),
            ) as Point[],
      );
    if (
      polygons.length > 0 &&
      polygons.every((polygon) => polygon.length >= 3)
    ) {
      return {
        kind: String(value.kind),
        ...(boxGeometry === undefined ? {} : { box_2d: boxGeometry }),
        visible_region: { polygons },
      };
    }
  }
  if (value.kind === "detector-box/v1" && boxGeometry !== undefined)
    return {
      kind: String(value.kind),
      box_2d: boxGeometry,
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

const GEOMETRY_EPSILON = 1e-9;

function candidateIsWithinIgnoreRegions(
  candidate: Candidate,
  regions: IgnoreRegion[],
): boolean {
  const containers = regions.flatMap((region) => region.geometry.polygons);
  return (
    containers.length > 0 &&
    geometryPolygons(candidate.geometry).every((polygon) =>
      polygonIsWithin(polygon, containers),
    )
  );
}

function polygonIsWithin(candidate: Point[], containers: Point[][]): boolean {
  if (candidate.length < 3) return false;
  if (!candidate.every((point) => pointInPolygonUnion(point, containers)))
    return false;
  return candidate.every((start, index) =>
    segmentIsWithin(
      start,
      candidate[(index + 1) % candidate.length],
      containers,
    ),
  );
}

function segmentIsWithin(
  start: Point,
  end: Point,
  containers: Point[][],
): boolean {
  if (start.x === end.x && start.y === end.y) return true;
  const parameters = [0, 1];
  for (const polygon of containers) {
    for (let index = 0; index < polygon.length; index += 1) {
      parameters.push(
        ...segmentIntersectionParameters(
          start,
          end,
          polygon[index],
          polygon[(index + 1) % polygon.length],
        ),
      );
    }
  }
  const ordered = [
    ...new Set(
      parameters
        .filter(
          (parameter) =>
            parameter >= -GEOMETRY_EPSILON && parameter <= 1 + GEOMETRY_EPSILON,
        )
        .map((parameter) =>
          Math.max(0, Math.min(1, Math.round(parameter * 1e12) / 1e12)),
        ),
    ),
  ].sort((left, right) => left - right);
  return ordered.slice(0, -1).every((left, index) => {
    const right = ordered[index + 1];
    if (right - left <= GEOMETRY_EPSILON) return true;
    const parameter = (left + right) / 2;
    return pointInPolygonUnion(
      {
        x: start.x + (end.x - start.x) * parameter,
        y: start.y + (end.y - start.y) * parameter,
      },
      containers,
    );
  });
}

function segmentIntersectionParameters(
  start: Point,
  end: Point,
  otherStart: Point,
  otherEnd: Point,
): number[] {
  const rayX = end.x - start.x;
  const rayY = end.y - start.y;
  const edgeX = otherEnd.x - otherStart.x;
  const edgeY = otherEnd.y - otherStart.y;
  const denominator = rayX * edgeY - rayY * edgeX;
  const offsetX = otherStart.x - start.x;
  const offsetY = otherStart.y - start.y;
  if (denominator === 0) {
    if (offsetX * rayY - offsetY * rayX !== 0) return [];
    const lengthSquared = rayX * rayX + rayY * rayY;
    if (lengthSquared === 0) return [];
    return [
      (offsetX * rayX + offsetY * rayY) / lengthSquared,
      ((otherEnd.x - start.x) * rayX + (otherEnd.y - start.y) * rayY) /
        lengthSquared,
    ];
  }
  const parameter = (offsetX * edgeY - offsetY * edgeX) / denominator;
  const otherParameter = (offsetX * rayY - offsetY * rayX) / denominator;
  return parameter >= -GEOMETRY_EPSILON &&
    parameter <= 1 + GEOMETRY_EPSILON &&
    otherParameter >= -GEOMETRY_EPSILON &&
    otherParameter <= 1 + GEOMETRY_EPSILON
    ? [parameter]
    : [];
}

function pointInPolygonUnion(point: Point, polygons: Point[][]): boolean {
  return polygons.some((polygon) => pointInPolygon(point.x, point.y, polygon));
}

function findClearlySelectedCandidate(
  candidates: Candidate[],
  currentCardId: string | null,
  currentPolygons: Point[][],
  point: Point,
): { candidate: Candidate; polygonIndex: number } | null {
  if (!isClearlyOutsidePolygons(currentPolygons, point)) return null;
  let selected: {
    candidate: Candidate;
    polygonIndex: number;
    clearance: number;
  } | null = null;
  for (const candidate of candidates) {
    if (candidate.card_id === currentCardId) continue;
    const polygons = geometryPolygons(candidate.geometry);
    for (const [polygonIndex, polygon] of polygons.entries()) {
      if (polygon.length < 3 || !pointInPolygon(point.x, point.y, polygon)) {
        continue;
      }
      const clearance = polygonClearanceRatio(point, polygon);
      if (clearance <= POLYGON_SWITCH_CLEARANCE_RATIO) continue;
      if (selected === null || clearance > selected.clearance) {
        selected = { candidate, polygonIndex, clearance };
      }
    }
  }
  return selected === null
    ? null
    : {
        candidate: selected.candidate,
        polygonIndex: selected.polygonIndex,
      };
}

function findClearlySelectedPolygon(
  polygons: Point[][],
  currentPolygonIndex: number,
  point: Point,
): number | null {
  const currentPolygon = polygons[currentPolygonIndex];
  if (currentPolygon === undefined || currentPolygon.length < 3) return null;
  if (!isClearlyOutsidePolygons([currentPolygon], point)) {
    return null;
  }
  let selected: { index: number; clearance: number } | null = null;
  for (const [polygonIndex, polygon] of polygons.entries()) {
    if (
      polygonIndex === currentPolygonIndex ||
      polygon.length < 3 ||
      !pointInPolygon(point.x, point.y, polygon)
    ) {
      continue;
    }
    const clearance = polygonClearanceRatio(point, polygon);
    if (clearance <= POLYGON_SWITCH_CLEARANCE_RATIO) continue;
    if (selected === null || clearance > selected.clearance) {
      selected = { index: polygonIndex, clearance };
    }
  }
  return selected?.index ?? null;
}

function isClearlyOutsidePolygons(polygons: Point[][], point: Point): boolean {
  const completePolygons = polygons.filter((polygon) => polygon.length >= 3);
  if (completePolygons.length === 0) return true;
  if (pointInPolygonUnion(point, completePolygons)) return false;
  return completePolygons.every(
    (polygon) =>
      polygonClearanceRatio(point, polygon) > POLYGON_SWITCH_CLEARANCE_RATIO,
  );
}

function polygonClearanceRatio(point: Point, polygon: Point[]): number {
  const scale = polygonScale(polygon);
  let nearestDistanceSquared = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length; index += 1) {
    nearestDistanceSquared = Math.min(
      nearestDistanceSquared,
      squaredDistanceToSegment(
        point,
        polygon[index],
        polygon[(index + 1) % polygon.length],
      ),
    );
  }
  return Math.sqrt(nearestDistanceSquared) / scale;
}

function polygonScale(polygon: Point[]): number {
  const xValues = polygon.map((point) => point.x);
  const yValues = polygon.map((point) => point.y);
  return Math.max(
    1,
    Math.hypot(
      Math.max(...xValues) - Math.min(...xValues),
      Math.max(...yValues) - Math.min(...yValues),
    ),
  );
}

function pointInPolygon(x: number, y: number, polygon: Point[]): boolean {
  let inside = false;
  for (let index = 0; index < polygon.length; index += 1) {
    const first = polygon[index];
    const second = polygon[(index + 1) % polygon.length];
    if (pointOnSegment(x, y, first, second)) return true;
    if (first.y > y === second.y > y) continue;
    const intersectionX =
      first.x + ((y - first.y) * (second.x - first.x)) / (second.y - first.y);
    if (x < intersectionX) inside = !inside;
  }
  return inside;
}

function pointOnSegment(
  x: number,
  y: number,
  start: Point,
  end: Point,
): boolean {
  const cross =
    (x - start.x) * (end.y - start.y) - (y - start.y) * (end.x - start.x);
  if (Math.abs(cross) > GEOMETRY_EPSILON) return false;
  return (
    Math.min(start.x, end.x) - GEOMETRY_EPSILON <= x &&
    x <= Math.max(start.x, end.x) + GEOMETRY_EPSILON &&
    Math.min(start.y, end.y) - GEOMETRY_EPSILON <= y &&
    y <= Math.max(start.y, end.y) + GEOMETRY_EPSILON
  );
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

function insertPointOnNearestEdge(polygon: Point[], point: Point): Point[] {
  let nearestEdgeIndex = 0;
  let nearestDistanceSquared = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length; index += 1) {
    const distanceSquared = squaredDistanceToSegment(
      point,
      polygon[index],
      polygon[(index + 1) % polygon.length],
    );
    if (distanceSquared < nearestDistanceSquared) {
      nearestDistanceSquared = distanceSquared;
      nearestEdgeIndex = index;
    }
  }
  return [
    ...polygon.slice(0, nearestEdgeIndex + 1),
    point,
    ...polygon.slice(nearestEdgeIndex + 1),
  ];
}

function squaredDistanceToSegment(
  point: Point,
  start: Point,
  end: Point,
): number {
  const horizontal = end.x - start.x;
  const vertical = end.y - start.y;
  const lengthSquared = horizontal ** 2 + vertical ** 2;
  if (lengthSquared === 0)
    return (point.x - start.x) ** 2 + (point.y - start.y) ** 2;
  const position = Math.min(
    Math.max(
      ((point.x - start.x) * horizontal + (point.y - start.y) * vertical) /
        lengthSquared,
      0,
    ),
    1,
  );
  const nearestX = start.x + position * horizontal;
  const nearestY = start.y + position * vertical;
  return (point.x - nearestX) ** 2 + (point.y - nearestY) ** 2;
}

function pointFromEvent(
  event: ReactPointerEvent<SVGSVGElement>,
  providedPoint?: Point | null,
): Point | null {
  if (providedPoint !== undefined) return providedPoint;
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
): "cards" | "ignored" | "cards_and_ignored" | "empty" | "unusable" | null {
  if (frame.outcome.status === "detected" && frame.reviewState === "accepted") {
    const hasCards = frame.outcome.candidates.length > 0;
    const hasIgnoredRegions = frame.outcome.ignored_regions.length > 0;
    if (hasCards && hasIgnoredRegions) return "cards_and_ignored";
    if (hasCards) return "cards";
    if (hasIgnoredRegions) return "ignored";
  }
  if (frame.outcome.status === "empty" && frame.reviewState === "empty")
    return "empty";
  if (frame.outcome.status === "failed" && frame.reviewState === "unusable")
    return "unusable";
  return null;
}

function nextManualCardId(frame: EditableFrame): string {
  return `manual-${frame.itemId}-${Date.now()}`;
}

function nextManualRegionId(frame: EditableFrame): string {
  return `ignore-${frame.itemId}-${Date.now()}`;
}

function copiedIgnoreRegionId(frame: EditableFrame, index: number): string {
  return `ignore-${frame.itemId}-copied-${index + 1}`;
}

function newIgnoreRegion(frame: EditableFrame, regionId: string): IgnoreRegion {
  const identity = frame.outcome.frame_identity;
  return {
    region_id: regionId,
    geometry: {
      kind: "reviewed-ignore-region/v1",
      polygons: [],
    },
    normalization: {
      width: identity?.width ?? 1,
      height: identity?.height ?? 1,
      policy_id: "full-frame-0-1000/v1",
    },
    reason: "untidy_stack",
    source_candidates: [],
  };
}

function ignoreRegionMapping(region: IgnoreRegion): Record<string, unknown> {
  return {
    region_id: region.region_id,
    geometry: {
      kind: region.geometry.kind,
      polygons: region.geometry.polygons.map((polygon) =>
        polygon.map((point) => ({ x: point.x, y: point.y })),
      ),
    },
    normalization: { ...region.normalization },
    reason: region.reason,
    source_candidates: region.source_candidates.map((source) => ({
      ...source,
    })),
  };
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
  window.dispatchEvent(new PopStateEvent("popstate"));
}
