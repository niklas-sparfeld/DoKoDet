import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { createPortal } from "react-dom";

import { pipelineDerivedFramePath } from "../api/client";
import styles from "./PipelineVisibleCardEditor.module.css";
import {
  applyPoseSceneAction,
  cardPolygon,
  nextManualPoseId,
  projectImagePointToTable,
  projectTablePoint,
  withSceneDigest,
  type CardSceneProjection,
  type PoseCard,
  type PoseSceneEnvelope,
  type ReviewedCardScene,
  type TablePoint,
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
  layerForSelection,
  visibleCardReviewWorkbenchReducer,
  workbenchCapabilitiesFromFrame,
  workbenchViewportShortcut,
  WORKBENCH_LAYER_DRAW_ORDER,
  WORKBENCH_LAYERS,
  type WorkbenchLayer,
  type WorkbenchPreferences,
  type WorkbenchSelection,
  type WorkbenchViewpoint,
  type VisibleCardReviewWorkbenchState,
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
  VisibleRegionWorkbenchAction | VirtualCardWorkbenchAction;

type WorkbenchPointHandler = (
  event: ReactPointerEvent<SVGSVGElement>,
  point: Point | null,
) => void;

type VirtualCardGesture = {
  pointerId: number;
  cardId: string | null;
  kind: "move" | "rotate" | "pan";
  dirty: boolean;
  startClientX: number;
  startClientY: number;
  originalScene: PoseSceneEnvelope;
  startPan?: { x: number; y: number };
  startViewBox?: { x: number; y: number; width: number; height: number };
};

export type VisibleCardReviewWorkbenchProps = {
  recordingId: string;
  frame: EditableFrame;
  readOnly: boolean;
  candidateCalibration?: CandidateCalibration | null;
  initialPreferences?: Partial<WorkbenchPreferences>;
  onSelectionChange?: (selection: WorkbenchSelection | null) => void;
  enabledEditTools?: readonly WorkbenchPreferences["activeTool"][];
  editor?: EditorState | null;
  editorError?: string | null;
  selectedCandidateIds?: string[];
  proposalSlot?: HTMLElement | null;
  canCopyIgnoreRegions?: boolean;
  canRestoreSuggestion?: boolean;
  onToolChange?: (tool: WorkbenchPreferences["activeTool"]) => void;
  onAction?: (
    action: VisibleCardReviewWorkbenchAction,
    selection: WorkbenchSelection | null,
  ) => void;
  onSceneChange?: (scene: PoseSceneEnvelope, notice: string) => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onOpenEditor?: (candidate: Candidate | null, polygonIndex?: number) => void;
  onOpenIgnoreRegion?: (region: IgnoreRegion | null) => void;
  onRemoveIgnoreRegion?: (regionId: string) => void;
  onToggleCandidateSelection?: (cardId: string) => void;
  onRemoveCard?: (cardId: string) => void;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onCancelEditor?: () => void;
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

const VIEWPOINT_LABELS: Record<WorkbenchViewpoint, string> = {
  camera: "Camera",
  rectified: "Rectified",
};

const LAYER_LABELS: Record<WorkbenchLayer, string> = {
  visible_regions: "Visible regions",
  virtual_cards: "Virtual cards",
  ignore_regions: "Ignore regions",
  suggestions: "Detector suggestions",
  mapping: "Mapping diagnostics",
};

const LATER_EDIT_REASON =
  "This edit tool is planned for a later workbench phase.";

export function VisibleCardReviewWorkbench({
  recordingId,
  frame,
  readOnly,
  candidateCalibration = null,
  initialPreferences,
  onSelectionChange,
  enabledEditTools,
  editor = null,
  editorError = null,
  selectedCandidateIds = [],
  proposalSlot,
  canCopyIgnoreRegions = false,
  canRestoreSuggestion = false,
  onToolChange,
  onAction,
  onSceneChange,
  onCardDecision,
  onResolveRemaining,
  onOpenEditor,
  onOpenIgnoreRegion,
  onRemoveIgnoreRegion,
  onToggleCandidateSelection,
  onRemoveCard,
  onSelectEditorPolygon,
  onCancelEditor,
  onPointPointerDown,
  onCanvasPointerDown,
  onPointerMove,
  onPointerLeave,
  onPointerUp,
  onPointerCancel,
  onDeleteSelectedPoint,
}: VisibleCardReviewWorkbenchProps) {
  const capabilities = workbenchCapabilitiesFromFrame(frame, readOnly);
  const frameScene = frame.outcome.card_scene ?? null;
  const sceneIdentity = `${frame.itemId}:${frameScene?.scene.scene_digest ?? "none"}`;
  const [sceneDraft, setSceneDraft] = useState<PoseSceneEnvelope | null>(
    frameScene,
  );
  const sceneDraftRef = useRef<PoseSceneEnvelope | null>(frameScene);
  const sceneIdentityRef = useRef(sceneIdentity);
  const virtualGestureRef = useRef<VirtualCardGesture | null>(null);
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

  const select = (selection: WorkbenchSelection) => {
    dispatch({ type: "select", selection });
    onSelectionChange?.(selection);
  };

  const handleSurfaceKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    const shortcut = workbenchViewportShortcut(event, "surface");
    if (shortcut === null) return;
    event.preventDefault();
    const viewport = activeState.viewport;
    if (shortcut === "reset") {
      dispatch({ type: "reset_viewport" });
      return;
    }
    const panStep = 0.15 / Math.max(viewport.zoom, 0.5);
    if (shortcut === "zoom_in" || shortcut === "zoom_out") {
      dispatch({
        type: "set_viewport",
        viewport: {
          zoom:
            shortcut === "zoom_in"
              ? Math.min(4, viewport.zoom * 1.2)
              : Math.max(0.5, viewport.zoom / 1.2),
          pan: viewport.pan,
        },
      });
      return;
    }
    dispatch({
      type: "set_viewport",
      viewport: {
        zoom: viewport.zoom,
        pan: {
          x:
            viewport.pan.x +
            (shortcut === "pan_left"
              ? -panStep
              : shortcut === "pan_right"
                ? panStep
                : 0),
          y:
            viewport.pan.y +
            (shortcut === "pan_up"
              ? -panStep
              : shortcut === "pan_down"
                ? panStep
                : 0),
        },
      },
    });
  };

  const handleVirtualCardKeyDown = (
    event: ReactKeyboardEvent<SVGPolygonElement>,
    cardId: string,
  ) => {
    if (readOnly || activeState.activeTool !== "virtual_cards") return;
    if (
      event.key !== "ArrowLeft" &&
      event.key !== "ArrowRight" &&
      event.key !== "ArrowUp" &&
      event.key !== "ArrowDown" &&
      event.key.toLowerCase() !== "r"
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    const delta = event.shiftKey ? 0.1 : 0.025;
    applySceneAction(
      event.key.toLowerCase() === "r"
        ? {
            type: "nudge",
            cardId,
            delta: [0, 0],
            rotationDeltaDegrees: event.shiftKey ? -5 : 5,
          }
        : {
            type: "nudge",
            cardId,
            delta: [
              event.key === "ArrowLeft"
                ? -delta
                : event.key === "ArrowRight"
                  ? delta
                  : 0,
              event.key === "ArrowUp"
                ? -delta
                : event.key === "ArrowDown"
                  ? delta
                  : 0,
            ],
          },
      event.key.toLowerCase() === "r"
        ? "Card rotation nudge saved."
        : "Card nudge saved.",
    );
  };

  const beginVirtualCardGesture = (
    event: ReactPointerEvent<SVGElement>,
    cardId: string,
    kind: "move" | "rotate",
  ) => {
    if (
      readOnly ||
      activeState.activeTool !== "virtual_cards" ||
      sceneDraftRef.current === null
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    select({ type: "virtual_card", id: cardId });
    virtualGestureRef.current = {
      pointerId: event.pointerId,
      cardId,
      kind,
      dirty: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalScene: sceneDraftRef.current,
    };
    event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId);
    dispatch({
      type: "begin_gesture",
      gesture: {
        kind: "edit",
        tool: "virtual_cards",
        pointerId: event.pointerId,
      },
    });
  };

  const beginVirtualTablePan = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (
      event.button !== 0 ||
      event.target !== event.currentTarget ||
      activeState.activeTool !== "virtual_cards" ||
      sceneDraftRef.current === null ||
      virtualGestureRef.current !== null
    )
      return false;
    const currentScene = sceneDraftRef.current;
    const viewBox =
      activeState.viewpoint === "rectified"
        ? tableViewBox(
            currentScene.scene,
            currentScene.projection,
            activeState.viewport,
          )
        : null;
    if (viewBox === null) return false;
    event.preventDefault();
    virtualGestureRef.current = {
      pointerId: event.pointerId,
      cardId: null,
      kind: "pan",
      dirty: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalScene: currentScene,
      startPan: { ...activeState.viewport.pan },
      startViewBox: viewBox,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dispatch({
      type: "begin_gesture",
      gesture: { kind: "pan", tool: null, pointerId: event.pointerId },
    });
    return true;
  };

  const handleSurfacePointerDown = (
    event: ReactPointerEvent<SVGSVGElement>,
    point: Point | null,
  ) => {
    if (beginVirtualTablePan(event)) return;
    if (activeState.activeTool === "virtual_cards") return;
    onCanvasPointerDown?.(event, point);
  };

  const handleSurfacePointerMove = (
    event: ReactPointerEvent<SVGSVGElement>,
    point: Point | null,
  ) => {
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      if (activeState.activeTool === "virtual_cards") return;
      onPointerMove?.(event, point);
      return;
    }
    if (gesture.kind === "pan") {
      const viewBox = gesture.startViewBox;
      const startPan = gesture.startPan;
      const rect = event.currentTarget.getBoundingClientRect();
      if (viewBox === undefined || startPan === undefined || rect.width <= 0)
        return;
      const deltaX = event.clientX - gesture.startClientX;
      const deltaY = event.clientY - gesture.startClientY;
      if (!gesture.dirty && Math.hypot(deltaX, deltaY) < 4) return;
      gesture.dirty = true;
      dispatch({
        type: "set_viewport",
        viewport: {
          zoom: activeState.viewport.zoom,
          pan: {
            x: startPan.x - (deltaX / rect.width) * viewBox.width,
            y: startPan.y - (deltaY / rect.height) * viewBox.height,
          },
        },
      });
      return;
    }
    if (
      point === null ||
      sceneDraftRef.current === null ||
      gesture.cardId === null
    )
      return;
    const deltaX = event.clientX - gesture.startClientX;
    const deltaY = event.clientY - gesture.startClientY;
    if (!gesture.dirty && Math.hypot(deltaX, deltaY) < 4) return;
    const tablePoint = sourcePointToTablePoint(
      point,
      width,
      height,
      sceneDraftRef.current,
    );
    if (tablePoint === null) return;
    const pose = sceneDraftRef.current.scene.poses.find(
      (candidate) => candidate.card_id === gesture.cardId,
    );
    if (pose === undefined) return;
    const next = applyPoseSceneAction(
      sceneDraftRef.current,
      gesture.kind === "move"
        ? { type: "move", cardId: gesture.cardId, center: tablePoint }
        : {
            type: "rotate",
            cardId: gesture.cardId,
            rotationDegrees:
              (Math.atan2(
                tablePoint[1] - pose.center[1],
                tablePoint[0] - pose.center[0],
              ) *
                180) /
                Math.PI +
              90,
          },
    );
    gesture.dirty = true;
    sceneDraftRef.current = next;
    setSceneDraft(next);
  };

  const finishVirtualGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      onPointerUp?.(event);
      return;
    }
    virtualGestureRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dispatch({ type: "commit_gesture" });
    if (!gesture.dirty || gesture.kind === "pan") return;
    const next = sceneDraftRef.current;
    if (next === null) return;
    commitScene(
      next,
      gesture.kind === "move"
        ? "Card moved on the virtual table."
        : "Card rotation saved.",
    );
  };

  const cancelVirtualGesture = (event: ReactPointerEvent<SVGSVGElement>) => {
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      onPointerCancel?.(event);
      if (onPointerCancel === undefined) onPointerUp?.(event);
      return;
    }
    virtualGestureRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    sceneDraftRef.current = gesture.originalScene;
    setSceneDraft(gesture.originalScene);
    dispatch({ type: "cancel_gesture" });
  };

  const handleSurfaceWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    if (activeState.viewpoint !== "rectified" || sceneDraftRef.current === null)
      return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || event.deltaY === 0) return;
    event.preventDefault();
    const currentScene = sceneDraftRef.current;
    const currentViewBox = tableViewBox(
      currentScene.scene,
      currentScene.projection,
      activeState.viewport,
    );
    const deltaY =
      event.deltaY *
      (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
    const nextZoom = Math.min(
      4,
      Math.max(0.5, activeState.viewport.zoom * Math.pow(2, -deltaY / 240)),
    );
    if (nextZoom === activeState.viewport.zoom) return;
    const focusX = (event.clientX - rect.left) / rect.width;
    const focusY = (event.clientY - rect.top) / rect.height;
    const focusedPoint: TablePoint = [
      currentViewBox.x + focusX * currentViewBox.width,
      currentViewBox.y + focusY * currentViewBox.height,
    ];
    const nextViewBox = tableViewBox(
      currentScene.scene,
      currentScene.projection,
      {
        zoom: nextZoom,
        pan: activeState.viewport.pan,
      },
    );
    dispatch({
      type: "set_viewport",
      viewport: {
        zoom: nextZoom,
        pan: {
          x:
            activeState.viewport.pan.x +
            focusedPoint[0] -
            (nextViewBox.x + focusX * nextViewBox.width),
          y:
            activeState.viewport.pan.y +
            focusedPoint[1] -
            (nextViewBox.y + focusY * nextViewBox.height),
        },
      },
    });
  };

  return (
    <section
      className={styles.workbench}
      aria-label="Visible-card review workbench"
      data-viewpoint={activeState.viewpoint}
      data-read-only={readOnly}
    >
      <WorkbenchCommandBar
        state={activeState}
        availability={availability}
        readOnly={readOnly}
        enabledEditTools={
          enabledEditTools ?? ["visible_regions", "virtual_cards", "mapping"]
        }
        selectedCandidateIds={selectedCandidateIds}
        editor={editor}
        canCopyIgnoreRegions={canCopyIgnoreRegions}
        canRestoreSuggestion={canRestoreSuggestion}
        scene={scene}
        onCardDecision={onCardDecision}
        onResolveRemaining={onResolveRemaining}
        onToggleViewpoint={() => dispatch({ type: "toggle_viewpoint" })}
        onToggleLayer={(layer) => dispatch({ type: "toggle_layer", layer })}
        onSelectTool={(tool) => {
          dispatch({ type: "select_tool", tool });
          onToolChange?.(tool);
        }}
        onAction={(action) => {
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
              if (nextSelection === undefined)
                dispatch({ type: "clear_selection" });
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
          onAction?.(action, activeState.selection);
        }}
        onSceneAction={applySceneAction}
      />
      <div className={styles.workbenchSurfaceLayout}>
        <WorkbenchSurface
          frame={frame}
          scene={scene}
          sourceUrl={sourceUrl}
          width={width}
          height={height}
          viewpoint={activeState.viewpoint}
          enabledLayers={activeState.enabledLayers}
          selection={activeState.selection}
          viewport={activeState.viewport}
          candidateProjection={candidateProjection}
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
        />
        {proposalSlot !== undefined ? (
          <WorkbenchProposalColumn
            frame={frame}
            readOnly={readOnly}
            selection={activeState.selection}
            editor={editor}
            selectedCandidateIds={selectedCandidateIds}
            onToggleCandidateSelection={onToggleCandidateSelection}
            onSelectCandidate={(candidate) => {
              select({ type: "visible_card", id: candidate.card_id });
              onOpenEditor?.(candidate);
            }}
            onOpenEditor={onOpenEditor}
            onRemoveCard={onRemoveCard}
            onOpenIgnoreRegion={onOpenIgnoreRegion}
            onRemoveIgnoreRegion={onRemoveIgnoreRegion}
            proposalSlot={proposalSlot}
          />
        ) : null}
      </div>
      {editor !== null && !readOnly ? (
        <WorkbenchEditorControls
          editor={editor}
          editorError={editorError}
          onSelectEditorPolygon={onSelectEditorPolygon}
          onCancelEditor={onCancelEditor}
        />
      ) : null}
    </section>
  );
}

