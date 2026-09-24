import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type CSSProperties,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { createPortal } from "react-dom";

import type { CalibrationRefinementResponse } from "../api/client";
import { pipelineDerivedFramePath } from "../api/client";
import type { CalibrationFitDiagnosticOutline } from "./CalibrationFitDiagnostics";
import {
  TimelineRailSeekingControls,
  useTimelineRailReviewControlsSlot,
} from "../pipeline/TimelineRailSeekingControls";
import styles from "./PipelineVisibleCardEditor.module.css";
import { formatIdentifier } from "./PipelineVisibleCardFormatting";
import {
  applyPoseSceneAction,
  ANCHOR_STATES,
  cardPolygon,
  createCalibrationAnchorCommand,
  createCalibrationAnchorStateCommand,
  moveAnchorCorner,
  nextManualPoseId,
  projectImagePointToTable,
  projectTablePoint,
  withSceneDigest,
  type AnchorState,
  type CalibrationAnchorCommand,
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
  | VisibleRegionWorkbenchAction
  | VirtualCardWorkbenchAction
  | MappingWorkbenchAction;

export type MappingWorkbenchAction =
  | "accept_anchor"
  | "exclude_anchor"
  | "start_mapping_preview"
  | "discard_mapping_preview";

type WorkbenchCalibrationAnchor = {
  anchorId: string;
  cardId: string;
  sourceFrameId: string;
  eligible: boolean;
  state: AnchorState;
  corners: TablePoint[];
};

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

type VirtualCardGesture = {
  pointerId: number;
  cardId: string | null;
  kind: "move" | "rotate" | "pan";
  dirty: boolean;
  startClientX: number;
  startClientY: number;
  originalScene: PoseSceneEnvelope | null;
  startPan?: { x: number; y: number };
  startViewBox?: { x: number; y: number; width: number; height: number };
  startPoint?: Point | null;
};

type MappingGesture = {
  pointerId: number;
  anchorId: string;
  movedCorner: number;
  dirty: boolean;
  startClientX: number;
  startClientY: number;
  originalCorners: TablePoint[];
  sourceOffset: TablePoint;
};

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
  const virtualGestureRef = useRef<VirtualCardGesture | null>(null);
  const [gestureViewBox, setGestureViewBox] = useState<
    { x: number; y: number; width: number; height: number } | undefined
  >(undefined);
  const mappingGestureRef = useRef<MappingGesture | null>(null);
  const [anchorPreview, setAnchorPreview] =
    useState<WorkbenchCalibrationAnchor | null>(null);
  const anchorPreviewRef = useRef<WorkbenchCalibrationAnchor | null>(null);
  const [anchorCornerIndex, setAnchorCornerIndex] = useState(0);
  const [numericAnchor, setNumericAnchor] = useState<{
    anchorId: string;
    point: TablePoint;
  } | null>(null);
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

  const renderMappingAnchors = mappingAnchors.map((anchor) =>
    anchorPreview?.anchorId === anchor.anchorId ? anchorPreview : anchor,
  );

  const setAnchorPreviewState = (next: WorkbenchCalibrationAnchor | null) => {
    anchorPreviewRef.current = next;
    setAnchorPreview(next);
  };

  const select = (selection: WorkbenchSelection) => {
    dispatch({ type: "select", selection });
    onSelectionChange?.(selection);
  };

  const clearSelection = () => {
    if (activeState.selection === null) return;
    dispatch({ type: "clear_selection" });
    onSelectionChange?.(null);
  };

  const handleSurfaceKeyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    if (
      event.key === "Escape" &&
      activeState.activeTool === "virtual_cards" &&
      activeState.selection?.type === "virtual_card"
    ) {
      event.preventDefault();
      event.stopPropagation();
      clearSelection();
      return;
    }
    const shortcut = workbenchViewportShortcut(event, "surface");
    if (shortcut === null) return;
    event.preventDefault();
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

  const emitAnchorCommand = (command: CalibrationAnchorCommand) => {
    if (readOnly || onAnchorCommand === undefined) return;
    return onAnchorCommand(command);
  };

  const anchorCommandContext = () => ({
    sequence: calibrationCommandCount(calibrationRefinement) + 1,
    expectedDraftRevision: calibrationDraftRevision(calibrationRefinement),
  });

  const emitAnchorStateCommand = (state: AnchorState) => {
    const anchor = selectedMappingAnchor;
    if (
      anchor === null ||
      (!anchor.eligible && state !== "excluded") ||
      onAnchorCommand === undefined
    )
      return;
    const context = anchorCommandContext();
    emitAnchorCommand(
      createCalibrationAnchorStateCommand({
        command_id: `anchor-command-${frame.itemId}-${context.sequence}`,
        sequence: context.sequence,
        expected_draft_revision: context.expectedDraftRevision,
        anchor_id: anchor.anchorId,
        state,
        operator_id: "local-operator",
      }),
    );
  };

  const handleMappingAction = (action: MappingWorkbenchAction) => {
    switch (action) {
      case "accept_anchor":
        emitAnchorStateCommand("accepted");
        return;
      case "exclude_anchor":
        emitAnchorStateCommand("excluded");
        return;
      case "start_mapping_preview":
        onStartMappingPreview?.();
        return;
      case "discard_mapping_preview":
        onDiscardMappingPreview?.();
        return;
    }
  };

  const beginMappingAnchorGesture = (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    movedCorner: number,
    sourceOffset: TablePoint = [0, 0],
  ) => {
    if (
      readOnly ||
      activeState.activeTool !== "mapping" ||
      onAnchorCommand === undefined
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    select({ type: "calibration_anchor", id: anchor.anchorId });
    setAnchorCornerIndex(movedCorner);
    const preview = { ...anchor, corners: cloneTablePoints(anchor.corners) };
    mappingGestureRef.current = {
      pointerId: event.pointerId,
      anchorId: anchor.anchorId,
      movedCorner,
      dirty: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalCorners: cloneTablePoints(anchor.corners),
      sourceOffset,
    };
    setAnchorPreviewState(preview);
    event.currentTarget.ownerSVGElement?.setPointerCapture?.(event.pointerId);
    dispatch({
      type: "begin_gesture",
      gesture: { kind: "edit", tool: "mapping", pointerId: event.pointerId },
    });
  };

  const updateMappingAnchorPreview = (point: Point | null) => {
    const gesture = mappingGestureRef.current;
    if (gesture === null || point === null) return;
    const anchor = mappingAnchors.find(
      (candidate) => candidate.anchorId === gesture.anchorId,
    );
    if (anchor === undefined) return;
    const pointerPosition = sourcePoint(point, width, height);
    const sourcePosition: TablePoint = [
      pointerPosition[0] + gesture.sourceOffset[0],
      pointerPosition[1] + gesture.sourceOffset[1],
    ];
    const corners = moveAnchorCorner(
      gesture.originalCorners,
      gesture.movedCorner,
      sourcePosition,
    );
    gesture.dirty = corners.some(
      (corner, index) =>
        corner[0] !== gesture.originalCorners[index]?.[0] ||
        corner[1] !== gesture.originalCorners[index]?.[1],
    );
    setAnchorPreviewState({ ...anchor, corners });
  };

  const beginMappingNumericEdit = (value: number, axis: 0 | 1) => {
    if (selectedMappingAnchor === null || !Number.isFinite(value)) return;
    const corner = selectedMappingAnchor.corners[anchorCornerIndex];
    if (corner === undefined) return;
    setNumericAnchor({
      anchorId: selectedMappingAnchor.anchorId,
      point: [axis === 0 ? value : corner[0], axis === 1 ? value : corner[1]],
    });
  };

  const emitNumericAnchorCommand = () => {
    if (numericAnchor === null || onAnchorCommand === undefined) return;
    const anchor = mappingAnchors.find(
      (candidate) => candidate.anchorId === numericAnchor.anchorId,
    );
    if (anchor === undefined) return;
    const context = anchorCommandContext();
    emitAnchorCommand(
      createCalibrationAnchorCommand({
        command_id: `anchor-command-${frame.itemId}-${context.sequence}`,
        sequence: context.sequence,
        expected_draft_revision: context.expectedDraftRevision,
        anchor_id: anchor.anchorId,
        moved_corner: anchorCornerIndex,
        corners: moveAnchorCorner(
          anchor.corners,
          anchorCornerIndex,
          numericAnchor.point,
        ),
        operator_id: "local-operator",
      }),
    );
    setNumericAnchor(null);
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
    const startViewBox = surfaceViewBox(
      activeState.viewpoint,
      width,
      height,
      sceneDraftRef.current,
      viewport,
    );
    if (startViewBox === null) return;
    select({ type: "virtual_card", id: cardId });
    setGestureViewBox(startViewBox);
    virtualGestureRef.current = {
      pointerId: event.pointerId,
      cardId,
      kind,
      dirty: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalScene: sceneDraftRef.current,
      startViewBox,
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

  const beginTablePan = (
    event: ReactPointerEvent<SVGSVGElement>,
    point: Point | null,
  ) => {
    if (
      event.button !== 0 ||
      event.target !== event.currentTarget ||
      virtualGestureRef.current !== null
    )
      return false;
    const currentScene = sceneDraftRef.current;
    const viewBox = surfaceViewBox(
      activeState.viewpoint,
      width,
      height,
      currentScene,
      viewport,
    );
    if (viewBox === null) return false;
    event.preventDefault();
    setGestureViewBox(undefined);
    virtualGestureRef.current = {
      pointerId: event.pointerId,
      cardId: null,
      kind: "pan",
      dirty: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalScene: currentScene,
      startPan: { ...viewport.pan },
      startViewBox: viewBox,
      startPoint: point,
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
    if (
      event.target === event.currentTarget &&
      activeState.activeTool === "virtual_cards" &&
      activeState.selection?.type === "virtual_card"
    )
      clearSelection();
    if (beginTablePan(event, point)) return;
    if (
      activeState.activeTool === "virtual_cards" ||
      activeState.activeTool === "mapping"
    )
      return;
    onCanvasPointerDown?.(event, point);
  };

  const handleSurfacePointerMove = (
    event: ReactPointerEvent<SVGSVGElement>,
    point: Point | null,
  ) => {
    const mappingGesture = mappingGestureRef.current;
    if (
      mappingGesture !== null &&
      mappingGesture.pointerId === event.pointerId
    ) {
      if (
        !mappingGesture.dirty &&
        Math.hypot(
          event.clientX - mappingGesture.startClientX,
          event.clientY - mappingGesture.startClientY,
        ) < 4
      )
        return;
      updateMappingAnchorPreview(point);
      return;
    }
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      if (
        activeState.activeTool === "virtual_cards" ||
        activeState.activeTool === "mapping"
      )
        return;
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
          zoom: viewport.zoom,
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
    const mappingGesture = mappingGestureRef.current;
    if (
      mappingGesture !== null &&
      mappingGesture.pointerId === event.pointerId
    ) {
      mappingGestureRef.current = null;
      setGestureViewBox(undefined);
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      dispatch({ type: "commit_gesture" });
      const preview = anchorPreviewRef.current;
      if (mappingGesture.dirty && preview !== null) {
        const context = anchorCommandContext();
        const result = emitAnchorCommand(
          createCalibrationAnchorCommand({
            command_id: `anchor-command-${frame.itemId}-${context.sequence}`,
            sequence: context.sequence,
            expected_draft_revision: context.expectedDraftRevision,
            anchor_id: mappingGesture.anchorId,
            moved_corner: mappingGesture.movedCorner,
            corners: preview.corners,
            operator_id: "local-operator",
          }),
        );
        const clearSavedPreview = () => {
          if (anchorPreviewRef.current === preview) setAnchorPreviewState(null);
        };
        void Promise.resolve(result).then(clearSavedPreview, clearSavedPreview);
      } else {
        setAnchorPreviewState(null);
      }
      return;
    }
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      onPointerUp?.(event);
      return;
    }
    virtualGestureRef.current = null;
    setGestureViewBox(undefined);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dispatch({ type: "commit_gesture" });
    if (gesture.kind === "pan") {
      if (!gesture.dirty && activeState.activeTool === "visible_regions") {
        onCanvasPointerDown?.(event, gesture.startPoint ?? null);
      }
      return;
    }
    if (!gesture.dirty) return;
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
    const mappingGesture = mappingGestureRef.current;
    if (
      mappingGesture !== null &&
      mappingGesture.pointerId === event.pointerId
    ) {
      mappingGestureRef.current = null;
      setGestureViewBox(undefined);
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      setAnchorPreviewState(null);
      dispatch({ type: "cancel_gesture" });
      return;
    }
    const gesture = virtualGestureRef.current;
    if (gesture === null || gesture.pointerId !== event.pointerId) {
      onPointerCancel?.(event);
      if (onPointerCancel === undefined) onPointerUp?.(event);
      return;
    }
    virtualGestureRef.current = null;
    setGestureViewBox(undefined);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    sceneDraftRef.current = gesture.originalScene;
    setSceneDraft(gesture.originalScene);
    dispatch({ type: "cancel_gesture" });
  };

  const handleSurfaceWheel = (event: ReactWheelEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0 || event.deltaY === 0) return;
    event.preventDefault();
    const currentScene = sceneDraftRef.current;
    const currentViewBox = surfaceViewBox(
      activeState.viewpoint,
      width,
      height,
      currentScene,
      viewport,
    );
    if (currentViewBox === null) return;
    const deltaY =
      event.deltaY *
      (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
    const nextZoom = Math.min(
      4,
      Math.max(0.5, viewport.zoom * Math.pow(2, -deltaY / 240)),
    );
    if (nextZoom === viewport.zoom) return;
    const focusX = (event.clientX - rect.left) / rect.width;
    const focusY = (event.clientY - rect.top) / rect.height;
    const focusedPoint: TablePoint = [
      currentViewBox.x + focusX * currentViewBox.width,
      currentViewBox.y + focusY * currentViewBox.height,
    ];
    const nextViewBox = surfaceViewBox(
      activeState.viewpoint,
      width,
      height,
      currentScene,
      {
        zoom: nextZoom,
        pan: viewport.pan,
      },
    );
    if (nextViewBox === null) return;
    dispatch({
      type: "set_viewport",
      viewport: {
        zoom: nextZoom,
        pan: {
          x:
            viewport.pan.x +
            focusedPoint[0] -
            (nextViewBox.x + focusX * nextViewBox.width),
          y:
            viewport.pan.y +
            focusedPoint[1] -
            (nextViewBox.y + focusY * nextViewBox.height),
        },
      },
    });
  };

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
      state={activeState}
      readOnly={readOnly}
      selectedCandidateIds={selectedCandidateIds}
      editor={editor}
      canCopyIgnoreRegions={canCopyIgnoreRegions}
      canRestoreSuggestion={canRestoreSuggestion}
      frameDecision={frameDecision}
      scene={scene}
      calibrationRefinement={calibrationRefinement}
      mappingAnchors={mappingAnchors}
      mappingLoading={mappingLoading}
      anchorCornerIndex={anchorCornerIndex}
      numericAnchor={numericAnchor}
      onNumericChange={beginMappingNumericEdit}
      onEmitNumeric={emitNumericAnchorCommand}
      onCardDecision={onCardDecision}
      onResolveRemaining={onResolveRemaining}
      onSceneAction={applySceneAction}
      onAction={handleWorkbenchAction}
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
        state={activeState}
        availability={availability}
        readOnly={readOnly}
        enabledEditTools={
          enabledEditTools ?? ["visible_regions", "virtual_cards", "mapping"]
        }
        onToggleViewpoint={() => dispatch({ type: "toggle_viewpoint" })}
        onToggleLayer={(layer) => dispatch({ type: "toggle_layer", layer })}
        onSelectTool={(tool) => {
          dispatch({ type: "select_tool", tool });
          onToolChange?.(tool);
          if (
            tool === "mapping" &&
            calibrationRefinement === null &&
            !mappingLoading
          ) {
            onStartMappingPreview?.();
          }
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
            editor={editor}
            editorError={editorError}
            selectedCandidateIds={selectedCandidateIds}
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

function WorkbenchCommandBar({
  state,
  availability,
  readOnly,
  enabledEditTools,
  onToggleViewpoint,
  onToggleLayer,
  onSelectTool,
}: {
  state: VisibleCardReviewWorkbenchState;
  availability: ReturnType<typeof getWorkbenchAvailability>;
  readOnly: boolean;
  enabledEditTools: readonly WorkbenchPreferences["activeTool"][];
  onToggleViewpoint: () => void;
  onToggleLayer: (layer: WorkbenchLayer) => void;
  onSelectTool: (tool: WorkbenchPreferences["activeTool"]) => void;
}) {
  const nextViewpoint = state.viewpoint === "camera" ? "rectified" : "camera";
  const viewpointAvailability = availability.viewpoints[nextViewpoint];
  const viewpointLabel = `Viewpoint: ${VIEWPOINT_LABELS[state.viewpoint]}. Switch to ${VIEWPOINT_LABELS[nextViewpoint]}`;
  return (
    <div
      className={styles.workbenchCommandBar}
      aria-label="Workbench command bar"
      role="toolbar"
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
    </div>
  );
}

type WorkbenchTimelineSelectionActionsProps = {
  state: VisibleCardReviewWorkbenchState;
  readOnly: boolean;
  selectedCandidateIds: string[];
  editor: EditorState | null;
  canCopyIgnoreRegions: boolean;
  canRestoreSuggestion: boolean;
  frameDecision?: VisibleCardFrameDecision;
  scene: PoseSceneEnvelope | null;
  calibrationRefinement: CalibrationRefinementResponse | null;
  mappingAnchors: WorkbenchCalibrationAnchor[];
  mappingLoading: boolean;
  anchorCornerIndex: number;
  numericAnchor: { anchorId: string; point: TablePoint } | null;
  onNumericChange: (value: number, axis: 0 | 1) => void;
  onEmitNumeric: () => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
};

function WorkbenchTimelineSelectionActions({
  state,
  readOnly,
  selectedCandidateIds,
  editor,
  canCopyIgnoreRegions,
  canRestoreSuggestion,
  frameDecision,
  scene,
  calibrationRefinement,
  mappingAnchors,
  mappingLoading,
  anchorCornerIndex,
  numericAnchor,
  onNumericChange,
  onEmitNumeric,
  onCardDecision,
  onResolveRemaining,
  onSceneAction,
  onAction,
}: WorkbenchTimelineSelectionActionsProps) {
  const content = (
    <div
      className={styles.workbenchTimelineActions}
      aria-label="Selection actions"
    >
      {state.activeTool === "visible_regions" ||
      selectedCandidateIds.length > 0 ? (
        <VisibleRegionSelectionActions
          readOnly={readOnly}
          sourceAvailable={
            getWorkbenchAvailability(state.capabilities).viewpoints.camera
              .available
          }
          selectedCandidateCount={selectedCandidateIds.length}
          editor={editor}
          selection={state.selection}
          canCopyIgnoreRegions={canCopyIgnoreRegions}
          canRestoreSuggestion={canRestoreSuggestion}
          onAction={onAction}
        />
      ) : null}
      {state.activeTool === "virtual_cards" &&
      selectedCandidateIds.length === 0 ? (
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
      {state.activeTool === "mapping" && selectedCandidateIds.length === 0 ? (
        <MappingSelectionActions
          readOnly={readOnly}
          refinement={calibrationRefinement}
          anchors={mappingAnchors}
          selection={state.selection}
          anchorCornerIndex={anchorCornerIndex}
          numericAnchor={numericAnchor}
          mappingLoading={mappingLoading}
          onNumericChange={onNumericChange}
          onEmitNumeric={onEmitNumeric}
          onAction={onAction}
        />
      ) : null}
      {frameDecision !== undefined ? (
        <FrameDecisionActions decision={frameDecision} />
      ) : null}
    </div>
  );
  return content;
}

function FrameDecisionActions({
  decision,
}: {
  decision: VisibleCardFrameDecision;
}) {
  return (
    <div
      className={styles.workbenchCommandGroup}
      aria-label="Frame decision"
      role="group"
    >
      <span className={styles.workbenchCommandLabel}>Frame decision</span>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="A"
        disabled={!decision.canAccept}
        title={
          decision.canAccept
            ? "Accept frame · A"
            : decision.acceptDisabledReason
        }
        onClick={decision.onAccept}
      >
        {decision.accepted ? "Mark frame unreviewed" : "Accept frame"}
      </button>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="E"
        title="Mark empty frame · E"
        onClick={decision.onMarkEmpty}
      >
        Mark empty
      </button>
      <button
        type="button"
        className={styles.workbenchToggle}
        aria-keyshortcuts="U"
        title="Mark unusable frame · U"
        onClick={decision.onMarkUnusable}
      >
        Mark unusable
      </button>
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
  const actionControl = (
    action: VirtualCardWorkbenchAction,
    label: string,
    symbol: string,
    shortcut: string,
    disabled: boolean,
    reason: string,
  ) => ({
    label,
    symbol,
    shortcut,
    ariaShortcut: shortcut === "Click" ? undefined : shortcut,
    disabled,
    disabledReason: reason,
    onClick: () => {
      if (
        (action === "accept_card" || action === "reject_card") &&
        selectedCardId !== null &&
        onCardDecision !== undefined
      ) {
        onCardDecision(
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
    },
  });
  const controls = [
    actionControl(
      "add_virtual_card",
      "Add virtual card",
      "＋",
      "Click",
      readOnly || !sceneAvailable,
      readOnly
        ? "Generated visible-card results are read-only."
        : "A proposed card scene is required to add a virtual card.",
    ),
    actionControl(
      "accept_card",
      selectedCardId === null ? "Accept card" : `Accept card ${cardTarget}`,
      "✓",
      "Click",
      readOnly ||
        selectedCardId === null ||
        selectedReviewState === null ||
        selectedReviewState.state === "accepted",
      selectedCardId === null
        ? "Select a virtual card first."
        : selectedReviewState === null
          ? "This card has no review decision state."
          : "The selected card is already accepted.",
    ),
    actionControl(
      "reject_card",
      selectedCardId === null ? "Reject card" : `Reject card ${cardTarget}`,
      "×",
      "Click",
      readOnly ||
        selectedCardId === null ||
        selectedReviewState === null ||
        selectedReviewState.state === "rejected",
      selectedCardId === null
        ? "Select a virtual card first."
        : selectedReviewState === null
          ? "This card has no review decision state."
          : "The selected card is already rejected.",
    ),
    actionControl(
      "accept_remaining_cards",
      "Accept remaining cards",
      "✓✓",
      "Click",
      readOnly || pendingCount === 0 || onResolveRemaining === undefined,
      pendingCount === 0
        ? "No pending card decisions remain."
        : "All pending cards must be resolved through the maintained reference.",
    ),
    actionControl(
      "remove_card",
      selectedCardId === null ? "Remove card" : `Remove card ${cardTarget}`,
      "−",
      "Click",
      readOnly || selectedPose === null || scene?.scene.poses.length === 1,
      selectedPose === null
        ? "Select a virtual card first."
        : scene?.scene.poses.length === 1
          ? "A card scene must keep one virtual card."
          : "",
    ),
    actionControl(
      "bring_forward",
      selectedCardId === null
        ? "Bring card forward"
        : `Bring card ${cardTarget} forward`,
      "↑",
      "Click",
      readOnly || selectedPose === null,
      "Select a virtual card first.",
    ),
    actionControl(
      "send_backward",
      selectedCardId === null
        ? "Send card backward"
        : `Send card ${cardTarget} backward`,
      "↓",
      "Click",
      readOnly || selectedPose === null,
      "Select a virtual card first.",
    ),
    actionControl(
      "restore_proposed_scene",
      "Restore proposed scene",
      "↺",
      "Click",
      readOnly || !sceneAvailable,
      readOnly
        ? "Generated visible-card results are read-only."
        : "A proposed card scene is required to restore the scene.",
    ),
  ];
  return (
    <>
      <TimelineRailSeekingControls
        groups={[{ label: "Selection actions", controls }]}
      />
      <label
        key={selectedPose?.card_id ?? "no-selected-card"}
        className={styles.workbenchTimelineField}
      >
        <span>Rotation</span>
        <input
          aria-label="Rotation (degrees)"
          type="number"
          step="1"
          defaultValue={selectedPose?.rotation_degrees ?? ""}
          disabled={readOnly || selectedPose === null}
          title={
            selectedPose === null
              ? "Select a virtual card to set its rotation."
              : "Set rotation in degrees."
          }
          onBlur={(event) => {
            const value = Number(event.target.value);
            if (
              !Number.isFinite(value) ||
              scene === null ||
              selectedPose === null
            )
              return;
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
    </>
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

function MappingSelectionActions({
  readOnly,
  refinement,
  anchors,
  selection,
  anchorCornerIndex,
  numericAnchor,
  mappingLoading,
  onNumericChange,
  onEmitNumeric,
  onAction,
}: {
  readOnly: boolean;
  refinement: CalibrationRefinementResponse | null;
  anchors: WorkbenchCalibrationAnchor[];
  selection: WorkbenchSelection | null;
  anchorCornerIndex: number;
  numericAnchor: { anchorId: string; point: TablePoint } | null;
  mappingLoading: boolean;
  onNumericChange: (value: number, axis: 0 | 1) => void;
  onEmitNumeric: () => void;
  onAction: (action: VisibleCardReviewWorkbenchAction) => void;
}) {
  const selectedAnchor =
    selection?.type === "calibration_anchor"
      ? (anchors.find((anchor) => anchor.anchorId === selection.id) ?? null)
      : null;
  const stateButton = (
    state: "accepted" | "excluded",
    label: string,
    symbol: string,
  ) => ({
    label,
    symbol,
    shortcut: "Click",
    disabled:
      readOnly ||
      selectedAnchor === null ||
      (!selectedAnchor.eligible && state !== "excluded") ||
      selectedAnchor.state === state ||
      refinement === null,
    disabledReason:
      selectedAnchor === null
        ? "Select a calibration anchor first."
        : refinement === null
          ? "Start a mapping preview before changing anchor decisions."
          : "The selected anchor already has this state.",
    onClick: () =>
      onAction(state === "accepted" ? "accept_anchor" : "exclude_anchor"),
  });
  const corner =
    selectedAnchor?.corners[anchorCornerIndex] ?? ([0, 0] as TablePoint);
  const numericPoint =
    numericAnchor !== null &&
    numericAnchor.anchorId === selectedAnchor?.anchorId
      ? numericAnchor.point
      : corner;
  const controls = [
    stateButton("accepted", "Accept anchor", "✓"),
    stateButton("excluded", "Exclude anchor", "⊘"),
    {
      label: "Start mapping preview",
      symbol: "▶",
      shortcut: "Click",
      disabled: readOnly || refinement !== null || mappingLoading,
      disabledReason: "A mapping preview is already active.",
      onClick: () => onAction("start_mapping_preview"),
    },
    {
      label: "Discard mapping preview",
      symbol: "↶",
      shortcut: "Click",
      disabled: readOnly || refinement === null || mappingLoading,
      disabledReason: "Start a mapping preview first.",
      onClick: () => onAction("discard_mapping_preview"),
    },
  ];
  return (
    <>
      <p>
        Drag corners to save corrected anchors. Apply the calibration to the
        table in Recording-wide mapping.
      </p>
      <TimelineRailSeekingControls
        groups={[{ label: "Anchor decisions", controls }]}
      />
      {selectedAnchor !== null ? (
        <div className={styles.workbenchTimelineFields}>
          <label className={styles.workbenchTimelineField}>
            <span>Corner {anchorCornerIndex + 1} X</span>
            <input
              aria-label={`Anchor corner ${anchorCornerIndex + 1} X`}
              type="number"
              step="0.01"
              value={numericPoint[0]}
              disabled={readOnly}
              onChange={(event) =>
                onNumericChange(Number(event.target.value), 0)
              }
            />
          </label>
          <label className={styles.workbenchTimelineField}>
            <span>Corner {anchorCornerIndex + 1} Y</span>
            <input
              aria-label={`Anchor corner ${anchorCornerIndex + 1} Y`}
              type="number"
              step="0.01"
              value={numericPoint[1]}
              disabled={readOnly}
              onChange={(event) =>
                onNumericChange(Number(event.target.value), 1)
              }
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  onEmitNumeric();
                }
              }}
            />
          </label>
          <button
            type="button"
            className={styles.workbenchTimelineFieldButton}
            aria-label="Save corner coordinates"
            disabled={readOnly || numericAnchor === null}
            title="Save corner coordinates · Enter"
            onClick={onEmitNumeric}
          >
            <span aria-hidden="true">✓</span>
          </button>
        </div>
      ) : null}
    </>
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
    ariaLabel?: string;
    symbol: string;
    shortcut: string;
    ariaShortcut?: string;
    disabled: boolean;
    reason: string;
  }> = [
    {
      action: "add_visible_card",
      label: "Add visible card",
      symbol: "＋",
      shortcut: "N",
      ariaShortcut: "N",
      disabled: readOnly || !sourceAvailable,
      reason: readOnly
        ? "Generated visible-card results are read-only."
        : "A resolved source frame is required to add a visible card.",
    },
    {
      action: "add_polygon",
      label: "Add polygon",
      symbol: "◇+",
      shortcut: "Click",
      disabled: readOnly || editor === null || editor.cardId === null,
      reason: "Select a visible card before adding a polygon.",
    },
    {
      action: "remove_polygon",
      label: "Remove polygon",
      symbol: "◇−",
      shortcut: "Click",
      disabled: readOnly || editor === null || editor.polygons.length <= 1,
      reason: "A visible card must keep one polygon.",
    },
    {
      action: "draw_ignore_region",
      label: "Draw ignore region",
      ariaLabel: "Draw ignore region in shared workbench",
      symbol: "⊘",
      shortcut: "Click",
      disabled: readOnly || !sourceAvailable,
      reason: "A resolved source frame is required to draw an ignore region.",
    },
    {
      action: "convert_to_ignore_region",
      label: "Convert selection to ignore region",
      symbol: "⇢",
      shortcut: "I",
      ariaShortcut: "I",
      disabled: readOnly || selectedCandidateCount === 0,
      reason:
        "Select one or more proposals to convert them to an ignore region.",
    },
    {
      action: "copy_ignore_regions",
      label: "Copy ignore regions",
      symbol: "⧉",
      shortcut: "Click",
      disabled: readOnly || !canCopyIgnoreRegions,
      reason: "Review an earlier frame with ignore regions first.",
    },
    {
      action: "delete_selection",
      label: "Delete selection",
      symbol: "⌫",
      shortcut: "Delete",
      ariaShortcut: "Delete",
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
      symbol: "↺",
      shortcut: "Click",
      disabled: readOnly || !canRestoreSuggestion,
      reason: "A generated suggestion is required to restore this frame.",
    },
  ];
  return (
    <TimelineRailSeekingControls
      groups={[
        {
          label: "Selection actions",
          controls: actions.map(
            ({
              action,
              label,
              ariaLabel,
              symbol,
              shortcut,
              ariaShortcut,
              disabled,
              reason,
            }) => ({
              label,
              ariaLabel,
              symbol,
              shortcut,
              ariaShortcut,
              disabled,
              disabledReason: reason,
              onClick: () => onAction(action),
            }),
          ),
        },
      ]}
    />
  );
}

function WorkbenchProposalColumn({
  frame,
  candidates,
  scene,
  activeTool,
  sourceUrl,
  frameWidth,
  frameHeight,
  readOnly,
  selection,
  editor,
  editorError,
  selectedCandidateIds,
  onToggleCandidateSelection,
  onSelectCandidate,
  onSelectIgnoreRegion,
  onSelectEditorPolygon,
  onSelectVirtualCard,
  onSceneAction,
  proposalSlot,
}: {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  activeTool: WorkbenchPreferences["activeTool"];
  sourceUrl: string | null;
  frameWidth: number;
  frameHeight: number;
  readOnly: boolean;
  selection: WorkbenchSelection | null;
  editor: EditorState | null;
  editorError: string | null;
  selectedCandidateIds: string[];
  onToggleCandidateSelection?: (cardId: string) => void;
  onSelectCandidate: (candidate: Candidate, polygonIndex?: number) => void;
  onSelectIgnoreRegion?: (region: IgnoreRegion) => void;
  onSelectEditorPolygon?: (polygonIndex: number) => void;
  onSelectVirtualCard: (cardId: string) => void;
  onSceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  proposalSlot: HTMLElement | null;
}) {
  const stackingOrder =
    scene === null
      ? []
      : [
          ...scene.scene.stacking_order.card_ids,
          ...scene.scene.poses
            .map((pose) => pose.card_id)
            .filter(
              (cardId) => !scene.scene.stacking_order.card_ids.includes(cardId),
            ),
        ].filter((cardId) =>
          scene.scene.poses.some((pose) => pose.card_id === cardId),
        );
  const poseById = new Map(
    (scene?.scene.poses ?? []).map((pose) => [pose.card_id, pose]),
  );
  const candidateById = new Map(candidates.map((item) => [item.card_id, item]));
  const isStackOrderMode = activeTool === "virtual_cards" && scene !== null;
  const content = (
    <section
      className={styles.proposalColumn}
      aria-label={
        isStackOrderMode ? "Card stack order" : "Visible-card proposals"
      }
    >
      {editorError !== null ? (
        <p className={styles.inlineFormError} role="alert">
          {editorError}
        </p>
      ) : null}
      {isStackOrderMode ? (
        <section className={styles.stackOrderSection} aria-label="Stack order">
          <ol className={styles.proposalItems}>
            {stackingOrder.map((cardId, index) => {
              const pose = poseById.get(cardId);
              if (pose === undefined) return null;
              const candidate =
                (typeof pose.source_suggestion_id !== "string"
                  ? undefined
                  : candidateById.get(pose.source_suggestion_id)) ??
                candidateById.get(cardId);
              const previewCandidate =
                candidate ??
                (scene === null
                  ? null
                  : virtualCardPreviewCandidate(
                      pose,
                      scene,
                      frameWidth,
                      frameHeight,
                    ));
              const selected =
                selection?.type === "virtual_card" && selection.id === cardId;
              return (
                <li
                  key={cardId}
                  className={styles.stackOrderRow}
                  draggable={!readOnly}
                  data-card-id={cardId}
                  data-stacking-index={index}
                  data-selected={selected ? "true" : undefined}
                  onDragStart={(event) => {
                    event.dataTransfer.setData("text/plain", cardId);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  onDragOver={(event) => {
                    if (!readOnly) {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "move";
                    }
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    const draggedCardId =
                      event.dataTransfer.getData("text/plain");
                    const currentIndex = stackingOrder.indexOf(draggedCardId);
                    if (
                      readOnly ||
                      currentIndex < 0 ||
                      draggedCardId === cardId ||
                      currentIndex === index
                    ) {
                      return;
                    }
                    onSceneAction(
                      { type: "place", cardId: draggedCardId, index },
                      `Card moved to stack position ${index + 1}.`,
                    );
                  }}
                >
                  <span className={styles.stackOrderRank} aria-hidden="true">
                    {index + 1}
                  </span>
                  <button
                    className={styles.stackOrderSelect}
                    type="button"
                    aria-label={`Select virtual card at stack position ${index + 1}`}
                    aria-pressed={selected}
                    onClick={() => onSelectVirtualCard(cardId)}
                  >
                    {previewCandidate !== null ? (
                      <CandidatePreview
                        candidate={previewCandidate}
                        sourceUrl={sourceUrl}
                        frameWidth={frameWidth}
                        frameHeight={frameHeight}
                        label={`Card at stack position ${index + 1} preview`}
                      />
                    ) : (
                      <span
                        className={styles.stackOrderPlaceholder}
                        aria-hidden="true"
                      >
                        ◇
                      </span>
                    )}
                    <span className={styles.proposalDetails}>
                      <strong>{candidate?.side ?? "Virtual card"}</strong>
                      <span>
                        {index === 0
                          ? "Front"
                          : index === stackingOrder.length - 1
                            ? "Back"
                            : `Layer ${index + 1}`}
                      </span>
                    </span>
                  </button>
                  <span className={styles.stackOrderActions}>
                    <button
                      type="button"
                      aria-label={`Move card at stack position ${index + 1} toward front`}
                      disabled={readOnly || index === 0}
                      onClick={() =>
                        onSceneAction(
                          { type: "place", cardId, index: index - 1 },
                          `Card moved to stack position ${index}.`,
                        )
                      }
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Move card at stack position ${index + 1} toward back`}
                      disabled={readOnly || index === stackingOrder.length - 1}
                      onClick={() =>
                        onSceneAction(
                          { type: "place", cardId, index: index + 1 },
                          `Card moved to stack position ${index + 2}.`,
                        )
                      }
                    >
                      ↓
                    </button>
                  </span>
                </li>
              );
            })}
          </ol>
          {!readOnly && stackingOrder.length > 1 ? (
            <p className={styles.stackOrderHint}>
              Drag a card to change its stack position.
            </p>
          ) : null}
        </section>
      ) : null}
      {candidates.length === 0 ? (
        <p className={styles.detailEmptyState}>
          No proposals. Add a visible card or review this frame as empty.
        </p>
      ) : (
        <ol className={styles.proposalItems}>
          {candidates.map((candidate, index) => {
            const polygonCount =
              editor?.cardId === candidate.card_id
                ? editor.polygons.length
                : (candidate.geometry.visible_region?.polygons.length ?? 1);
            const hasMultiplePolygons = polygonCount > 1;
            const alreadyIgnored = candidateIsCoveredByIgnoreRegions(
              candidate,
              frame.outcome.ignored_regions,
            );
            const markedForIgnore =
              !alreadyIgnored &&
              selectedCandidateIds.includes(candidate.card_id);
            const isEditorSelection =
              (selection?.id === candidate.card_id &&
                (selection.type === "visible_card" ||
                  selection.type === "polygon")) ||
              editor?.cardId === candidate.card_id;
            const statusLabel = alreadyIgnored
              ? "Already ignored"
              : markedForIgnore
                ? "Marked for ignore"
                : "Detector suggestion";
            return (
              <li key={candidate.card_id}>
                <div
                  className={styles.proposalRow}
                  data-already-ignored={alreadyIgnored ? "true" : undefined}
                  data-marked-for-ignore={markedForIgnore ? "true" : undefined}
                >
                  {!readOnly ? (
                    <label className={styles.proposalCheckbox}>
                      <input
                        type="checkbox"
                        aria-label={`Select proposal ${index + 1} for ignore region`}
                        checked={markedForIgnore || alreadyIgnored}
                        disabled={alreadyIgnored}
                        onChange={() =>
                          onToggleCandidateSelection?.(candidate.card_id)
                        }
                      />
                    </label>
                  ) : null}
                  <button
                    className={styles.proposalSelect}
                    type="button"
                    aria-label={`Select proposal ${index + 1}`}
                    aria-pressed={isEditorSelection}
                    data-has-selection={readOnly ? undefined : "true"}
                    data-selected={isEditorSelection ? "true" : undefined}
                    onClick={() => onSelectCandidate(candidate)}
                  >
                    <CandidatePreview
                      candidate={candidate}
                      sourceUrl={sourceUrl}
                      frameWidth={frameWidth}
                      frameHeight={frameHeight}
                      label={`Proposal ${index + 1} crop preview`}
                    />
                    <span className={styles.proposalDetails}>
                      <strong>Proposal {index + 1}</strong>
                      <span>{statusLabel}</span>
                      <small>{formatIdentifier(candidate.side)}</small>
                      <small>{formatGeometryKind(candidate.geometry)}</small>
                    </span>
                  </button>
                  {hasMultiplePolygons ? (
                    <div
                      className={styles.proposalPolygonSelectors}
                      aria-label={`Polygons for proposal ${index + 1}`}
                    >
                      {Array.from(
                        { length: polygonCount },
                        (_, polygonIndex) => (
                          <button
                            className={styles.proposalPolygonSelector}
                            type="button"
                            key={`polygon-${polygonIndex}`}
                            aria-label={`Select polygon ${polygonIndex + 1} for proposal ${index + 1}`}
                            aria-pressed={
                              editor?.cardId === candidate.card_id
                                ? editor.polygonIndex === polygonIndex
                                : selection?.type === "polygon" &&
                                  selection.id === candidate.card_id &&
                                  selection.polygonIndex === polygonIndex
                            }
                            onClick={(event) => {
                              event.stopPropagation();
                              if (editor?.cardId === candidate.card_id) {
                                onSelectEditorPolygon?.(polygonIndex);
                              } else {
                                onSelectCandidate(candidate, polygonIndex);
                              }
                            }}
                          >
                            {polygonIndex + 1}
                          </button>
                        ),
                      )}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
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
                  <button
                    className={styles.proposalSelect}
                    type="button"
                    aria-label={`Select ignore region ${index + 1}`}
                    aria-pressed={selection?.id === region.region_id}
                    onClick={() => onSelectIgnoreRegion?.(region)}
                  >
                    <span className={styles.proposalDetails}>
                      <strong>Ignore region {index + 1}</strong>
                      <span>Untidy stack</span>
                      <small>
                        {region.geometry.polygons.length} polygon
                        {region.geometry.polygons.length === 1 ? "" : "s"}
                      </small>
                    </span>
                  </button>
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

function CandidatePreview({
  candidate,
  sourceUrl,
  frameWidth,
  frameHeight,
  label,
}: {
  candidate: Candidate;
  sourceUrl: string | null;
  frameWidth: number;
  frameHeight: number;
  label: string;
}) {
  const bounds = candidateBounds(candidate, frameWidth, frameHeight);
  if (sourceUrl === null || bounds === null) {
    return (
      <div className={styles.proposalPreviewPlaceholder} aria-hidden="true" />
    );
  }
  return (
    <svg
      className={styles.proposalPreview}
      viewBox={`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="xMidYMid slice"
    >
      <image
        href={sourceUrl}
        x="0"
        y="0"
        width={frameWidth}
        height={frameHeight}
        preserveAspectRatio="none"
      />
    </svg>
  );
}

function candidateBounds(
  candidate: Candidate,
  frameWidth: number,
  frameHeight: number,
) {
  const geometry = candidate.geometry;
  const points =
    geometry.visible_region?.polygons.flat() ??
    (geometry.box_2d === undefined
      ? []
      : [
          { x: geometry.box_2d.x_min, y: geometry.box_2d.y_min },
          { x: geometry.box_2d.x_max, y: geometry.box_2d.y_max },
        ]);
  if (points.length === 0) return null;
  const xMin = Math.max(0, Math.min(...points.map((point) => point.x)));
  const yMin = Math.max(0, Math.min(...points.map((point) => point.y)));
  const xMax = Math.min(1000, Math.max(...points.map((point) => point.x)));
  const yMax = Math.min(1000, Math.max(...points.map((point) => point.y)));
  const width = Math.max(1, ((xMax - xMin) * frameWidth) / 1000);
  const height = Math.max(1, ((yMax - yMin) * frameHeight) / 1000);
  const x = (xMin * frameWidth) / 1000;
  const y = (yMin * frameHeight) / 1000;
  return { x, y, width, height };
}

function virtualCardPreviewCandidate(
  pose: PoseCard,
  scene: PoseSceneEnvelope,
  frameWidth: number,
  frameHeight: number,
): Candidate | null {
  const polygon = posePolygon(pose, scene.projection, "camera");
  if (polygon.length !== 4 || frameWidth <= 0 || frameHeight <= 0) return null;
  return {
    card_id: pose.card_id,
    geometry: {
      kind: "virtual-card-preview/v1",
      visible_region: {
        polygons: [
          polygon.map(([x, y]) => ({
            x: clamp((x / frameWidth) * 1000, 1000),
            y: clamp((y / frameHeight) * 1000, 1000),
          })),
        ],
      },
    },
    normalization: {},
    side: "unknown",
  };
}

function formatGeometryKind(geometry: Candidate["geometry"]): string {
  if (geometry.visible_region !== undefined) return "Polygon";
  const { kind } = geometry;
  if (kind === "detector-box/v1" || kind === "reviewed-box/v1") return "Box";
  return formatIdentifier(kind);
}

function WorkbenchSurface({
  frame,
  candidates,
  scene,
  sourceUrl,
  width,
  height,
  viewpoint,
  activeTool,
  enabledLayers,
  selection,
  viewport,
  gestureViewBox,
  candidateProjection,
  calibrationFitOutlines,
  mappingAnchors,
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
  onMappingAnchorPointerDown,
  onMappingAnchorCornerSelect,
}: {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  sourceUrl: string | null;
  width: number;
  height: number;
  viewpoint: WorkbenchViewpoint;
  activeTool: WorkbenchPreferences["activeTool"];
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  viewport: { zoom: number; pan: { x: number; y: number } };
  gestureViewBox?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  candidateProjection: CardSceneProjection | null;
  calibrationFitOutlines: CalibrationFitDiagnosticOutline[];
  mappingAnchors: WorkbenchCalibrationAnchor[];
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
  onMappingAnchorPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
    sourceOffset?: TablePoint,
  ) => void;
  onMappingAnchorCornerSelect: (cornerIndex: number) => void;
}) {
  const count = frame.outcome.candidates.length;
  const proposalLabel = `${count} visible-card proposal${count === 1 ? "" : "s"}${includeIgnoreRegionCount && frame.outcome.ignored_regions.length > 0 ? ` and ${frame.outcome.ignored_regions.length} ignore region${frame.outcome.ignored_regions.length === 1 ? "" : "s"}` : ""}`;
  if (viewpoint === "rectified" && scene !== null) {
    const viewBox =
      gestureViewBox ?? tableViewBox(scene.scene, scene.projection, viewport);
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
          candidates,
          scene,
          viewpoint,
          width,
          height,
          zoom: viewport.zoom,
          activeTool,
          enabledLayers,
          selection,
          candidateProjection,
          mappingAnchors,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
          onMappingAnchorPointerDown,
          onMappingAnchorCornerSelect,
        })}
        {renderCalibrationFitOutlines(
          calibrationFitOutlines,
          viewpoint,
          width,
          height,
          scene,
          candidates,
        )}
        {renderEditorOverlay({
          editor,
          activeTool,
          viewpoint,
          width,
          height,
          scene,
          onPointPointerDown,
        })}
      </svg>
    );
  }
  const viewBox = cameraViewBox(width, height, viewport);
  return (
    <div
      className={styles.workbenchCameraViewport}
      style={
        {
          "--workbench-frame-aspect-ratio": `${width} / ${height}`,
        } as CSSProperties
      }
    >
      <svg
        className={styles.workbenchCameraSurface}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        preserveAspectRatio="xMidYMid meet"
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
              "camera",
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
              "camera",
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
          <image
            href={sourceUrl}
            x={0}
            y={0}
            width={width}
            height={height}
            preserveAspectRatio="none"
            pointerEvents="none"
            data-workbench-background="camera"
            aria-hidden="true"
          />
        ) : null}
        {renderLayers({
          frame,
          candidates,
          scene,
          viewpoint: "camera",
          width,
          height,
          zoom: viewport.zoom,
          activeTool,
          enabledLayers,
          selection,
          candidateProjection,
          mappingAnchors,
          onSelect,
          onVirtualCardPointerDown,
          onVirtualCardKeyDown,
          onMappingAnchorPointerDown,
          onMappingAnchorCornerSelect,
        })}
        {renderCalibrationFitOutlines(
          calibrationFitOutlines,
          "camera",
          width,
          height,
          scene,
          candidates,
        )}
        {renderEditorOverlay({
          editor,
          activeTool,
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

function renderCalibrationFitOutlines(
  outlines: CalibrationFitDiagnosticOutline[],
  viewpoint: WorkbenchViewpoint,
  width: number,
  height: number,
  scene: PoseSceneEnvelope | null,
  candidates: Candidate[],
) {
  return outlines.map((outline) => {
    const projectedPoints = outline.points
      .map((point): [number, number] | null => {
        if (viewpoint === "camera" || scene === null) return [point.x, point.y];
        return projectImagePointToTable(
          [point.x, point.y],
          scene.projection.table_to_image_homography,
        );
      })
      .filter((point): point is [number, number] => point !== null);
    const candidate = candidates.find(
      (item) => item.card_id === outline.candidateId,
    );
    const points =
      projectedPoints.length >= 4
        ? projectedPoints
        : candidate === undefined
          ? []
          : (candidatePolygons(candidate, width, height, viewpoint, scene)[0] ??
            []);
    if (points.length < 3) return null;
    const minX = Math.min(...points.map(([x]) => x));
    const minY = Math.min(...points.map(([, y]) => y));
    const fontSize = viewpoint === "camera" ? Math.max(13, width / 110) : 0.14;
    const labelX = Math.max(0, minX);
    const labelY = Math.max(fontSize * 2, minY);
    const statusLabel =
      outline.status === "fit"
        ? "FIT"
        : outline.status === "held_out"
          ? "HELD OUT"
          : "DISCARDED";
    const metricLabel =
      outline.medianDistancePx === null
        ? "boundary metric unavailable"
        : `M/P90/MAX ${outline.medianDistancePx.toFixed(1)}/${outline.p90DistancePx?.toFixed(1) ?? "–"}/${outline.maximumDistancePx?.toFixed(1) ?? "–"} px`;
    const detailLabel =
      outline.status === "discarded" && outline.reason !== null
        ? outline.reason.replaceAll("_", " ")
        : `confidence ${outline.confidence?.toFixed(2) ?? "–"} · quality ${outline.qualityScore?.toFixed(2) ?? "–"}`;
    const title = [
      outline.candidateId,
      statusLabel,
      outline.reason === null
        ? null
        : `Reason: ${outline.reason.replaceAll("_", " ")}`,
      outline.confidence === null
        ? null
        : `Confidence: ${outline.confidence.toFixed(3)}`,
      outline.qualityScore === null
        ? null
        : `Quality score: ${outline.qualityScore.toFixed(3)}`,
      outline.medianDistancePx === null
        ? null
        : `Boundary distance: median ${outline.medianDistancePx.toFixed(2)} px, P90 ${outline.p90DistancePx?.toFixed(2) ?? "unavailable"} px, max ${outline.maximumDistancePx?.toFixed(2) ?? "unavailable"} px`,
    ]
      .filter((item) => item !== null)
      .join("\n");
    return (
      <g
        key={outline.candidateId}
        data-calibration-fit-outline="true"
        data-candidate-id={outline.candidateId}
        data-calibration-status={outline.status}
        role="img"
        aria-label={`${statusLabel.toLowerCase()} calibration card ${outline.candidateId}: ${metricLabel}`}
      >
        <title>{title}</title>
        <polygon
          className={styles.calibrationFitOutline}
          points={pointsAttribute(points)}
          strokeWidth={strokeWidth(viewpoint, width)}
          data-status={outline.status}
          data-geometry={projectedPoints.length >= 4 ? "fitted" : "detected"}
        />
        <text
          className={styles.calibrationFitLabel}
          x={labelX}
          y={labelY}
          fontSize={fontSize}
          data-status={outline.status}
        >
          <tspan x={labelX}>{statusLabel}</tspan>
          <tspan x={labelX} dy="1.15em">
            {metricLabel}
          </tspan>
          <tspan x={labelX} dy="1.15em">
            {detailLabel}
          </tspan>
        </text>
      </g>
    );
  });
}

type LayerRenderContext = {
  frame: EditableFrame;
  candidates: Candidate[];
  scene: PoseSceneEnvelope | null;
  viewpoint: WorkbenchViewpoint;
  width: number;
  height: number;
  zoom: number;
  activeTool: WorkbenchPreferences["activeTool"];
  enabledLayers: WorkbenchLayer[];
  selection: WorkbenchSelection | null;
  candidateProjection: CardSceneProjection | null;
  mappingAnchors: WorkbenchCalibrationAnchor[];
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
  onMappingAnchorPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
    sourceOffset?: TablePoint,
  ) => void;
  onMappingAnchorCornerSelect: (cornerIndex: number) => void;
};

function renderEditorOverlay({
  editor,
  activeTool,
  viewpoint,
  width,
  height,
  scene,
  onPointPointerDown,
}: {
  editor: EditorState | null;
  activeTool: WorkbenchPreferences["activeTool"];
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
    <g
      data-workbench-editor="visible-regions"
      pointerEvents={activeTool === "mapping" ? "none" : undefined}
    >
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
  const scale = Math.min(
    rect.width / viewBox.width,
    rect.height / viewBox.height,
  );
  if (!Number.isFinite(scale) || scale <= 0) return null;
  const contentWidth = viewBox.width * scale;
  const contentHeight = viewBox.height * scale;
  const offsetX = (rect.width - contentWidth) / 2;
  const offsetY = (rect.height - contentHeight) / 2;
  const displayX = viewBox.x + (event.clientX - rect.left - offsetX) / scale;
  const displayY = viewBox.y + (event.clientY - rect.top - offsetY) / scale;
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

function readCalibrationAnchors(
  refinement: CalibrationRefinementResponse | null,
  frameId: string,
  eventId: string,
  sceneFrameId: string | null,
): WorkbenchCalibrationAnchor[] {
  if (refinement === null || !Array.isArray(refinement.draft.anchors))
    return [];
  const frameIds = new Set([frameId, eventId, sceneFrameId].filter(Boolean));
  return refinement.draft.anchors.flatMap((raw) => {
    if (!isRecord(raw)) return [];
    const anchorId = readString(raw.anchor_id);
    const cardId = readString(raw.card_id);
    const sourceFrameId = readString(raw.source_frame_id);
    const state = readAnchorState(raw.state);
    const corners = readTablePoints(raw.quadrilateral);
    if (
      anchorId === null ||
      cardId === null ||
      sourceFrameId === null ||
      state === null ||
      corners === null ||
      !frameIds.has(sourceFrameId)
    )
      return [];
    return [
      {
        anchorId,
        cardId,
        sourceFrameId,
        eligible: raw.eligible === true,
        state,
        corners,
      },
    ];
  });
}

function calibrationDraftRevision(
  refinement: CalibrationRefinementResponse | null,
): number {
  const revision = refinement?.draft.revision;
  return typeof revision === "number" &&
    Number.isInteger(revision) &&
    revision >= 0
    ? revision
    : 0;
}

function calibrationCommandCount(
  refinement: CalibrationRefinementResponse | null,
): number {
  return Array.isArray(refinement?.draft.commands)
    ? refinement.draft.commands.length
    : 0;
}

function readAnchorState(value: unknown): AnchorState | null {
  return typeof value === "string" &&
    (ANCHOR_STATES as readonly string[]).includes(value)
    ? (value as AnchorState)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readTablePoints(value: unknown): TablePoint[] | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const points = value.map((raw) => {
    if (!Array.isArray(raw) || raw.length !== 2) return null;
    const x = raw[0];
    const y = raw[1];
    return typeof x === "number" &&
      Number.isFinite(x) &&
      typeof y === "number" &&
      Number.isFinite(y)
      ? ([x, y] as TablePoint)
      : null;
  });
  return points.every((point): point is TablePoint => point !== null)
    ? points
    : null;
}

function cloneTablePoints(points: TablePoint[]): TablePoint[] {
  return points.map(([x, y]) => [x, y]);
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
  const layerOrder =
    context.activeTool === "mapping"
      ? [
          ...WORKBENCH_LAYER_DRAW_ORDER.filter((layer) => layer !== "mapping"),
          "mapping" as const,
        ]
      : WORKBENCH_LAYER_DRAW_ORDER;
  return layerOrder
    .filter((layer) => context.enabledLayers.includes(layer))
    .map((layer) => {
      const entry = registry.get(layer);
      return entry === undefined ? null : (
        <g
          key={layer}
          data-workbench-layer={layer}
          pointerEvents={
            context.activeTool === "mapping" && layer !== "mapping"
              ? "none"
              : undefined
          }
        >
          {entry.render(context)}
        </g>
      );
    });
}

function renderVisibleRegionLayer({
  candidates,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return candidates.flatMap((candidate) =>
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
  candidates,
  viewpoint,
  scene,
  width,
  height,
  selection,
  onSelect,
}: LayerRenderContext) {
  return candidates.flatMap((candidate) =>
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
  zoom,
  selection,
  onSelect,
  onVirtualCardPointerDown,
  onVirtualCardKeyDown,
}: LayerRenderContext) {
  if (scene === null) return null;
  const orderedPoses = renderOrder(scene.scene, selection);
  const badges = orderedPoses.map((pose) => {
    const index = scene.scene.stacking_order.card_ids.indexOf(pose.card_id);
    const polygon = posePolygon(pose, scene.projection, viewpoint);
    if (index < 0 || polygon.length === 0) return null;
    const [start, edgeEnd, inwardEnd] = polygon;
    const edge = [edgeEnd[0] - start[0], edgeEnd[1] - start[1]];
    const inward = [inwardEnd[0] - edgeEnd[0], inwardEnd[1] - edgeEnd[1]];
    const x = start[0] + edge[0] * 0.12 + inward[0] * 0.1;
    const y = start[1] + edge[1] * 0.12 + inward[1] * 0.1;
    const radius =
      viewpoint === "camera"
        ? Math.max(12, width / 55) / Math.max(zoom, 0.01)
        : Math.max(0.08, scene.projection.card_short_size * 0.12) /
          Math.max(zoom, 0.01);
    return { cardId: pose.card_id, index, x, y, radius };
  });
  return (
    <>
      {orderedPoses.map((pose) => {
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
      })}
      <g
        data-card-stacking-badges="true"
        pointerEvents="none"
        aria-hidden="true"
      >
        {badges.map((badge) =>
          badge === null ? null : (
            <g
              key={badge.cardId}
              data-stacking-badge-id={badge.cardId}
              data-stacking-index={badge.index}
            >
              <circle
                cx={badge.x}
                cy={badge.y}
                r={badge.radius}
                fill="#14252b"
                stroke="#ffffff"
                strokeWidth={
                  (viewpoint === "camera" ? Math.max(1, width / 500) : 0.08) /
                  Math.max(zoom, 0.01)
                }
              />
              <text
                x={badge.x}
                y={badge.y}
                fill="#ffffff"
                fontSize={badge.radius * 1.15}
                fontWeight="800"
                textAnchor="middle"
                dominantBaseline="central"
              >
                {badge.index + 1}
              </text>
            </g>
          ),
        )}
      </g>
    </>
  );
}

function renderMappingLayer({
  scene,
  viewpoint,
  candidateProjection,
  width,
  zoom,
  mappingAnchors,
  selection,
  onSelect,
  onMappingAnchorPointerDown,
  onMappingAnchorCornerSelect,
}: LayerRenderContext) {
  if (scene === null && mappingAnchors.length === 0) return null;
  const orderedAnchors = [
    ...mappingAnchors.filter(
      (anchor) =>
        !isSelected(selection, {
          type: "calibration_anchor",
          id: anchor.anchorId,
        }),
    ),
    ...mappingAnchors.filter((anchor) =>
      isSelected(selection, {
        type: "calibration_anchor",
        id: anchor.anchorId,
      }),
    ),
  ];
  if (scene === null) {
    return orderedAnchors.map((anchor) => (
      <MappingAnchorOverlay
        key={anchor.anchorId}
        anchor={anchor}
        viewpoint={viewpoint}
        projection={null}
        width={width}
        zoom={zoom}
        selected={isSelected(selection, {
          type: "calibration_anchor",
          id: anchor.anchorId,
        })}
        onSelect={onSelect}
        onPointerDown={onMappingAnchorPointerDown}
        onSelectCorner={onMappingAnchorCornerSelect}
      />
    ));
  }
  const currentProjection = scene.projection;
  const current = scene.scene.poses.map((pose) => (
    <MappingProjection
      key={`${pose.card_id}-current`}
      pose={pose}
      projection={currentProjection}
      viewpoint={viewpoint}
      width={width}
      zoom={zoom}
      stroke="#ff8a65"
      dataProjection="current"
      anchor={mappingAnchors.find(
        (item) =>
          item.cardId === pose.card_id ||
          (pose.source_suggestion_id !== null &&
            item.cardId === pose.source_suggestion_id),
      )}
      onSelect={onSelect}
      onSelectCorner={onMappingAnchorCornerSelect}
      onPointerDown={onMappingAnchorPointerDown}
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
            zoom={zoom}
            stroke="#ffd166"
            dataProjection="candidate"
            polygonOverride={candidatePosePolygon(
              pose,
              currentProjection,
              candidateProjection,
              viewpoint,
            )}
          />
        ));
  return (
    <>
      {current}
      {candidate}
      {orderedAnchors.map((anchor) => (
        <MappingAnchorOverlay
          key={anchor.anchorId}
          anchor={anchor}
          viewpoint={viewpoint}
          projection={currentProjection}
          width={width}
          zoom={zoom}
          selected={isSelected(selection, {
            type: "calibration_anchor",
            id: anchor.anchorId,
          })}
          onSelect={onSelect}
          onPointerDown={onMappingAnchorPointerDown}
          onSelectCorner={onMappingAnchorCornerSelect}
        />
      ))}
    </>
  );
}

function MappingAnchorOverlay({
  anchor,
  viewpoint,
  projection,
  width,
  zoom,
  selected,
  onSelect,
  onSelectCorner,
  onPointerDown,
}: {
  anchor: WorkbenchCalibrationAnchor;
  viewpoint: WorkbenchViewpoint;
  projection: CardSceneProjection | null;
  width: number;
  zoom: number;
  selected: boolean;
  onSelect: (selection: WorkbenchSelection) => void;
  onSelectCorner: (cornerIndex: number) => void;
  onPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
  ) => void;
}) {
  const corners =
    projection === null || viewpoint === "camera"
      ? anchor.corners
      : anchor.corners
          .map((point) =>
            projectImagePointToTable(
              point,
              projection.table_to_image_homography,
            ),
          )
          .filter((point): point is TablePoint => point !== null);
  return (
    <g data-anchor-id={anchor.anchorId} data-anchor-state={anchor.state}>
      {corners.length === 4 ? (
        <polygon
          points={pointsAttribute(corners)}
          fill="none"
          stroke={selected ? "#ffffff" : "#ff8a65"}
          strokeDasharray={selected ? undefined : "4 3"}
          strokeWidth={mappingStrokeWidth(viewpoint, width, zoom)}
          opacity={0.5}
          pointerEvents="stroke"
          role="button"
          tabIndex={0}
          aria-label={`Select calibration anchor ${anchor.anchorId}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "calibration_anchor", id: anchor.anchorId });
          }}
        />
      ) : null}
      {corners.map(([x, y], index) => (
        <circle
          key={`${anchor.anchorId}-${index}`}
          cx={x}
          cy={y}
          r={mappingCornerRadius(
            viewpoint,
            width,
            zoom,
            Math.max(0.05, (projection?.card_short_size ?? 1) * 0.08),
          )}
          fill={selected ? "#ffffff" : "#ff8a65"}
          stroke="#18242f"
          strokeWidth={mappingStrokeWidth(viewpoint, width, zoom) / 2}
          opacity={0.5}
          data-mapping-anchor={index}
          role="button"
          tabIndex={0}
          aria-label={`Adjust calibration anchor ${index + 1} for ${anchor.anchorId}`}
          onClick={(event) => {
            event.stopPropagation();
            onSelect({ type: "calibration_anchor", id: anchor.anchorId });
            onSelectCorner(index);
          }}
          onPointerDown={(event) => onPointerDown?.(event, anchor, index)}
        />
      ))}
    </g>
  );
}

function MappingProjection({
  pose,
  projection,
  viewpoint,
  width,
  zoom,
  stroke,
  dataProjection,
  polygonOverride,
  anchor,
  onSelect,
  onSelectCorner,
  onPointerDown,
}: {
  pose: PoseCard;
  projection: CardSceneProjection;
  viewpoint: WorkbenchViewpoint;
  width: number;
  zoom: number;
  stroke: string;
  dataProjection: "current" | "candidate";
  polygonOverride?: TablePoint[];
  anchor?: WorkbenchCalibrationAnchor;
  onSelect?: (selection: WorkbenchSelection) => void;
  onSelectCorner?: (cornerIndex: number) => void;
  onPointerDown?: (
    event: ReactPointerEvent<SVGCircleElement>,
    anchor: WorkbenchCalibrationAnchor,
    cornerIndex: number,
    sourceOffset?: TablePoint,
  ) => void;
}) {
  const polygon = polygonOverride ?? posePolygon(pose, projection, viewpoint);
  const anchorCornerIndices =
    anchor === undefined
      ? null
      : matchProjectionCornersToAnchor(
          polygon,
          anchor.corners,
          projection,
          viewpoint,
        );
  return (
    <g data-projection={dataProjection} data-card-id={pose.card_id}>
      <polygon
        points={pointsAttribute(polygon)}
        fill="none"
        stroke={stroke}
        strokeDasharray={dataProjection === "candidate" ? "8 5" : undefined}
        strokeWidth={mappingStrokeWidth(viewpoint, width, zoom)}
        opacity={0.5}
        pointerEvents="none"
      />
      {dataProjection === "current"
        ? polygon.map(([x, y], index) => {
            const imagePoint =
              viewpoint === "camera"
                ? ([x, y] as TablePoint)
                : projectTablePoint(
                    [x, y],
                    projection.table_to_image_homography,
                  );
            const anchorCornerIndex = anchorCornerIndices?.[index];
            const anchorCorner =
              anchorCornerIndex === undefined
                ? undefined
                : anchor?.corners[anchorCornerIndex];
            if (imagePoint === null) return null;
            return (
              <circle
                key={index}
                cx={x}
                cy={y}
                r={mappingCornerRadius(
                  viewpoint,
                  width,
                  zoom,
                  Math.max(0.05, projection.card_short_size * 0.08),
                )}
                fill={stroke}
                stroke="#18242f"
                strokeWidth={mappingStrokeWidth(viewpoint, width, zoom) / 2}
                pointerEvents={anchorCorner === undefined ? "none" : undefined}
                role={anchorCorner === undefined ? undefined : "button"}
                tabIndex={anchorCorner === undefined ? undefined : 0}
                aria-label={
                  anchorCorner === undefined
                    ? undefined
                    : `Adjust mapped card corner ${index + 1} for ${pose.card_id}`
                }
                onClick={(event) => {
                  event.stopPropagation();
                  if (anchor !== undefined && anchorCornerIndex !== undefined) {
                    onSelect?.({
                      type: "calibration_anchor",
                      id: anchor.anchorId,
                    });
                    onSelectCorner?.(anchorCornerIndex);
                  }
                }}
                onPointerDown={(event) => {
                  if (
                    anchor !== undefined &&
                    anchorCornerIndex !== undefined &&
                    anchorCorner !== undefined
                  )
                    onPointerDown?.(event, anchor, anchorCornerIndex, [
                      anchorCorner[0] - imagePoint[0],
                      anchorCorner[1] - imagePoint[1],
                    ]);
                }}
              />
            );
          })
        : null}
    </g>
  );
}

function matchProjectionCornersToAnchor(
  polygon: TablePoint[],
  anchorCorners: TablePoint[],
  projection: CardSceneProjection,
  viewpoint: WorkbenchViewpoint,
): number[] | null {
  if (polygon.length !== 4 || anchorCorners.length !== 4) return null;
  const projected =
    viewpoint === "camera"
      ? polygon
      : polygon.map((point) =>
          projectTablePoint(point, projection.table_to_image_homography),
        );
  if (projected.some((point) => point === null)) return null;
  let best: number[] | null = null;
  let bestDistance = Infinity;
  for (let a = 0; a < 4; a++)
    for (let b = 0; b < 4; b++)
      for (let c = 0; c < 4; c++)
        for (let d = 0; d < 4; d++) {
          const order = [a, b, c, d];
          if (new Set(order).size !== 4) continue;
          const distance = order.reduce((sum, anchorIndex, index) => {
            const point = projected[index]!;
            const corner = anchorCorners[anchorIndex];
            return sum + Math.hypot(point[0] - corner[0], point[1] - corner[1]);
          }, 0);
          if (distance < bestDistance) {
            bestDistance = distance;
            best = order;
          }
        }
  return best;
}

function mappingStrokeWidth(
  viewpoint: WorkbenchViewpoint,
  width: number,
  zoom: number,
): number {
  return strokeWidth(viewpoint, width) / Math.max(zoom, 0.01);
}

function mappingCornerRadius(
  viewpoint: WorkbenchViewpoint,
  width: number,
  zoom: number,
  rectifiedRadius: number,
): number {
  const radius =
    viewpoint === "camera" ? Math.max(4, width / 110) : rectifiedRadius;
  return radius / Math.max(zoom, 0.01);
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

function candidateNormalizedPolygons(candidate: Candidate): Point[][] {
  if (candidate.geometry.visible_region !== undefined) {
    return candidate.geometry.visible_region.polygons.map((polygon) =>
      polygon.map((point) => ({ x: point.x, y: point.y })),
    );
  }
  const box = candidate.geometry.box_2d;
  return box === undefined
    ? []
    : [
        [
          { x: box.x_min, y: box.y_min },
          { x: box.x_max, y: box.y_min },
          { x: box.x_max, y: box.y_max },
          { x: box.x_min, y: box.y_max },
        ],
      ];
}

function candidateIsCoveredByIgnoreRegions(
  candidate: Candidate,
  regions: IgnoreRegion[],
): boolean {
  if (regions.length === 0) return false;
  if (
    regions.some((region) =>
      region.source_candidates.some(
        (source) => source.card_id === candidate.card_id,
      ),
    )
  ) {
    return true;
  }
  const containers = regions.flatMap((region) => region.geometry.polygons);
  const polygons = candidateNormalizedPolygons(candidate);
  if (polygons.length === 0 || containers.length === 0) return false;
  return polygons.some((polygon) =>
    containers.some((container) =>
      polygonsOverlapForIgnore(polygon, container),
    ),
  );
}

function polygonsOverlapForIgnore(left: Point[], right: Point[]): boolean {
  if (left.length < 3 || right.length < 3) return false;
  if (polygonsMatch(left, right)) return true;
  const leftCentroid = polygonCentroid(left);
  const rightCentroid = polygonCentroid(right);
  if (
    pointInPolygon(leftCentroid, right) ||
    pointInPolygon(rightCentroid, left)
  ) {
    return true;
  }
  return (
    vertexOverlapRatio(left, right) >= 0.45 ||
    vertexOverlapRatio(right, left) >= 0.45
  );
}

function vertexOverlapRatio(source: Point[], container: Point[]): number {
  if (source.length === 0) return 0;
  const hits = source.filter((point) =>
    pointInPolygon(point, container),
  ).length;
  return hits / source.length;
}

function polygonCentroid(polygon: Point[]): Point {
  const total = polygon.reduce(
    (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
    { x: 0, y: 0 },
  );
  return { x: total.x / polygon.length, y: total.y / polygon.length };
}

function polygonsMatch(left: Point[], right: Point[]): boolean {
  if (left.length !== right.length) return false;
  return left.every(
    (point, index) =>
      Math.abs(point.x - right[index].x) < 1e-6 &&
      Math.abs(point.y - right[index].y) < 1e-6,
  );
}

function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  for (
    let index = 0, previous = polygon.length - 1;
    index < polygon.length;
    previous = index, index += 1
  ) {
    const current = polygon[index];
    const prior = polygon[previous];
    const crosses =
      current.y > point.y !== prior.y > point.y &&
      point.x <
        ((prior.x - current.x) * (point.y - current.y)) /
          (prior.y - current.y + Number.EPSILON) +
          current.x;
    if (crosses) inside = !inside;
  }
  return inside;
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

function candidatePosePolygon(
  pose: PoseCard,
  currentProjection: CardSceneProjection,
  candidateProjection: CardSceneProjection,
  viewpoint: WorkbenchViewpoint,
): TablePoint[] {
  const sourceCorners = posePolygon(pose, currentProjection, "camera");
  const candidateCorners = sourceCorners.map((point) =>
    projectImagePointToTable(
      point,
      candidateProjection.table_to_image_homography,
    ),
  );
  if (candidateCorners.some((point) => point === null)) return [];
  const corners = candidateCorners as TablePoint[];
  const center: TablePoint = [
    corners.reduce((sum, point) => sum + point[0], 0) / 4,
    corners.reduce((sum, point) => sum + point[1], 0) / 4,
  ];
  const shortAxis: TablePoint = [
    corners[1][0] - corners[0][0] + corners[2][0] - corners[3][0],
    corners[1][1] - corners[0][1] + corners[2][1] - corners[3][1],
  ];
  const candidatePose = {
    ...pose,
    center,
    rotation_degrees: (Math.atan2(shortAxis[1], shortAxis[0]) * 180) / Math.PI,
  };
  const candidateImage = posePolygon(
    candidatePose,
    candidateProjection,
    "camera",
  );
  if (viewpoint === "camera") return candidateImage;
  return candidateImage
    .map((point) =>
      projectImagePointToTable(
        point,
        currentProjection.table_to_image_homography,
      ),
    )
    .filter((point): point is TablePoint => point !== null);
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

function cameraViewBox(
  frameWidth: number,
  frameHeight: number,
  viewport: { zoom: number; pan: { x: number; y: number } },
): { x: number; y: number; width: number; height: number } {
  const zoom = Math.max(viewport.zoom, 0.01);
  const width = frameWidth / zoom;
  const height = frameHeight / zoom;
  const centerX = frameWidth / 2 + viewport.pan.x;
  const centerY = frameHeight / 2 + viewport.pan.y;
  return { x: centerX - width / 2, y: centerY - height / 2, width, height };
}

function surfaceViewBox(
  viewpoint: WorkbenchViewpoint,
  frameWidth: number,
  frameHeight: number,
  scene: PoseSceneEnvelope | null,
  viewport: { zoom: number; pan: { x: number; y: number } },
): { x: number; y: number; width: number; height: number } | null {
  if (viewpoint === "rectified" && scene !== null) {
    return tableViewBox(scene.scene, scene.projection, viewport);
  }
  if (viewpoint === "camera") {
    return cameraViewBox(frameWidth, frameHeight, viewport);
  }
  return null;
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
