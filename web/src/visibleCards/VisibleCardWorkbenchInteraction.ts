import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from "react";
import type { CalibrationRefinementResponse } from "../api/client";
import { ignoresReviewNavigationShortcut } from "../reviewNavigation";
import type { WorkbenchCalibrationAnchor } from "./VisibleCardWorkbenchControls";
import {
  applyPoseSceneAction,
  createCalibrationAnchorCommand,
  createCalibrationAnchorStateCommand,
  moveAnchorCorner,
  type AnchorState,
  type CalibrationAnchorCommand,
  type PoseSceneEnvelope,
  type TablePoint,
} from "./PoseBasedVisibleCardScene";
import type { Point } from "./PipelineVisibleCardTypes";
import {
  calibrationCommandCount,
  calibrationDraftRevision,
  cloneTablePoints,
} from "./VisibleCardWorkbenchSurface";
import {
  sourcePoint,
  sourcePointToTablePoint,
  surfaceViewBox,
} from "./VisibleCardWorkbenchSurfaceGeometry";
import {
  workbenchViewportShortcut,
  type WorkbenchAction,
  type WorkbenchSelection,
  type VisibleCardReviewWorkbenchState,
  type WorkbenchViewport,
} from "./VisibleCardReviewWorkbenchState";

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
  moveOffset?: TablePoint;
};

type MappingGesture = {
  pointerId: number;
  anchorId: string;
  movedCorner: number;
  dirty: boolean;
  startClientX: number;
  startClientY: number;
  originalCorners: TablePoint[];
};

export type MappingWorkbenchAction =
  | "accept_anchor"
  | "exclude_anchor"
  | "start_mapping_preview"
  | "discard_mapping_preview";

type WorkbenchPointHandler = (
  event: ReactPointerEvent<SVGSVGElement>,
  point: Point | null,
) => void;

type InteractionOptions = {
  readOnly: boolean;
  activeState: VisibleCardReviewWorkbenchState;
  pileRegionEditorActive: boolean;
  viewport: WorkbenchViewport;
  width: number;
  height: number;
  frameId: string;
  calibrationRefinement: CalibrationRefinementResponse | null;
  mappingAnchors: WorkbenchCalibrationAnchor[];
  selectedMappingAnchor: WorkbenchCalibrationAnchor | null;
  sceneDraftRef: MutableRefObject<PoseSceneEnvelope | null>;
  setSceneDraft: (scene: PoseSceneEnvelope | null) => void;
  commitScene: (scene: PoseSceneEnvelope, notice: string) => void;
  applySceneAction: (
    action: Parameters<typeof applyPoseSceneAction>[1],
    notice: string,
  ) => void;
  select: (selection: WorkbenchSelection) => void;
  clearSelection: () => void;
  dispatch: (action: WorkbenchAction) => void;
  onAnchorCommand?: (
    command: CalibrationAnchorCommand,
  ) => Promise<boolean> | void;
  onStartMappingPreview?: () => void;
  onDiscardMappingPreview?: () => void;
  onCanvasPointerDown?: WorkbenchPointHandler;
  onPointerMove?: WorkbenchPointHandler;
  onPointerUp?: (event: ReactPointerEvent<SVGSVGElement>) => void;
  onPointerCancel?: (event: ReactPointerEvent<SVGSVGElement>) => void;
};