function WorkbenchCommandBar({
  state,
  availability,
  readOnly,
  enabledEditTools,
  selectedCandidateIds,
  editor,
  canCopyIgnoreRegions,
  canRestoreSuggestion,
  scene,
  onCardDecision,
  onResolveRemaining,
  onSceneAction,
  onToggleViewpoint,
  onToggleLayer,
  onSelectTool,
  onAction,
}: {
  state: VisibleCardReviewWorkbenchState;
  availability: ReturnType<typeof getWorkbenchAvailability>;
  readOnly: boolean;
  enabledEditTools: readonly WorkbenchPreferences["activeTool"][];
  selectedCandidateIds: string[];
  editor: EditorState | null;
  canCopyIgnoreRegions: boolean;
  canRestoreSuggestion: boolean;
  scene: PoseSceneEnvelope | null;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  onToggleViewpoint: () => void;
  onToggleLayer: (layer: WorkbenchLayer) => void;
  onSelectTool: (tool: WorkbenchPreferences["activeTool"]) => void;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
}) {
  const nextViewpoint = state.viewpoint === "camera" ? "rectified" : "camera";
  const viewpointAvailability = availability.viewpoints[nextViewpoint];
  const viewpointLabel = `Viewpoint: ${VIEWPOINT_LABELS[state.viewpoint]}. Switch to ${VIEWPOINT_LABELS[nextViewpoint]}`;
  return (
    <div
      className={styles.workbenchCommandBar}
      aria-label="Workbench command bar"
    >
      <div className={styles.workbenchCommandGroup} aria-label="View">
        <span className={styles.workbenchCommandLabel}>View</span>
        <button
          type="button"
          className={styles.workbenchToggle}
          aria-label={viewpointLabel}
          title={viewpointAvailability.disabledReason ?? undefined}
          disabled={!viewpointAvailability.available}
          onClick={onToggleViewpoint}
        >
          {VIEWPOINT_LABELS[state.viewpoint]}
        </button>
      </div>
      <div className={styles.workbenchCommandGroup} aria-label="Show">
        <span className={styles.workbenchCommandLabel}>Show</span>
        {WORKBENCH_LAYERS.map((layer) => {
          const layerAvailability = availability.layers[layer];
          return (
            <button
              key={layer}
              type="button"
              className={styles.workbenchToggle}
              aria-label={LAYER_LABELS[layer]}
              aria-pressed={state.enabledLayers.includes(layer)}
              title={layerAvailability.disabledReason ?? undefined}
              disabled={!layerAvailability.available}
              onClick={() => onToggleLayer(layer)}
            >
              {LAYER_LABELS[layer]}
            </button>
          );
        })}
      </div>
      <div className={styles.workbenchCommandGroup} aria-label="Edit">
        <span className={styles.workbenchCommandLabel}>Edit</span>
        {(["visible_regions", "virtual_cards", "mapping"] as const).map(
          (tool) => {
            const toolAvailability = availability.tools[tool];
            const enabledInPhase = enabledEditTools.includes(tool);
            const disabledReason = readOnly
              ? toolAvailability.mutationDisabledReason
              : enabledInPhase
                ? null
                : LATER_EDIT_REASON;
            return (
              <button
                key={tool}
                type="button"
                className={styles.workbenchToggle}
                aria-pressed={state.activeTool === tool}
                aria-label={`Edit ${LAYER_LABELS[tool]}`}
                title={
                  (toolAvailability.available
                    ? disabledReason
                    : toolAvailability.disabledReason) ?? undefined
                }
                disabled={
                  !toolAvailability.available || disabledReason !== null
                }
                onClick={() => onSelectTool(tool)}
              >
                {tool === "mapping" ? "Mapping" : LAYER_LABELS[tool]}
              </button>
            );
          },
        )}
      </div>
      {state.activeTool === "visible_regions" ? (
        <VisibleRegionSelectionActions
          readOnly={readOnly}
          sourceAvailable={availability.viewpoints.camera.available}
          selectedCandidateCount={selectedCandidateIds.length}
          editor={editor}
          selection={state.selection}
          canCopyIgnoreRegions={canCopyIgnoreRegions}
          canRestoreSuggestion={canRestoreSuggestion}
          onAction={onAction}
        />
      ) : null}
      {state.activeTool === "virtual_cards" ? (
        <VirtualCardSelectionActions
          readOnly={readOnly}
          scene={scene}
          selection={state.selection}
          onAction={onAction}
          onCardDecision={onCardDecision}
          onResolveRemaining={onResolveRemaining}
          onSceneAction={onSceneAction}
        />
      ) : null}
    </div>
  );
}

