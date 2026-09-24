import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";

import type { CalibrationRefinementResponse } from "../api/client";
import { pipelineDerivedFramePath } from "../api/client";
import type { CalibrationFitDiagnosticOutline } from "./CalibrationFitDiagnostics";
import { useTimelineRailReviewControlsSlot } from "../pipeline/TimelineRailSeekingControls";
import styles from "./PipelineVisibleCardEditor.module.css";
import {
  WorkbenchCommandBar,
  WorkbenchTimelineSelectionActions,
} from "./VisibleCardWorkbenchControls";
import { WorkbenchProposalColumn } from "./VisibleCardWorkbenchProposalPresentation";
import {
  WorkbenchSurface,
  WORKBENCH_LAYER_REGISTRY,
  readCalibrationAnchors,
} from "./VisibleCardWorkbenchSurface";
import {
  useVisibleCardWorkbenchInteraction,
  type MappingWorkbenchAction,
} from "./VisibleCardWorkbenchInteraction";
import {
  candidateIsCoveredByIgnoreRegions,
  selectedPoseForSelection,
} from "./VisibleCardWorkbenchGeometry";
import {
  applyPoseSceneAction,
  nextManualPoseId,
  withSceneDigest,
  type CalibrationAnchorCommand,
  type PoseSceneEnvelope,
} from "./PoseBasedVisibleCardScene";
import type {
  Candidate,
  EditableFrame,
  EditorState,
  IgnoreRegion,
  Point,
} from "./PipelineVisibleCardTypes";
import {
  createVisibleCardReviewWorkbenchState,
  getWorkbenchAvailability,
  getWorkbenchPreferences,
  visibleCardReviewWorkbenchReducer,
  workbenchCapabilitiesFromFrame,
  type WorkbenchPreferences,
  type WorkbenchSelection,
} from "./VisibleCardReviewWorkbenchState";

type CandidateCalibration = {
  table_to_image: number[][];
  card_short_size: number;
  card_long_size: number;
};

export type VisibleRegionWorkbenchAction =
  | "add_visible_card"
  | "add_polygon"
  | "remove_polygon"
  | "draw_ignore_region"
  | "convert_to_ignore_region"
  | "copy_ignore_regions"
  | "delete_selection"
  | "restore_suggestion";

export type VirtualCardWorkbenchAction =
  | "add_virtual_card"
  | "accept_card"
  | "reject_card"
  | "accept_remaining_cards"
  | "remove_card"
  | "bring_forward"
  | "send_backward"
  | "restore_proposed_scene";

export type VisibleCardReviewWorkbenchAction =
  | VisibleRegionWorkbenchAction
  | VirtualCardWorkbenchAction
  | MappingWorkbenchAction;

export type { MappingWorkbenchAction };

type WorkbenchPointHandler = (
  event: ReactPointerEvent<SVGSVGElement>,
  point: Point | null,
) => void;

export type VisibleCardFrameDecision = {
  accepted: boolean;
  canAccept: boolean;
  acceptDisabledReason: string;
  onAccept: () => void;
  onMarkEmpty: () => void;
  onMarkUnusable: () => void;
};

export { WORKBENCH_LAYER_REGISTRY };

