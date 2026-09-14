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
  type PipelineReferenceItem,
  type PipelineReferenceOperation,
  type PipelineReferenceResource,
  type PipelineVisibleCardResult,
} from "../api/client";
import styles from "../App.module.css";
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
  VisibleCardFramePanel,
  VisibleCardReviewControls,
} from "./PipelineVisibleCardPresentation";
import visibleStyles from "./PipelineVisibleCardEditor.module.css";
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
    dirty: boolean;
  } | null>(null);
  const [reference, setReference] = useState<PipelineReferenceResource | null>(
    null,
  );
  const [frames, setFrames] = useState<EditableFrame[]>([]);
  const [generatedFrames, setGeneratedFrames] = useState<EditableFrame[]>([]);
  const [selectedFrameId, setSelectedFrameId] = useState<string | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null,
  );
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
  const [completionBusy, setCompletionBusy] = useState(false);
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
    setSelectedCandidateId(null);
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
      },
      "Maintained visible-card reference seeded from the selected generated result.",
      (currentFrames) => currentFrames,
    );
  }, [enqueue, generatedSourceRevisionId, operatorId]);

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
      setSelectedCandidateId(candidate?.card_id ?? null);
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
      setSelectedCandidateId(null);
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
      setSelectedCandidateId((current) =>
        current === cardId ? null : current,
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
      const selected = frame.outcome.candidates.filter((candidate) =>
        selectedCandidateIds.includes(candidate.card_id),
      );
      if (selected.length === 0) return;
      const region = newIgnoreRegion(frame, nextManualRegionId(frame));
      const operation: PipelineReferenceOperation = {
        operation: "convert_to_ignore_region",
        item_id: frame.itemId,
        region: ignoreRegionMapping({
          ...region,
          geometry: {
            kind: "reviewed-ignore-region/v1",
            polygons: selected.flatMap((candidate) =>
              geometryPolygons(candidate.geometry),
            ),
          },
        }),
        candidate_ids: selected.map((candidate) => candidate.card_id),
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
                !selectedCandidateIds.includes(currentCandidate.card_id),
            );
            return {
              ...candidate,
              reviewState:
                remainingCandidates.length === 0
                  ? "accepted"
                  : candidate.reviewState,
              outcome: {
                ...candidate.outcome,
                status: "detected",
                candidates: remainingCandidates,
                ignored_regions: [
                  ...candidate.outcome.ignored_regions,
                  {
                    ...region,
                    geometry: {
                      kind: "reviewed-ignore-region/v1",
                      polygons: selected.flatMap((currentCandidate) =>
                        geometryPolygons(currentCandidate.geometry),
                      ),
                    },
                  },
                ],
                error: null,
              },
            };
          }),
      );
    },
    [endEditMode, enqueue, selectedCandidateIds],
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

  const addVisibleRegionPoint = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const point = pointFromEvent(event);
      if (point === null) return;
      const currentEditor = editorRef.current;
      if (currentEditor === null) return;
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
    [],
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
            generatedSourceRevisionId === null ? "empty" : "selected_generated",
          ...(generatedSourceRevisionId === null
            ? {}
            : { source_revision_id: generatedSourceRevisionId }),
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
    generatedSourceRevisionId,
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
      const isTimelineSeekingTarget =
        target !== null &&
        typeof target.closest === "function" &&
        target.closest('[data-timeline-seeking-controls="true"]') !== null;
      if (
        target !== null &&
        (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
          (isTimelineSeekingTarget && event.key === " "))
      ) {
        return;
      }
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
      if (!event.altKey && event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        selectFrame(current[index - 1]);
      } else if (
        !event.altKey &&
        event.key === "ArrowRight" &&
        index >= 0 &&
        index < current.length - 1
      ) {
        event.preventDefault();
        selectFrame(current[index + 1]);
      } else if (canEdit && (event.key === "n" || event.key === "N")) {
        const frame = current[index >= 0 ? index : 0];
        if (frame !== undefined) {
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
      referenceNeedsSeed={referenceNeedsSeed}
      startReference={startReference}
      completionBusy={completionBusy}
      completionBlocker={completionBlocker}
      restoreGeneratedSuggestions={() =>
        activeFrame === null
          ? undefined
          : restoreGeneratedSuggestions(activeFrame)
      }
      canRestoreGeneratedSuggestions={
        activeFrame !== null &&
        generatedFrames.some((frame) => frame.itemId === activeFrame.itemId) &&
        activeFrame.reviewState !== "pending"
      }
      retryQueuedCommands={retryQueuedCommands}
      reloadWinningDraft={reloadWinningDraft}
      completeReference={completeReference}
      createReference={createReference}
      onReviewRequested={onReviewRequested}
    />
  );

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
          <div className={visibleStyles.reviewWorkbench}>
            {view === "generated" || editable ? (
              <VisibleCardReviewControls
                editable={editable}
                hasPrevious={activeFrameIndex > 0}
                hasNext={
                  activeFrameIndex >= 0 &&
                  activeFrameIndex < displayedFrames.length - 1
                }
                selectedFrame={activeFrame}
                onPrevious={() => {
                  const previous = displayedFrames[activeFrameIndex - 1];
                  if (previous !== undefined) selectFrame(previous);
                }}
                onNext={() => {
                  const next = displayedFrames[activeFrameIndex + 1];
                  if (next !== undefined) selectFrame(next);
                }}
                onAccept={() => toggleFrameAcceptance(activeFrame)}
                onAddCard={() => openEditor(activeFrame, null)}
                selectedCandidateCount={selectedCandidateIds.length}
                onConvertToIgnoreRegion={() =>
                  convertSelectedToIgnoreRegion(activeFrame)
                }
                onCreateIgnoreRegion={() => openIgnoreRegionEditor(activeFrame)}
                onMarkEmpty={() => setFrameOutcome(activeFrame, "empty")}
                onMarkUnusable={() => setFrameOutcome(activeFrame, "unusable")}
              />
            ) : null}
            <VisibleCardFramePanel
              recordingId={recordingId}
              frame={activeFrame}
              editor={
                editor?.frameItemId === activeFrame.itemId ? editor : null
              }
              selectedCandidateId={selectedCandidateId}
              editorError={editorError}
              selectedCandidateIds={selectedCandidateIds}
              onToggleCandidateSelection={toggleCandidateSelection}
              onOpenIgnoreRegion={
                editable
                  ? (region) => openIgnoreRegionEditor(activeFrame, region)
                  : undefined
              }
              onRemoveIgnoreRegion={
                editable
                  ? (regionId) => removeIgnoreRegion(activeFrame, regionId)
                  : undefined
              }
              readOnly={!editable}
              onSelectCandidate={(candidate) => {
                setSelectedCandidateId(candidate.card_id);
                if (editable) openEditor(activeFrame, candidate);
              }}
              onSelectCandidatePolygon={
                editable
                  ? (candidate, polygonIndex) =>
                      openEditor(activeFrame, candidate, polygonIndex)
                  : undefined
              }
              onOpenEditor={
                editable
                  ? (candidate) => openEditor(activeFrame, candidate)
                  : undefined
              }
              onCancelEditor={editable ? () => setEditor(null) : undefined}
              onRemoveCard={
                editable
                  ? (cardId) => removeCard(activeFrame, cardId)
                  : undefined
              }
              onPointerMove={handleCanvasPointerMove}
              onCanvasPointerDown={addVisibleRegionPoint}
              onPointerUp={stopCanvasPointer}
              onPointPointerDown={startPointDrag}
              onDeleteSelectedPoint={deleteSelectedPoint}
              onSelectEditorPolygon={selectEditorPolygon}
              onAddEditorPolygon={addEditorPolygon}
              onRemoveEditorPolygon={removeEditorPolygon}
              proposalSlot={proposalSlot}
            />
          </div>
        )}
        {notice !== null ? (
          <p className={styles.recordingNotice} role="status">
            {notice}
          </p>
        ) : null}
        {inspectorSlots === null && error !== null ? (
          <div className={styles.cardEventError} role="alert">
            <p>{error}</p>
          </div>
        ) : null}
      </section>
    </>
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
  return {
    event_id: eventId,
    frame_identity: frame,
    status: status as Outcome["status"],
    candidates,
    ignored_regions: ignoredRegions,
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