function VirtualCardSelectionActions({
  readOnly,
  scene,
  selection,
  onAction,
  onCardDecision,
  onResolveRemaining,
  onSceneAction,
}: {
  readOnly: boolean;
  scene: PoseSceneEnvelope | null;
  selection: WorkbenchSelection | null;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
}) {
  const selectedPose =
    scene === null ? null : selectedPoseForSelection(scene, selection);
  const selectedReviewState =
    scene?.card_review_states?.find(
      (state) => state.card_id === selectedPose?.card_id,
    ) ?? null;
  const pendingCount =
    scene?.card_review_states?.filter((state) => state.state === "pending")
      .length ?? 0;
  const selectedCardId = selectedPose?.card_id ?? null;
  const sceneAvailable = scene !== null;
  const cardTarget = selectedCardId ?? "selected card";
  const actionButton = (
    action: VirtualCardWorkbenchAction,
    label: string,
    disabled: boolean,
    reason: string,
  ) => (
    <button
      key={action}
      type="button"
      className={styles.workbenchToggle}
      disabled={disabled}
      title={disabled ? reason : undefined}
      onClick={() => {
        if (
          (action === "accept_card" || action === "reject_card") &&
          selectedCardId !== null &&
          onCardDecision !== undefined
        ) {
          onCardDecision?.(
            selectedCardId,
            action === "accept_card" ? "accept" : "reject",
          );
        } else if (
          action === "accept_remaining_cards" &&
          onResolveRemaining !== undefined
        ) {
          onResolveRemaining();
        } else {
          onAction(action);
        }
      }}
    >
      {label}
    </button>
  );
  return (
    <div
      className={styles.workbenchCommandGroup}
      aria-label="Selection actions"
    >
      <span className={styles.workbenchCommandLabel}>Selection actions</span>
      {actionButton(
        "add_virtual_card",
        "Add virtual card",
        readOnly || !sceneAvailable,
        readOnly
          ? "Generated visible-card results are read-only."
          : "A proposed card scene is required to add a virtual card.",
      )}
      {actionButton(
        "accept_card",
        selectedCardId === null ? "Accept card" : `Accept card ${cardTarget}`,
        readOnly ||
          selectedCardId === null ||
          selectedReviewState === null ||
          selectedReviewState.state === "accepted",
        selectedCardId === null
          ? "Select a virtual card first."
          : selectedReviewState === null
            ? "This card has no review decision state."
            : "The selected card is already accepted.",
      )}
      {actionButton(
        "reject_card",
        selectedCardId === null ? "Reject card" : `Reject card ${cardTarget}`,
        readOnly ||
          selectedCardId === null ||
          selectedReviewState === null ||
          selectedReviewState.state === "rejected",
        selectedCardId === null
          ? "Select a virtual card first."
          : selectedReviewState === null
            ? "This card has no review decision state."
            : "The selected card is already rejected.",
      )}
      {actionButton(
        "accept_remaining_cards",
        "Accept remaining cards",
        readOnly || pendingCount === 0 || onResolveRemaining === undefined,
        pendingCount === 0
          ? "No pending card decisions remain."
          : "All pending cards must be resolved through the maintained reference.",
      )}
      {actionButton(
        "remove_card",
        selectedCardId === null ? "Remove card" : `Remove card ${cardTarget}`,
        readOnly || selectedPose === null || scene?.scene.poses.length === 1,
        selectedPose === null
          ? "Select a virtual card first."
          : scene?.scene.poses.length === 1
            ? "A card scene must keep one virtual card."
            : "",
      )}
      {actionButton(
        "bring_forward",
        selectedCardId === null
          ? "Bring card forward"
          : `Bring card ${cardTarget} forward`,
        readOnly || selectedPose === null,
        "Select a virtual card first.",
      )}
      {actionButton(
        "send_backward",
        selectedCardId === null
          ? "Send card backward"
          : `Send card ${cardTarget} backward`,
        readOnly || selectedPose === null,
        "Select a virtual card first.",
      )}
      {actionButton(
        "restore_proposed_scene",
        "Restore proposed scene",
        readOnly || !sceneAvailable,
        readOnly
          ? "Generated visible-card results are read-only."
          : "A proposed card scene is required to restore the scene.",
      )}
      {selectedPose !== null ? (
        <label className={styles.workbenchNumericField}>
          <span>Rotation {selectedPose.card_id}</span>
          <input
            aria-label={`Rotation for card ${selectedPose.card_id}`}
            type="number"
            step="1"
            defaultValue={selectedPose.rotation_degrees}
            disabled={readOnly}
            onBlur={(event) => {
              const value = Number(event.target.value);
              if (!Number.isFinite(value) || scene === null) return;
              onSceneAction(
                {
                  type: "rotate",
                  cardId: selectedPose.card_id,
                  rotationDegrees: value,
                },
                "Card angle saved.",
              );
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }
            }}
          />
        </label>
      ) : null}
    </div>
  );
}