export type VisibleCardReviewWorkbenchProps = {
  recordingId: string;
  frame: EditableFrame;
  readOnly: boolean;
  candidateCalibration?: CandidateCalibration | null;
  calibrationFitOutlines?: CalibrationFitDiagnosticOutline[];
  calibrationRefinement?: CalibrationRefinementResponse | null;
  detectedCandidates?: Candidate[];
  initialPreferences?: Partial<WorkbenchPreferences>;
  onSelectionChange?: (selection: WorkbenchSelection | null) => void;
  frameDecision?: VisibleCardFrameDecision;
  enabledEditTools?: readonly WorkbenchPreferences["activeTool"][];
  editor?: EditorState | null;
  editorError?: string | null;
  selectedCandidateIds?: string[];
  proposalSlot?: HTMLElement | null;
  canCopyIgnoreRegions?: boolean;
  canRestoreSuggestion?: boolean;
  onToolChange?: (tool: WorkbenchPreferences["activeTool"]) => void;
  onStartProposal?: () => void;
  onAction?: (
    action: VisibleCardReviewWorkbenchAction,
    selection: WorkbenchSelection | null,
  ) => void;
  onSceneChange?: (scene: PoseSceneEnvelope, notice: string) => void;
  onAnchorCommand?: (
    command: CalibrationAnchorCommand,
  ) => Promise<boolean> | void;
  onStartMappingPreview?: () => void;
  onDiscardMappingPreview?: () => void;
  mappingLoading?: boolean;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onOpenEditor?: (candidate: Candidate | null, polygonIndex?: number) => void;
  onOpenIgnoreRegion?: (region: IgnoreRegion | null) => void;
  onToggleCandidateSelection?: (cardId: string) => void;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onPointPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
  onCanvasPointerDown?: WorkbenchPointHandler;
  onPointerMove?: WorkbenchPointHandler;
  onPointerLeave?: WorkbenchPointHandler;
  onPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerCancel?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onDeleteSelectedPoint?: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
};

