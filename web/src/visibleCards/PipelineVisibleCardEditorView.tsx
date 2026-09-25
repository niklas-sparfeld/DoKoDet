import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import styles from "../App.module.css";
import {
  findAdjacentUnfinishedItem,
  ignoresReviewNavigationShortcut,
} from "../reviewNavigation";
import { Toast } from "../Toast";
import {
  frameReviewStatus,
  formatFrameTime,
} from "./PipelineVisibleCardFormatting";
import { usePipelineVisibleCardEditorController } from "./PipelineVisibleCardEditorController";
import {
  copiedIgnoreRegionId,
  frameCoverageKey,
  frameDecision,
  ignoreRegionMapping,
  newIgnoreRegion,
  nextManualCardId,
  nextManualRegionId,
} from "./PipelineVisibleCardData";
import {
  candidateIsWithinIgnoreRegions,
  clamp,
  findClearlySelectedCandidate,
  findClearlySelectedPolygon,
  geometryPolygons,
  insertPointOnNearestEdge,
  pointFromEvent,
  reviewedGeometry,
  validatePolygons,
} from "./PipelineVisibleCardGeometry";
import {
  readPipelineEditorUrlState,
  updatePipelineUrl,
} from "./PipelineVisibleCardUrl";
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
import { usePipelineReviewPrewarm } from "../pipeline/pipelineReviewPrewarm";
import { usePageVisibility } from "../pipeline/usePageVisibility";
import type {
  Candidate,
  CalibrationRefinementResponse,
  EditableFrame,
  IgnoreRegion,
  EditorState,
  Outcome,
  PipelineVisibleCardRailItem,
  PipelineProposalRunResponse,
  PipelineReferenceOperation,
  PipelineReferenceResource,
  Point,
  SaveState,
} from "./PipelineVisibleCardTypes";

export type { PipelineVisibleCardRailItem } from "./PipelineVisibleCardTypes";

const POINT_DRAG_THRESHOLD_PX = 4;
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

export function PipelineVisibleCardEditorView({
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
  const profileName = useProfileName();
  const pageVisible = usePageVisibility();
  const referenceRef = useRef<PipelineReferenceResource | null>(null);
  const framesRef = useRef<EditableFrame[]>([]);
  const selectedFrameIdRef = useRef<string | null>(null);
  const serverRevisionRef = useRef(0);
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
  const calibrationRefinementRef = useRef<CalibrationRefinementResponse | null>(
    null,
  );
  const [calibrationLoading, setCalibrationLoading] = useState(false);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  useEffect(() => {
    calibrationRefinementRef.current = calibrationRefinement;
  }, [calibrationRefinement]);
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
  const calibrationProposalRevisionId = usesMaintainedFrames
    ? (reference?.draft.proposal_revision_id ?? null)
    : proposalRevisionId;

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

  const commandController = usePipelineVisibleCardEditorController({
    recordingId,
    operatorId,
    generatedRevisionId,
    generatedSourceRevisionId,
    proposalRevisionId,
    proposalRun,
    referenceRef,
    serverRevisionRef,
    selectedFrameIdRef,
    inspectedFrameKeysRef,
    setInspectedFrameKeys,
    getFrames: () => framesRef.current,
    setLocalFrames,
    completionBusy,
    saveState,
    setSaveState,
    setError,
    setNotice,
    setRebasingReference,
    setRebasingProposal,
    generatedRunId,
    setGeneratedFrames,
    setGeneratedLoading,
    setLoading,
    setReference,
    setSelected,
    setProposalRun,
    setProposalRevisionId,
    setProposalLoading,
    setProposalError,
    setCalibrationRefinement,
    calibrationRefinementRef,
    setCalibrationLoading,
    setCalibrationError,
    setCreatingReference,
    setCompletionBusy,
    setReviewerId,
    calibrationProposalRevisionId,
  });
  const {
    enqueue,
    enqueueOperations,
    queueLength,
    firstUnappliedCommand,
    retryQueuedCommands,
    reloadWinningDraft,
    startReference,
    rebaseReference,
    rebaseReferenceToProposal,
    hasPendingCommands,
    isProcessing,
    loadGenerated,
    loadReference,
    loadProposalRun,
    refreshProposalRun,
    startProposal,
    retryProposal,
    loadCalibrationRefinement,
    startCalibrationRefinement,
    refreshCalibrationPreview,
    updateCalibrationAnchor,
    discardCalibrationRefinement,
    applyCalibrationRefinement,
    createReference: createReferenceInController,
    completeReference: completeReferenceInController,
  } = commandController;

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCalibrationRefinement(), 0);
    return () => window.clearTimeout(timer);
  }, [calibrationProposalRevisionId, loadCalibrationRefinement]);

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
  }, [recordingId, generatedSourceRevisionId, loadProposalRun]);

  useEffect(() => {
    if (
      !pageVisible ||
      (proposalRun?.status !== "queued" && proposalRun?.status !== "running")
    )
      return;
    let cancelled = false;
    let timer: number | null = null;
    const controller = new AbortController();
    const poll = async () => {
      const run = await refreshProposalRun(
        proposalRun.run_id,
        controller.signal,
      );
      if (
        !cancelled &&
        !controller.signal.aborted &&
        (run === null || run.status === "queued" || run.status === "running")
      ) {
        timer = window.setTimeout(() => void poll(), 2000);
      }
    };
    timer = window.setTimeout(() => void poll(), 2000);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      controller.abort();
    };
  }, [pageVisible, proposalRun, refreshProposalRun]);

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
      };
      // Convert only when every selected card is already on the maintained frame.
      // Otherwise create from detector fallback geometry — those IDs are not on the draft.
      // Do not send source_candidates: the backend assigns them from candidate_ids.
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
    [endEditMode, enqueue, generatedFrames, selectedCandidateIds],
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
      hasPendingCommands() ||
      isProcessing() ||
      saveState !== "saved"
    )
      return;
    await completeReferenceInController(reviewerId);
  }, [
    completeReferenceInController,
    hasPendingCommands,
    isProcessing,
    reviewerId,
    saveState,
  ]);

  const createReference = useCallback(async () => {
    await createReferenceInController();
  }, [createReferenceInController]);

  const startReviewFromProposal = useCallback(async () => {
    if (proposalRevisionId === null) return;
    if (referenceRef.current === null) {
      await createReference();
    }
    onReviewRequested?.();
  }, [createReference, onReviewRequested, proposalRevisionId]);

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
      refreshCalibrationPreview={() => void refreshCalibrationPreview()}
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
                onAnchorCommand={updateCalibrationAnchor}
                onStartProposal={() => void startProposal()}
                onStartMappingPreview={() => void startCalibrationRefinement()}
                onDiscardMappingPreview={() =>
                  void discardCalibrationRefinement()
                }
                mappingLoading={calibrationLoading}
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