function selectedPoseForSelection(
  scene: PoseSceneEnvelope,
  selection: WorkbenchSelection | null,
): PoseCard | null {
  if (selection?.type !== "virtual_card") return null;
  return (
    scene.scene.poses.find((pose) => pose.card_id === selection.id) ?? null
  );
}

function VisibleRegionSelectionActions({
  readOnly,
  sourceAvailable,
  selectedCandidateCount,
  editor,
  selection,
  canCopyIgnoreRegions,
  canRestoreSuggestion,
  onAction,
}: {
  readOnly: boolean;
  sourceAvailable: boolean;
  selectedCandidateCount: number;
  editor: EditorState | null;
  selection: WorkbenchSelection | null;
  canCopyIgnoreRegions: boolean;
  canRestoreSuggestion: boolean;
  onAction: (action: VisibleRegionWorkbenchAction) => void;
}) {
  const actions: Array<{
    action: VisibleRegionWorkbenchAction;
    label: string;
    disabled: boolean;
    reason: string;
  }> = [
    {
      action: "add_visible_card",
      label: "Add visible card",
      disabled: readOnly || !sourceAvailable,
      reason: readOnly
        ? "Generated visible-card results are read-only."
        : "A resolved source frame is required to add a visible card.",
    },
    {
      action: "add_polygon",
      label: "Add polygon",
      disabled: readOnly || editor === null || editor.cardId === null,
      reason: "Select a visible card before adding a polygon.",
    },
    {
      action: "remove_polygon",
      label: "Remove polygon",
      disabled: readOnly || editor === null || editor.polygons.length <= 1,
      reason: "A visible card must keep one polygon.",
    },
    {
      action: "draw_ignore_region",
      label: "Draw ignore region",
      disabled: readOnly || !sourceAvailable,
      reason: "A resolved source frame is required to draw an ignore region.",
    },
    {
      action: "convert_to_ignore_region",
      label: "Convert selection to ignore region",
      disabled: readOnly || selectedCandidateCount === 0,
      reason:
        "Select one or more proposals to convert them to an ignore region.",
    },
    {
      action: "copy_ignore_regions",
      label: "Copy ignore regions",
      disabled: readOnly || !canCopyIgnoreRegions,
      reason: "Review an earlier frame with ignore regions first.",
    },
    {
      action: "delete_selection",
      label: "Delete selection",
      disabled:
        readOnly ||
        selection === null ||
        (selection.type !== "visible_card" &&
          selection.type !== "polygon" &&
          selection.type !== "ignore_region"),
      reason: "Select a visible card or ignore region first.",
    },
    {
      action: "restore_suggestion",
      label: "Restore suggestion",
      disabled: readOnly || !canRestoreSuggestion,
      reason: "A generated suggestion is required to restore this frame.",
    },
  ];
  return (
    <div
      className={styles.workbenchCommandGroup}
      aria-label="Selection actions"
    >
      <span className={styles.workbenchCommandLabel}>Selection actions</span>
      {actions.map(({ action, label, disabled, reason }) => (
        <button
          key={action}
          type="button"
          className={styles.workbenchToggle}
          disabled={disabled}
          title={disabled ? reason : undefined}
          aria-label={
            action === "draw_ignore_region"
              ? "Draw ignore region in shared workbench"
              : undefined
          }
          onClick={() => onAction(action)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function WorkbenchEditorControls({
  editor,
  editorError,
  onSelectEditorPolygon,
  onCancelEditor,
}: {
  editor: EditorState;
  editorError: string | null;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onCancelEditor?: () => void;
}) {
  return (
    <section
      className={styles.workbenchEditor}
      aria-label="Visible region editor"
    >
      <p className={styles.workbenchEditorHelp}>
        Drag a point to adjust a region. Click an edge to add a point. Changes
        save through the maintained-reference command queue.
      </p>
      <div
        className={styles.workbenchPolygonActions}
        aria-label="Visible region polygons"
      >
        {editor.polygons.map((polygon, polygonIndex) => (
          <button
            className={styles.workbenchToggle}
            type="button"
            key={`polygon-${polygonIndex}`}
            aria-pressed={editor.polygonIndex === polygonIndex}
            onClick={() => onSelectEditorPolygon?.(polygonIndex)}
          >
            Polygon {polygonIndex + 1} ({polygon.length} point
            {polygon.length === 1 ? "" : "s"})
          </button>
        ))}
        <button
          className={styles.workbenchToggle}
          type="button"
          onClick={onCancelEditor}
        >
          Close editor Esc
        </button>
      </div>
      {editorError !== null ? (
        <p className={styles.workbenchEditorError}>{editorError}</p>
      ) : null}
    </section>
  );
}

function WorkbenchProposalColumn({
  frame,
  readOnly,
  selection,
  editor,
  selectedCandidateIds,
  onToggleCandidateSelection,
  onSelectCandidate,
  onOpenEditor,
  onRemoveCard,
  onOpenIgnoreRegion,
  onRemoveIgnoreRegion,
  proposalSlot,
}: {
  frame: EditableFrame;
  readOnly: boolean;
  selection: WorkbenchSelection | null;
  editor: EditorState | null;
  selectedCandidateIds: string[];
  onToggleCandidateSelection?: (cardId: string) => void;
  onSelectCandidate: (candidate: Candidate) => void;
  onOpenEditor?: (candidate: Candidate | null, polygonIndex?: number) => void;
  onRemoveCard?: (cardId: string) => void;
  onOpenIgnoreRegion?: (region: IgnoreRegion | null) => void;
  onRemoveIgnoreRegion?: (regionId: string) => void;
  proposalSlot: HTMLElement | null;
}) {
  const content = (
    <section
      className={styles.proposalColumn}
      aria-label="Visible-card proposals"
    >
      {frame.outcome.candidates.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No proposals. Add a visible card or review this frame as empty.
        </p>
      ) : (
        <ol className={styles.proposalItems}>
          {frame.outcome.candidates.map((candidate, index) => (
            <li key={candidate.card_id}>
              <div className={styles.proposalRow}>
                {!readOnly ? (
                  <label className={styles.proposalCheckbox}>
                    <input
                      type="checkbox"
                      aria-label={`Select proposal ${index + 1} for ignore region`}
                      checked={selectedCandidateIds.includes(candidate.card_id)}
                      onChange={() =>
                        onToggleCandidateSelection?.(candidate.card_id)
                      }
                    />
                    <span className={styles.visuallyHidden}>
                      Select for ignore region
                    </span>
                  </label>
                ) : null}
                <button
                  className={styles.proposalSelect}
                  type="button"
                  aria-label={`Select proposal ${index + 1}`}
                  aria-pressed={
                    (selection?.id === candidate.card_id &&
                      (selection.type === "visible_card" ||
                        selection.type === "polygon")) ||
                    editor?.cardId === candidate.card_id
                  }
                  onClick={() => onSelectCandidate(candidate)}
                >
                  <strong>Proposal {index + 1}</strong>
                  <span>Detector suggestion</span>
                  <small>
                    {candidate.geometry.visible_region !== undefined
                      ? "Polygon"
                      : candidate.geometry.box_2d !== undefined
                        ? "Box"
                        : candidate.geometry.kind}
                  </small>
                </button>
                {!readOnly ? (
                  <div className={styles.actionButtons}>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => {
                        onSelectCandidate(candidate);
                        onOpenEditor?.(candidate);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      className={styles.inlineAction}
                      type="button"
                      onClick={() => onRemoveCard?.(candidate.card_id)}
                    >
                      Remove
                    </button>
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
      {frame.outcome.ignored_regions.length > 0 ? (
        <section
          className={styles.ignoreRegionList}
          aria-label="Visible-card ignore regions"
        >
          <p className={styles.statusLabel}>Ignore regions</p>
          <ol className={styles.proposalItems}>
            {frame.outcome.ignored_regions.map((region, index) => (
              <li key={region.region_id}>
                <div className={styles.ignoreRegionRow}>
                  <span
                    className={styles.ignoreRegionSwatch}
                    aria-hidden="true"
                  />
                  <span className={styles.proposalDetails}>
                    <strong>Ignore region {index + 1}</strong>
                    <span>Untidy stack</span>
                  </span>
                  {!readOnly ? (
                    <div className={styles.actionButtons}>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() => onOpenIgnoreRegion?.(region)}
                      >
                        Edit
                      </button>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() => onRemoveIgnoreRegion?.(region.region_id)}
                      >
                        Delete
                      </button>
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
  return proposalSlot === null ? content : createPortal(content, proposalSlot);
}

function WorkbenchSurface({
  frame,
  scene,
  sourceUrl,
  width,
  height,
  viewpoint,
  enabledLayers,
  selection,
  viewport,
  candidateProjection,
  editor,
  includeIgnoreRegionCount,
  onSelect,
  onKeyDown,
  onPointPointerDown,
  onCanvasPointerDown,
  onPointerMove,
  onPointerLeave,
  onPointerUp,
  onPointerCancel,
  onWheel,
  onDeleteSelectedPoint,
  onVirtualCardPointerDown,
  onVirtualCardKeyDown,
}: {
  frame: EditableFrame;
  scene: PoseSceneEnvelope | null;
  sourceUrl: string | null;
  width: number;
  height: number;
  viewpoint: WorkbenchViewpoint;
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  viewport: { zoom: number; pan: { x: number; y: number } };
  candidateProjection: CardSceneProjection | null;
  editor: EditorState | null;
  includeIgnoreRegionCount: boolean;
  onSelect: (selection: WorkbenchSelection) => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
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
  onWheel?: (event: ReactWheelEvent<SVGSVGElement>) => void;
  onDeleteSelectedPoint?: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
  onVirtualCardPointerDown?: (
    event: ReactPointerEvent<SVGElement>,
    cardId: string,
    kind: "move" | "rotate",
  ) => void;
  onVirtualCardKeyDown?: (
    event: ReactKeyboardEvent<SVGPolygonElement>,
    cardId: string,
  ) => void;
}) {
  const count = frame.outcome.candidates.length;
  const proposalLabel = `${count} visible-card proposal${count === 1 ? "" : "s"}${includeIgnoreRegionCount && frame.outcome.ignored_regions.length > 0 ? ` and ${frame.outcome.ignored_regions.length} ignore region${frame.outcome.ignored_regions.length === 1 ? "" : "s"}` : ""}`;
  if (viewpoint === "rectified" && scene !== null) {
    const viewBox = tableViewBox(scene.scene, scene.projection, viewport);
    return (
      <svg
        className={styles.workbenchRectifiedSurface}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        role="img"
        aria-label={`Rectified visible-card workbench with ${proposalLabel}`}
        tabIndex={0}
        onKeyDown={(event) => {
          onKeyDown(event);
          onDeleteSelectedPoint?.(event);
        }}
        onPointerDown={(event) =>
          onCanvasPointerDown?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerMove={(event) =>
          onPointerMove?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerLeave={(event) =>
          onPointerLeave?.(
            event,
            sourcePointFromEvent(
              event,
              "rectified",
              viewBox,
              width,
              height,
              scene,
            ),
          )
        }
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onWheel={onWheel}
      >
        {sourceUrl !== null ? (
          <RectifiedSourceFrame
            sourceUrl={sourceUrl}
            width={width}
            height={height}
            homography={scene.projection.table_to_image_homography}
            clipPrefix={`workbench-${frame.itemId}-background`}
          />
        ) : null}
        {renderLayers({
          frame,
          scene,
          viewpoint,
          width,
          height,
          enabledLayers,
          selection,
          candidateProjection,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
        })}
        {renderEditorOverlay({
          editor,
          viewpoint,
          width,
          height,
          scene,
          onPointPointerDown,
        })}
      </svg>
    );
  }
  return (
    <div
      className={styles.workbenchCameraViewport}
      style={{
        aspectRatio: `${width} / ${height}`,
        maxWidth: `min(100%, 2000px, calc(80vh * ${width / height}))`,
      }}
    >
      {sourceUrl !== null ? (
        <img
          className={styles.workbenchCameraImage}
          src={sourceUrl}
          width={width}
          height={height}
          alt="Selected visible-card source frame"
        />
      ) : null}
      <svg
        className={styles.workbenchCameraSurface}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={proposalLabel}
        tabIndex={0}
        onKeyDown={(event) => {
          onKeyDown(event);
          onDeleteSelectedPoint?.(event);
        }}
        onPointerDown={(event) =>
          onCanvasPointerDown?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              { x: 0, y: 0, width, height },
              width,
              height,
              scene,
            ),
          )
        }
        onPointerMove={(event) =>
          onPointerMove?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              { x: 0, y: 0, width, height },
              width,
              height,
              scene,
            ),
          )
        }
        onPointerLeave={(event) =>
          onPointerLeave?.(
            event,
            sourcePointFromEvent(
              event,
              "camera",
              { x: 0, y: 0, width, height },
              width,
              height,
              scene,
            ),
          )
        }
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
      >
        {renderLayers({
          frame,
          scene,
          viewpoint: "camera",
          width,
          height,
          enabledLayers,
          selection,
          candidateProjection,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
        })}
        {renderEditorOverlay({
          editor,
          viewpoint: "camera",
          width,
          height,
          scene,
          onPointPointerDown,
        })}
      </svg>
    </div>
  );
}

type LayerRenderContext = {
  frame: EditableFrame;
  scene: PoseSceneEnvelope | null;
  viewpoint: WorkbenchViewpoint;
  width: number;
  height: number;
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  candidateProjection: CardSceneProjection | null;
  onSelect: (selection: WorkbenchSelection) => void;
  onVirtualCardPointerDown?: (
    event: ReactPointerEvent<SVGElement>,
    cardId: string,
    kind: "move" | "rotate",
  ) => void;
  onVirtualCardKeyDown?: (
    event: ReactKeyboardEvent<SVGPolygonElement>,
    cardId: string,
  ) => void;
};

function renderEditorOverlay({
  editor,
  viewpoint,
  width,
  height,
  scene,
  onPointPointerDown,
}: {
  editor: EditorState | null;
  viewpoint: WorkbenchViewpoint;
  width: number;
  height: number;
  scene: PoseSceneEnvelope | null;
  onPointPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    polygonIndex: number,
    pointIndex: number,
  ) => void;
}) {
  if (editor === null) return null;
  return (
    <g data-workbench-editor="visible-regions">
      {editor.polygons.map((polygon, polygonIndex) => {
        const points = polygon
          .map((point) => editorPoint(point, viewpoint, width, height, scene))
          .filter((point): point is [number, number] => point !== null);
        return (
          <g key={`editor-${polygonIndex}`}>
            {points.length >= 2 ? (
              <polygon
                points={pointsAttribute(points)}
                fill={
                  editor.polygonIndex === polygonIndex
                    ? "rgba(255, 210, 79, 0.25)"
                    : "rgba(255, 210, 79, 0.12)"
                }
                stroke={
                  editor.polygonIndex === polygonIndex ? "#ffd24f" : "#c79f34"
                }
                strokeDasharray="4 3"
                strokeWidth={strokeWidth(viewpoint, width)}
                pointerEvents="none"
              />
            ) : null}
            {polygon.map((point, pointIndex) => {
              const displayPoint = editorPoint(
                point,
                viewpoint,
                width,
                height,
                scene,
              );
              if (displayPoint === null) return null;
              const [x, y] = displayPoint;
              return (
                <circle
                  key={`${point.x}:${point.y}:${pointIndex}`}
                  cx={x}
                  cy={y}
                  r={viewpoint === "camera" ? Math.max(1, width / 160) : 0.1}
                  fill={
                    editor.polygonIndex === polygonIndex &&
                    editor.selectedPointIndex === pointIndex
                      ? "#ffffff"
                      : "#ffd24f"
                  }
                  stroke="#ffd24f"
                  strokeWidth={strokeWidth(viewpoint, width) / 2}
                  tabIndex={0}
                  role="button"
                  aria-label={`Polygon ${polygonIndex + 1}, point ${pointIndex + 1} at ${point.x}, ${point.y}`}
                  onPointerDown={(event) =>
                    onPointPointerDown?.(event, polygonIndex, pointIndex)
                  }
                  onClick={(event) => event.stopPropagation()}
                />
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

function editorPoint(
  point: Point,
  viewpoint: WorkbenchViewpoint,
  width: number,
  height: number,
  scene: PoseSceneEnvelope | null,
): [number, number] | null {
  const source = sourcePoint(point, width, height);
  if (viewpoint === "camera" || scene === null) return source;
  const projected = projectImagePointToTable(
    source,
    scene.projection.table_to_image_homography,
  );
  return projected === null ? null : projected;
}

function sourcePointFromEvent(
  event: ReactPointerEvent<SVGSVGElement>,
  viewpoint: WorkbenchViewpoint,
  viewBox: { x: number; y: number; width: number; height: number },
  width: number,
  height: number,
  scene: PoseSceneEnvelope | null,
): Point | null {
  const rect = event.currentTarget.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  const displayX =
    viewBox.x + ((event.clientX - rect.left) / rect.width) * viewBox.width;
  const displayY =
    viewBox.y + ((event.clientY - rect.top) / rect.height) * viewBox.height;
  if (viewpoint === "camera" || scene === null) {
    return {
      x: clamp((displayX / width) * 1000, 1000),
      y: clamp((displayY / height) * 1000, 1000),
    };
  }
  const source = projectTablePoint(
    [displayX, displayY],
    scene.projection.table_to_image_homography,
  );
  return source === null
    ? null
    : {
        x: clamp((source[0] / width) * 1000, 1000),
        y: clamp((source[1] / height) * 1000, 1000),
      };
}

function sourcePointToTablePoint(
  point: Point,
  width: number,
  height: number,
  scene: PoseSceneEnvelope,
): TablePoint | null {
  return projectImagePointToTable(
    sourcePoint(point, width, height),
    scene.projection.table_to_image_homography,
  );
}

function clamp(value: number, maximum: number): number {
  return Math.min(Math.max(value, 0), maximum);
}

type LayerRenderer = {
  layer: WorkbenchLayer;
  render: (context: LayerRenderContext) => ReactNode;
};

const LAYER_REGISTRY: readonly LayerRenderer[] = [
  { layer: "mapping", render: renderMappingLayer },
  { layer: "ignore_regions", render: renderIgnoreLayer },
  { layer: "suggestions", render: renderSuggestionLayer },
  { layer: "virtual_cards", render: renderVirtualCardLayer },
  { layer: "visible_regions", render: renderVisibleRegionLayer },
];

export const WORKBENCH_LAYER_REGISTRY = LAYER_REGISTRY;

function renderLayers(context: LayerRenderContext) {
  const registry = new Map(LAYER_REGISTRY.map((entry) => [entry.layer, entry]));
  return WORKBENCH_LAYER_DRAW_ORDER.filter((layer) =>
    context.enabledLayers.includes(layer),
  ).map((layer) => {
    const entry = registry.get(layer);
    return entry === undefined ? null : (
      <g key={layer} data-workbench-layer={layer}>
        {entry.render(context)}
      </g>
    );
  });
}

function renderVisibleRegionLayer({
  frame,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return frame.outcome.candidates.flatMap((candidate) =>
    candidatePolygons(candidate, width, height, viewpoint, scene).map(
      (polygon, polygonIndex) => (
        <polygon
          key={`${candidate.card_id}-visible-${polygonIndex}`}
          points={pointsAttribute(polygon)}
          fill="rgba(59, 205, 180, 0.2)"
          stroke={
            isSelected(selection, {
              type: "visible_card",
              id: candidate.card_id,
            })
              ? "#ffd24f"
              : "#30c9ac"
          }
          strokeWidth={strokeWidth(viewpoint, width)}
          data-card-id={candidate.card_id}
          data-polygon-index={polygonIndex}
          role="button"
          tabIndex={0}
          aria-label={`Edit ${candidate.card_id}, polygon ${polygonIndex + 1}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({
              type: "polygon",
              id: candidate.card_id,
              polygonIndex,
            });
          }}
        />
      ),
    ),
  );
}

function renderSuggestionLayer({
  frame,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return frame.outcome.candidates.flatMap((candidate) =>
    candidatePolygons(candidate, width, height, viewpoint, scene).map(
      (polygon, polygonIndex) => (
        <path
          key={`${candidate.card_id}-suggestion-${polygonIndex}`}
          d={pathAttribute(polygon)}
          fill="none"
          stroke={
            isSelected(selection, {
              type: "visible_card",
              id: candidate.card_id,
            })
              ? "#ffffff"
              : "#a7aebc"
          }
          strokeDasharray="5 5"
          strokeWidth={strokeWidth(viewpoint, width)}
          data-card-id={candidate.card_id}
          data-suggestion="true"
          role="button"
          tabIndex={0}
          aria-label={`Select detector suggestion ${candidate.card_id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "visible_card", id: candidate.card_id });
          }}
        />
      ),
    ),
  );
}

function renderIgnoreLayer({
  frame,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return frame.outcome.ignored_regions.flatMap((region) =>
    region.geometry.polygons.map((polygon, polygonIndex) => {
      const points = transformSourcePolygon(
        polygon,
        width,
        height,
        viewpoint,
        scene,
      );
      return (
        <polygon
          key={`${region.region_id}-${polygonIndex}`}
          points={pointsAttribute(points)}
          fill="rgba(255, 170, 96, 0.22)"
          stroke={
            isSelected(selection, {
              type: "ignore_region",
              id: region.region_id,
            })
              ? "#ffffff"
              : "#f0a35b"
          }
          strokeDasharray="3 3"
          strokeWidth={strokeWidth(viewpoint, width)}
          data-ignore-region-id={region.region_id}
          role="button"
          tabIndex={0}
          aria-label={`Select ignore region ${region.region_id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "ignore_region", id: region.region_id });
          }}
        />
      );
    }),
  );
}

function renderVirtualCardLayer({
  scene,
  viewpoint,
  width,
  selection,
  onSelect,
  onVirtualCardPointerDown,
  onVirtualCardKeyDown,
}: LayerRenderContext) {
  if (scene === null) return null;
  return renderOrder(scene.scene, selection).map((pose) => {
    const polygon = posePolygon(pose, scene.projection, viewpoint);
    const selected = isSelected(selection, {
      type: "virtual_card",
      id: pose.card_id,
    });
    const handle = rotationHandle(pose, scene.projection, viewpoint);
    return (
      <g key={pose.card_id}>
        <polygon
          points={pointsAttribute(polygon)}
          fill="rgba(55, 96, 106, 0.55)"
          stroke={selected ? "#d9fff7" : "#80b6b7"}
          strokeWidth={strokeWidth(viewpoint, width, selected)}
          data-card-id={pose.card_id}
          data-stacking-index={scene.scene.stacking_order.card_ids.indexOf(
            pose.card_id,
          )}
          role="button"
          tabIndex={0}
          aria-label={`Select virtual card ${pose.card_id}`}
          onKeyDown={(event) => onVirtualCardKeyDown?.(event, pose.card_id)}
          onPointerDown={(event) =>
            onVirtualCardPointerDown?.(event, pose.card_id, "move")
          }
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "virtual_card", id: pose.card_id });
          }}
        />
        {selected ? (
          <circle
            cx={handle[0]}
            cy={handle[1]}
            r={viewpoint === "camera" ? Math.max(3, width / 120) : 0.11}
            fill="#ffd24f"
            stroke="#18242f"
            strokeWidth={strokeWidth(viewpoint, width) / 2}
            role="button"
            tabIndex={0}
            aria-label={`Rotate card ${pose.card_id}`}
            onPointerDown={(event) =>
              onVirtualCardPointerDown?.(event, pose.card_id, "rotate")
            }
            onClick={(event) => event.stopPropagation()}
          />
        ) : null}
      </g>
    );
  });
}

function renderMappingLayer({
  scene,
  viewpoint,
  candidateProjection,
  width,
  selection,
  onSelect,
}: LayerRenderContext) {
  if (scene === null) return null;
  const currentProjection = scene.projection;
  const current = scene.scene.poses.map((pose) => (
    <MappingProjection
      key={`${pose.card_id}-current`}
      pose={pose}
      projection={currentProjection}
      viewpoint={viewpoint}
      width={width}
      stroke="#ff8a65"
      dataProjection="current"
      selection={selection}
      onSelect={onSelect}
    />
  ));
  const candidate =
    candidateProjection === null
      ? null
      : scene.scene.poses.map((pose) => (
          <MappingProjection
            key={`${pose.card_id}-candidate`}
            pose={pose}
            projection={candidateProjection}
            viewpoint={viewpoint}
            width={width}
            stroke="#ffd166"
            dataProjection="candidate"
            selection={selection}
            onSelect={onSelect}
          />
        ));
  return (
    <>
      {current}
      {candidate}
    </>
  );
}

function MappingProjection({
  pose,
  projection,
  viewpoint,
  width,
  stroke,
  dataProjection,
  selection,
  onSelect,
}: {
  pose: PoseCard;
  projection: CardSceneProjection;
  viewpoint: WorkbenchViewpoint;
  width: number;
  stroke: string;
  dataProjection: "current" | "candidate";
  selection: WorkbenchSelection | null;
  onSelect: (selection: WorkbenchSelection) => void;
}) {
  const polygon = posePolygon(pose, projection, viewpoint);
  const selected = isSelected(selection, {
    type: "calibration_anchor",
    id: pose.card_id,
  });
  return (
    <g data-projection={dataProjection} data-card-id={pose.card_id}>
      <polygon
        points={pointsAttribute(polygon)}
        fill="none"
        stroke={stroke}
        strokeDasharray="8 5"
        strokeWidth={strokeWidth(viewpoint, width)}
        pointerEvents="none"
      />
      {polygon.map(([x, y], index) => (
        <circle
          key={`${pose.card_id}-${dataProjection}-${index}`}
          cx={x}
          cy={y}
          r={viewpoint === "camera" ? Math.max(3, width / 120) : 0.08}
          fill={selected ? "#ffffff" : stroke}
          stroke="#18242f"
          strokeWidth={strokeWidth(viewpoint, width) / 2}
          data-mapping-anchor={index}
          role="button"
          tabIndex={0}
          aria-label={`Select calibration anchor ${index + 1} for ${pose.card_id}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "calibration_anchor", id: pose.card_id });
          }}
        />
      ))}
    </g>
  );
}

function candidatePolygons(
  candidate: Candidate,
  width: number,
  height: number,
  viewpoint: WorkbenchViewpoint,
  scene: PoseSceneEnvelope | null,
): Array<Array<[number, number]>> {
  const sourcePolygons = sourceCandidatePolygons(candidate, width, height);
  if (viewpoint === "camera" || scene === null) return sourcePolygons;
  return sourcePolygons
    .map((polygon) =>
      polygon
        .map((point) =>
          projectImagePointToTable(
            point,
            scene.projection.table_to_image_homography,
          ),
        )
        .filter((point): point is TablePoint => point !== null),
    )
    .filter((polygon) => polygon.length >= 3);
}

function sourceCandidatePolygons(
  candidate: Candidate,
  width: number,
  height: number,
): Array<Array<[number, number]>> {
  if (candidate.geometry.visible_region !== undefined) {
    return candidate.geometry.visible_region.polygons.map((polygon) =>
      polygon.map((point) => sourcePoint(point, width, height)),
    );
  }
  const box = candidate.geometry.box_2d;
  return box === undefined
    ? []
    : [
        [
          sourcePoint({ x: box.x_min, y: box.y_min }, width, height),
          sourcePoint({ x: box.x_max, y: box.y_min }, width, height),
          sourcePoint({ x: box.x_max, y: box.y_max }, width, height),
          sourcePoint({ x: box.x_min, y: box.y_max }, width, height),
        ],
      ];
}

function transformSourcePolygon(
  polygon: Point[],
  width: number,
  height: number,
  viewpoint: WorkbenchViewpoint,
  scene: PoseSceneEnvelope | null,
): Array<[number, number]> {
  const source = polygon.map((point) => sourcePoint(point, width, height));
  if (viewpoint === "camera" || scene === null) return source;
  return source
    .map((point) =>
      projectImagePointToTable(
        point,
        scene.projection.table_to_image_homography,
      ),
    )
    .filter((point): point is TablePoint => point !== null);
}

function posePolygon(
  pose: PoseCard,
  projection: CardSceneProjection,
  viewpoint: WorkbenchViewpoint,
): Array<[number, number]> {
  const polygon = cardPolygon(pose, projection);
  if (viewpoint === "rectified") return polygon;
  return polygon
    .map((point) =>
      projectTablePoint(point, projection.table_to_image_homography),
    )
    .filter((point): point is TablePoint => point !== null)
    .map(([x, y]) => [x, y] as [number, number]);
}

function sourcePoint(
  point: Point,
  width: number,
  height: number,
): [number, number] {
  return [(point.x * width) / 1000, (point.y * height) / 1000];
}

function isSelected(
  selection: WorkbenchSelection | null,
  candidate: WorkbenchSelection,
): boolean {
  return (
    selection !== null &&
    layerForSelection(selection) === layerForSelection(candidate) &&
    selection.id === candidate.id
  );
}

function renderOrder(
  scene: ReviewedCardScene,
  selection: WorkbenchSelection | null,
): PoseCard[] {
  const poses = new Map(scene.poses.map((pose) => [pose.card_id, pose]));
  const ordered = scene.stacking_order.card_ids
    .slice()
    .reverse()
    .map((cardId) => poses.get(cardId))
    .filter((pose): pose is PoseCard => pose !== undefined);
  const result = [
    ...ordered,
    ...scene.poses.filter(
      (pose) => !scene.stacking_order.card_ids.includes(pose.card_id),
    ),
  ];
  const selectedId = selection?.type === "virtual_card" ? selection.id : null;
  if (selectedId === null) return result;
  const selected = result.find((pose) => pose.card_id === selectedId);
  return selected === undefined
    ? result
    : [...result.filter((pose) => pose.card_id !== selectedId), selected];
}

function rotationHandle(
  pose: PoseCard,
  projection: CardSceneProjection,
  viewpoint: WorkbenchViewpoint,
): [number, number] {
  const angle = (pose.rotation_degrees * Math.PI) / 180;
  const tablePoint: TablePoint = [
    pose.center[0] + Math.sin(angle) * (projection.card_long_size / 2 + 0.18),
    pose.center[1] - Math.cos(angle) * (projection.card_long_size / 2 + 0.18),
  ];
  if (viewpoint === "rectified") return tablePoint;
  return (
    projectTablePoint(tablePoint, projection.table_to_image_homography) ?? [
      pose.center[0],
      pose.center[1],
    ]
  );
}

function strokeWidth(
  viewpoint: WorkbenchViewpoint,
  width: number,
  selected = false,
): number {
  if (viewpoint === "rectified") return selected ? 0.06 : 0.035;
  return selected ? Math.max(2, width / 250) : Math.max(1.25, width / 500);
}

function pointsAttribute(points: Array<[number, number]>): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

function pathAttribute(points: Array<[number, number]>): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  return `M ${first[0]} ${first[1]} ${rest
    .map(([x, y]) => `L ${x} ${y}`)
    .join(" ")} Z`;
}

function tableViewBox(
  scene: ReviewedCardScene,
  projection: CardSceneProjection,
  viewport: { zoom: number; pan: { x: number; y: number } },
): { x: number; y: number; width: number; height: number } {
  const points = scene.poses.flatMap((pose) => cardPolygon(pose, projection));
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const padding = Math.max(projection.card_long_size, 1);
  const minX = Math.min(...xs, -1) - padding;
  const maxX = Math.max(...xs, 1) + padding;
  const minY = Math.min(...ys, -1) - padding;
  const maxY = Math.max(...ys, 1) + padding;
  const baseWidth = Math.max(maxX - minX, 1);
  const baseHeight = Math.max(maxY - minY, 1);
  const zoom = Math.max(viewport.zoom, 0.01);
  const width = baseWidth / zoom;
  const height = baseHeight / zoom;
  const centerX = (minX + maxX) / 2 + viewport.pan.x;
  const centerY = (minY + maxY) / 2 + viewport.pan.y;
  return { x: centerX - width / 2, y: centerY - height / 2, width, height };
}

function RectifiedSourceFrame({
  sourceUrl,
  width,
  height,
  homography,
  clipPrefix,
}: {
  sourceUrl: string;
  width: number;
  height: number;
  homography: number[][];
  clipPrefix: string;
}) {
  const patches = rectifiedBackgroundPatches(
    width,
    height,
    homography,
    clipPrefix,
  );
  return (
    <g data-workbench-background="rectified" pointerEvents="none">
      <defs>
        {patches.map((patch) => (
          <clipPath
            key={patch.clipId}
            id={patch.clipId}
            clipPathUnits="userSpaceOnUse"
          >
            <polygon points={pointsAttribute(patch.sourceTriangle)} />
          </clipPath>
        ))}
      </defs>
      {patches.map((patch) => (
        <g key={patch.clipId} transform={patch.transform}>
          <image
            href={sourceUrl}
            x={0}
            y={0}
            width={width}
            height={height}
            preserveAspectRatio="none"
            clipPath={`url(#${patch.clipId})`}
            aria-hidden="true"
          />
        </g>
      ))}
    </g>
  );
}

function rectifiedBackgroundPatches(
  width: number,
  height: number,
  homography: number[][],
  clipPrefix: string,
) {
  const patches: Array<{
    clipId: string;
    sourceTriangle: TablePoint[];
    transform: string;
  }> = [];
  const gridSize = 12;
  let index = 0;
  for (let row = 0; row < gridSize; row += 1) {
    for (let column = 0; column < gridSize; column += 1) {
      const left = (column * width) / gridSize;
      const right = ((column + 1) * width) / gridSize;
      const top = (row * height) / gridSize;
      const bottom = ((row + 1) * height) / gridSize;
      const sourceTriangles: TablePoint[][] = [
        [
          [left, top],
          [right, top],
          [right, bottom],
        ],
        [
          [left, top],
          [right, bottom],
          [left, bottom],
        ],
      ];
      for (const sourceTriangle of sourceTriangles) {
        const destination = sourceTriangle.map((point) =>
          projectImagePointToTable(point, homography),
        );
        if (destination.some((point) => point === null)) continue;
        const transform = affineTriangleTransform(
          sourceTriangle,
          destination as TablePoint[],
        );
        if (transform === null) continue;
        patches.push({
          clipId: `${clipPrefix}-${index}`,
          sourceTriangle,
          transform,
        });
        index += 1;
      }
    }
  }
  return patches;
}

function affineTriangleTransform(
  source: TablePoint[],
  destination: TablePoint[],
): string | null {
  const [[x0, y0], [x1, y1], [x2, y2]] = source;
  const determinant = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1);
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-9)
    return null;
  const coefficients = [0, 1].flatMap((coordinate) => {
    const [u0, u1, u2] = destination.map((point) => point[coordinate]);
    return [
      (u0 * (y1 - y2) + u1 * (y2 - y0) + u2 * (y0 - y1)) / determinant,
      (u0 * (x2 - x1) + u1 * (x0 - x2) + u2 * (x1 - x0)) / determinant,
      (u0 * (x1 * y2 - x2 * y1) +
        u1 * (x2 * y0 - x0 * y2) +
        u2 * (x0 * y1 - x1 * y0)) /
        determinant,
    ];
  });
  const [a, c, e, b, d, f] = coefficients;
  if (![a, b, c, d, e, f].every(Number.isFinite)) return null;
  return `matrix(${a} ${b} ${c} ${d} ${e} ${f})`;
}