export function VisibleCardReviewWorkbenchView({
  recordingId,
  frame,
  readOnly,
  candidateCalibration = null,
  calibrationFitOutlines = [],
  calibrationRefinement = null,
  detectedCandidates,
  initialPreferences,
  onSelectionChange,
  frameDecision,
  enabledEditTools,
  editor = null,
  editorError = null,
  selectedCandidateIds = [],
  proposalSlot,
  canCopyIgnoreRegions = false,
  canRestoreSuggestion = false,
  onToolChange,
  onStartProposal,
  onAction,
  onSceneChange,
  onAnchorCommand,
  onStartMappingPreview,
  onDiscardMappingPreview,
  mappingLoading = false,
  onCardDecision,
  onResolveRemaining,
  onOpenEditor,
  onOpenIgnoreRegion,
  onToggleCandidateSelection,
  onSelectEditorPolygon,
  onPointPointerDown,
  onCanvasPointerDown,
  onPointerMove,
  onPointerLeave,
  onPointerUp,
  onPointerCancel,
  onDeleteSelectedPoint,
}: VisibleCardReviewWorkbenchProps) {
  const allCandidates =
    frame.outcome.candidates.length > 0
      ? frame.outcome.candidates
      : (detectedCandidates ?? []);
  const displayedCandidates = allCandidates.filter(
    (candidate) =>
      !candidateIsCoveredByIgnoreRegions(
        candidate,
        frame.outcome.ignored_regions,
      ),
  );
  const capabilities = workbenchCapabilitiesFromFrame(
    frame,
    readOnly,
    displayedCandidates,
  );
  const frameScene = frame.outcome.card_scene ?? null;
  const sceneIdentity = `${frame.itemId}:${frameScene?.scene.scene_digest ?? "none"}`;
  const [sceneDraft, setSceneDraft] = useState<PoseSceneEnvelope | null>(
    frameScene,
  );
  const sceneDraftRef = useRef<PoseSceneEnvelope | null>(frameScene);
  const sceneIdentityRef = useRef(sceneIdentity);
  const [state, dispatch] = useReducer(
    visibleCardReviewWorkbenchReducer,
    { capabilities, preferences: initialPreferences },
    ({ capabilities: initialCapabilities, preferences }) =>
      createVisibleCardReviewWorkbenchState(initialCapabilities, preferences),
  );
  const previousFrameId = useRef(frame.itemId);
  const capabilitiesKey = JSON.stringify(capabilities);
  const appliedCapabilitiesKey = useRef(capabilitiesKey);

  useEffect(() => {
    if (sceneIdentityRef.current === sceneIdentity) return;
    sceneIdentityRef.current = sceneIdentity;
    sceneDraftRef.current = frameScene;
    setSceneDraft(frameScene);
  }, [frameScene, sceneIdentity]);

  const commitScene = (next: PoseSceneEnvelope, notice: string) => {
    sceneDraftRef.current = next;
    setSceneDraft(next);
    void withSceneDigest(next).then(
      (digested) => {
        sceneDraftRef.current = digested;
        setSceneDraft(digested);
        onSceneChange?.(digested, notice);
      },
      () => onSceneChange?.(next, notice),
    );
  };

  const applySceneAction = (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => {
    const current = sceneDraftRef.current;
    if (readOnly || current === null) return;
    commitScene(applyPoseSceneAction(current, action), notice);
  };

  useEffect(() => {
    if (previousFrameId.current === frame.itemId) return;
    previousFrameId.current = frame.itemId;
    dispatch({ type: "navigate_frame", capabilities });
  }, [capabilities, frame.itemId]);

  useEffect(() => {
    if (
      state.frameId !== frame.itemId ||
      appliedCapabilitiesKey.current === capabilitiesKey
    )
      return;
    appliedCapabilitiesKey.current = capabilitiesKey;
    dispatch({ type: "refresh_capabilities", capabilities });
  }, [capabilitiesKey, frame.itemId, state.frameId]);

  const activeState =
    state.frameId === frame.itemId
      ? state
      : createVisibleCardReviewWorkbenchState(
          capabilities,
          getWorkbenchPreferences(state),
        );
  const viewport = activeState.viewports[activeState.viewpoint];
  const availability = getWorkbenchAvailability(capabilities);
  const scene = sceneDraft;
  const sourceIdentity = frame.outcome.frame_identity;
  const width = sourceIdentity?.width ?? scene?.scene.source_frame_width ?? 1;
  const height =
    sourceIdentity?.height ?? scene?.scene.source_frame_height ?? 1;
  const sourceUrl =
    sourceIdentity === null
      ? null
      : pipelineDerivedFramePath(
          recordingId,
          sourceIdentity?.requested_time_us ?? 0,
        );
  const candidateProjection = useMemo(
    () =>
      candidateCalibration === null
        ? null
        : {
            table_to_image_homography: candidateCalibration.table_to_image,
            card_short_size: candidateCalibration.card_short_size,
            card_long_size: candidateCalibration.card_long_size,
          },
    [candidateCalibration],
  );
  const mappingAnchors = useMemo(
    () =>
      readCalibrationAnchors(
        calibrationRefinement,
        frame.itemId,
        frame.outcome.event_id,
        scene?.scene.source_frame_id ?? null,
      ),
    [calibrationRefinement, frame.itemId, frame.outcome.event_id, scene],
  );
  const selectedMappingAnchor =
    activeState.selection?.type === "calibration_anchor"
      ? (mappingAnchors.find(
          (anchor) => anchor.anchorId === activeState.selection?.id,
        ) ?? null)
      : null;

  const timelineReviewControlsSlot = useTimelineRailReviewControlsSlot();

  const select = (selection: WorkbenchSelection) => {
    dispatch({ type: "select", selection });
    onSelectionChange?.(selection);
  };

  const clearSelection = () => {
    if (activeState.selection === null) return;
    dispatch({ type: "clear_selection" });
    onSelectionChange?.(null);
  };

  const interaction = useVisibleCardWorkbenchInteraction({
    readOnly,
    activeState,
    viewport,
    width,
    height,
    frameId: frame.itemId,
    calibrationRefinement,
    mappingAnchors,
    selectedMappingAnchor,
    sceneDraftRef,
    setSceneDraft,
    commitScene,
    applySceneAction,
    select,
    clearSelection,
    dispatch,
    onAnchorCommand,
    onStartMappingPreview,
    onDiscardMappingPreview,
    onCanvasPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
  });
  const {
    anchorPreview,
    anchorCornerIndex,
    numericAnchor,
    gestureViewBox,
    setAnchorCornerIndex,
    handleSurfaceKeyDown,
    handleVirtualCardKeyDown,
    handleMappingAction,
    beginMappingAnchorGesture,
    beginMappingNumericEdit,
    emitNumericAnchorCommand,
    beginVirtualCardGesture,
    handleSurfacePointerDown,
    handleSurfacePointerMove,
    finishVirtualGesture,
    cancelVirtualGesture,
    handleSurfaceWheel,
  } = interaction;
  const renderMappingAnchors = mappingAnchors.map((anchor) =>
    anchorPreview?.anchorId === anchor.anchorId ? anchorPreview : anchor,
  );

  const handleWorkbenchAction = (action: VisibleCardReviewWorkbenchAction) => {
    if (action === "add_virtual_card") {
      if (scene !== null) {
        const selectedPose = selectedPoseForSelection(
          scene,
          activeState.selection,
        );
        const center = selectedPose?.center ?? [0, 0];
        const cardId = nextManualPoseId(scene.scene);
        select({ type: "virtual_card", id: cardId });
        applySceneAction(
          {
            type: "add",
            cardId,
            center: [center[0] + 0.2, center[1] + 0.2],
          },
          "Standard-size card added to the virtual table.",
        );
      }
      return;
    }
    if (action === "remove_card") {
      const selectedPose =
        scene === null
          ? null
          : selectedPoseForSelection(scene, activeState.selection);
      if (scene !== null && selectedPose !== null) {
        const nextSelection = scene.scene.poses.find(
          (pose) => pose.card_id !== selectedPose.card_id,
        );
        applySceneAction(
          { type: "remove", cardId: selectedPose.card_id },
          "Card removed from the virtual table.",
        );
        if (nextSelection === undefined) dispatch({ type: "clear_selection" });
        else select({ type: "virtual_card", id: nextSelection.card_id });
      }
      return;
    }
    if (action === "bring_forward" || action === "send_backward") {
      const selectedPose =
        scene === null
          ? null
          : selectedPoseForSelection(scene, activeState.selection);
      if (selectedPose !== null) {
        applySceneAction(
          { type: action, cardId: selectedPose.card_id },
          action === "bring_forward"
            ? "Card brought forward."
            : "Card sent backward.",
        );
      }
      return;
    }
    if (action === "restore_proposed_scene") {
      applySceneAction(
        { type: "restore_initialized" },
        "Proposed card scene restored.",
      );
      return;
    }
    if (
      action === "accept_anchor" ||
      action === "exclude_anchor" ||
      action === "start_mapping_preview" ||
      action === "discard_mapping_preview"
    ) {
      handleMappingAction(action);
      return;
    }
    onAction?.(action, activeState.selection);
  };

  const timelineSelectionActions = (
    <WorkbenchTimelineSelectionActions
      viewModel={{
        activeTool: activeState.activeTool,
        selection: activeState.selection,
        readOnly,
        selectedCandidateIds,
        editor:
          editor === null
            ? null
            : {
                cardId: editor.cardId,
                polygonCount: editor.polygons.length,
                polygonIndex: editor.polygonIndex,
              },
        sourceAvailable: availability.viewpoints.camera.available,
        canCopyIgnoreRegions,
        canRestoreSuggestion,
        frameDecision,
        scene,
        calibrationRefinement,
        mappingAnchors,
        mappingLoading,
        anchorCornerIndex,
        numericAnchor,
      }}
      callbacks={{
        onNumericChange: beginMappingNumericEdit,
        onEmitNumeric: emitNumericAnchorCommand,
        onCardDecision,
        onResolveRemaining,
        onSceneAction: applySceneAction,
        onAction: handleWorkbenchAction,
      }}
    />
  );

  return (
    <section
      className={styles.workbench}
      aria-label="Visible-card review workbench"
      data-viewpoint={activeState.viewpoint}
      data-read-only={readOnly}
    >
      <WorkbenchCommandBar
        viewModel={{
          viewpoint: activeState.viewpoint,
          enabledLayers: activeState.enabledLayers,
          activeTool: activeState.activeTool,
          availability,
          readOnly,
          enabledEditTools: enabledEditTools ?? [
            "visible_regions",
            "virtual_cards",
            "mapping",
          ],
        }}
        callbacks={{
          onToggleViewpoint: () => dispatch({ type: "toggle_viewpoint" }),
          onToggleLayer: (layer) => dispatch({ type: "toggle_layer", layer }),
          onSelectTool: (tool) => {
            dispatch({ type: "select_tool", tool });
            onToolChange?.(tool);
          },
          onStartProposal,
          onStartMappingPreview,
        }}
      />
      {timelineReviewControlsSlot === null
        ? timelineSelectionActions
        : createPortal(timelineSelectionActions, timelineReviewControlsSlot)}
      <div className={styles.workbenchSurfaceLayout}>
        <WorkbenchSurface
          frame={frame}
          candidates={displayedCandidates}
          scene={scene}
          sourceUrl={sourceUrl}
          width={width}
          height={height}
          viewpoint={activeState.viewpoint}
          activeTool={activeState.activeTool}
          enabledLayers={activeState.enabledLayers}
          selection={activeState.selection}
          viewport={viewport}
          gestureViewBox={gestureViewBox}
          candidateProjection={candidateProjection}
          calibrationFitOutlines={calibrationFitOutlines}
          mappingAnchors={renderMappingAnchors}
          editor={editor}
          includeIgnoreRegionCount={proposalSlot !== undefined}
          onSelect={select}
          onKeyDown={handleSurfaceKeyDown}
          onPointPointerDown={onPointPointerDown}
          onCanvasPointerDown={handleSurfacePointerDown}
          onPointerMove={handleSurfacePointerMove}
          onPointerLeave={onPointerLeave}
          onPointerUp={finishVirtualGesture}
          onPointerCancel={cancelVirtualGesture}
          onWheel={handleSurfaceWheel}
          onDeleteSelectedPoint={onDeleteSelectedPoint}
          onVirtualCardPointerDown={beginVirtualCardGesture}
          onVirtualCardKeyDown={handleVirtualCardKeyDown}
          onMappingAnchorPointerDown={beginMappingAnchorGesture}
          onMappingAnchorCornerSelect={setAnchorCornerIndex}
        />
        {proposalSlot !== undefined ? (
          <WorkbenchProposalColumn
            frame={frame}
            candidates={allCandidates}
            scene={scene}
            activeTool={activeState.activeTool}
            sourceUrl={sourceUrl}
            frameWidth={width}
            frameHeight={height}
            readOnly={readOnly}
            selection={activeState.selection}
            editor={
              editor === null
                ? null
                : {
                    cardId: editor.cardId,
                    polygonCount: editor.polygons.length,
                    polygonIndex: editor.polygonIndex,
                  }
            }
            editorError={editorError}
            selectedCandidateIds={selectedCandidateIds}
            mappingAnchors={mappingAnchors}
            onToggleCandidateSelection={(cardId) => {
              if (activeState.activeTool !== "visible_regions") {
                dispatch({ type: "select_tool", tool: "visible_regions" });
                onToolChange?.("visible_regions");
              }
              onToggleCandidateSelection?.(cardId);
            }}
            onSelectCandidate={(candidate, polygonIndex) => {
              select(
                polygonIndex === undefined
                  ? { type: "visible_card", id: candidate.card_id }
                  : {
                      type: "polygon",
                      id: candidate.card_id,
                      polygonIndex,
                    },
              );
              onOpenEditor?.(candidate, polygonIndex);
            }}
            onSelectVirtualCard={(cardId) =>
              select({ type: "virtual_card", id: cardId })
            }
            onSceneAction={applySceneAction}
            onSelectIgnoreRegion={(region) => {
              select({ type: "ignore_region", id: region.region_id });
              onOpenIgnoreRegion?.(region);
            }}
            onSelectEditorPolygon={onSelectEditorPolygon}
            proposalSlot={proposalSlot}
          />
        ) : null}
      </div>
    </section>
  );
}