export function useVisibleCardWorkbenchInteraction({
  readOnly,
  activeState,
  pileRegionEditorActive,
  viewport,
  width,
  height,
  frameId,
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
}: InteractionOptions) {
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
  const setAnchorPreviewState = (next: WorkbenchCalibrationAnchor | null) => {
    anchorPreviewRef.current = next;
    setAnchorPreview(next);
  };
  const removeVirtualCard = useCallback(
    (cardId: string) => {
      if (
        readOnly ||
        activeState.activeTool !== "virtual_cards" ||
        activeState.selection?.type !== "virtual_card" ||
        activeState.selection.id !== cardId
      )
        return false;
      const scene = sceneDraftRef.current;
      if (scene === null) return false;
      if (scene.scene.poses.length <= 1) return true;
      const nextSelection = scene.scene.poses.find(
        (pose) => pose.card_id !== cardId,
      );
      applySceneAction(
        { type: "remove", cardId },
        "Card removed from the virtual table.",
      );
      if (nextSelection === undefined) clearSelection();
      else select({ type: "virtual_card", id: nextSelection.card_id });
      return true;
    },
    [
      activeState.activeTool,
      activeState.selection,
      applySceneAction,
      clearSelection,
      readOnly,
      sceneDraftRef,
      select,
    ],
  );
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Backspace" ||
        ignoresReviewNavigationShortcut(event.target) ||
        readOnly ||
        activeState.activeTool !== "virtual_cards" ||
        activeState.selection?.type !== "virtual_card"
      )
        return;
      if (!removeVirtualCard(activeState.selection.id)) return;
      event.preventDefault();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    activeState.activeTool,
    activeState.selection,
    readOnly,
    removeVirtualCard,
  ]);
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
    if (
      readOnly ||
      activeState.activeTool !== "virtual_cards" ||
      pileRegionEditorActive
    )
      return;
    if (
      event.key === "Backspace" &&
      activeState.selection?.type === "virtual_card" &&
      activeState.selection.id === cardId
    ) {
      if (!removeVirtualCard(cardId)) return;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
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
        command_id: `anchor-command-${frameId}-${context.sequence}`,
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
    const corners = moveAnchorCorner(
      gesture.originalCorners,
      gesture.movedCorner,
      sourcePoint(point, width, height),
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
        command_id: `anchor-command-${frameId}-${context.sequence}`,
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
      pileRegionEditorActive ||
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
    const pose = sceneDraftRef.current.scene.poses.find(
      (candidate) => candidate.card_id === cardId,
    );
    const surface = event.currentTarget.ownerSVGElement;
    const rect = surface?.getBoundingClientRect();
    let moveOffset: TablePoint | undefined;
    if (
      kind === "move" &&
      pose !== undefined &&
      rect &&
      rect.width > 0 &&
      rect.height > 0
    ) {
      const scale = Math.min(
        rect.width / startViewBox.width,
        rect.height / startViewBox.height,
      );
      if (Number.isFinite(scale) && scale > 0) {
        const displayX =
          startViewBox.x +
          (event.clientX -
            rect.left -
            (rect.width - startViewBox.width * scale) / 2) /
            scale;
        const displayY =
          startViewBox.y +
          (event.clientY -
            rect.top -
            (rect.height - startViewBox.height * scale) / 2) /
            scale;
        const pointerTablePoint =
          activeState.viewpoint === "rectified"
            ? ([displayX, displayY] as TablePoint)
            : sourcePointToTablePoint(
                {
                  x: (displayX / width) * 1000,
                  y: (displayY / height) * 1000,
                },
                width,
                height,
                sceneDraftRef.current,
              );
        if (pointerTablePoint !== null) {
          moveOffset = [
            pose.center[0] - pointerTablePoint[0],
            pose.center[1] - pointerTablePoint[1],
          ];
        }
      }
    }
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
      moveOffset,
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
        (activeState.activeTool === "virtual_cards" &&
          !pileRegionEditorActive) ||
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
        ? {
            type: "move",
            cardId: gesture.cardId,
            center: [
              tablePoint[0] + (gesture.moveOffset?.[0] ?? 0),
              tablePoint[1] + (gesture.moveOffset?.[1] ?? 0),
            ],
          }
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
            command_id: `anchor-command-${frameId}-${context.sequence}`,
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
      if (
        !gesture.dirty &&
        (activeState.activeTool === "visible_regions" ||
          (activeState.activeTool === "virtual_cards" &&
            pileRegionEditorActive))
      ) {
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

  return {
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
  };
}
