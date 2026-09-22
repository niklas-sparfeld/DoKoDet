import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";

import styles from "./PipelineVisibleCardEditor.module.css";
import { pipelineDerivedFramePath } from "../api/client";
import {
  ANCHOR_CONSTRAINTS,
  applyPoseSceneAction,
  cardPolygon,
  constrainAnchorQuad,
  createCalibrationAnchorCommand,
  nextManualPoseId,
  projectImagePointToTable,
  projectTablePoint,
  withSceneDigest,
  type AnchorConstraint,
  type CalibrationAnchorCommand,
  type CardSceneProjection,
  type PoseCard,
  type PoseSceneEnvelope,
  type ReviewedCardScene,
  type TablePoint,
} from "./PoseBasedVisibleCardScene";
import type { Candidate, EditableFrame } from "./PipelineVisibleCardTypes";

type PoseBasedVisibleCardEditorProps = {
  recordingId: string;
  frame: EditableFrame;
  scene: PoseSceneEnvelope;
  readOnly: boolean;
  activeView?: GestureView;
  onActiveViewChange?: (view: GestureView) => void;
  tableViewState?: VirtualTableViewState;
  onTableViewStateChange?: (state: VirtualTableViewState) => void;
  onChange: (scene: PoseSceneEnvelope, notice: string) => void;
  onCardDecision?: (cardId: string, decision: "accept" | "reject") => void;
  onResolveRemaining?: () => void;
  onAnchorCommand?: (command: CalibrationAnchorCommand) => void;
  candidateCalibration?: {
    table_to_image: number[][];
    card_short_size: number;
    card_long_size: number;
  } | null;
};

export type VirtualTableViewState = {
  zoom: number;
  pan: TablePoint;
};

type TableViewBox = { x: number; y: number; width: number; height: number };
type EditorMode = "review" | "refine";
type GestureKind = "move" | "rotate" | "anchor" | "pan";
type GestureView = "source" | "rectified";
type AnchorPreview = {
  cardId: string;
  movedCorner: number;
  constraint: AnchorConstraint;
  corners: TablePoint[];
};
type ActiveGesture = {
  pointerId: number;
  cardId: string | null;
  kind: GestureKind;
  view: GestureView;
  dirty: boolean;
  startClientX: number;
  startClientY: number;
  originalDraft: PoseSceneEnvelope;
  originalCorners?: TablePoint[];
  movedCorner?: number;
  constraint?: AnchorConstraint;
  startPan?: TablePoint;
  startViewBox?: TableViewBox;
};

const DRAG_THRESHOLD_PX = 4;
const RECTIFIED_BACKGROUND_GRID_SIZE = 12;

export function PoseBasedVisibleCardEditor({
  recordingId,
  frame,
  scene,
  readOnly,
  activeView: activeViewProp,
  onActiveViewChange,
  tableViewState,
  onTableViewStateChange,
  onChange,
  onCardDecision,
  onResolveRemaining,
  onAnchorCommand,
  candidateCalibration = null,
}: PoseBasedVisibleCardEditorProps) {
  const identity = frame.outcome.frame_identity;
  const width = identity?.width ?? scene.scene.source_frame_width;
  const height = identity?.height ?? scene.scene.source_frame_height;
  const sourceUrl =
    identity === null
      ? null
      : pipelineDerivedFramePath(recordingId, identity.requested_time_us);
  const sceneIdentity = `${frame.itemId}:${scene.scene.scene_digest}`;
  const [draftOverride, setDraftOverride] = useState<{
    identity: string;
    scene: PoseSceneEnvelope;
  } | null>(null);
  const draft =
    draftOverride?.identity === sceneIdentity ? draftOverride.scene : scene;
  const setDraft = useCallback(
    (next: PoseSceneEnvelope) =>
      setDraftOverride({ identity: sceneIdentity, scene: next }),
    [sceneIdentity],
  );
  const draftRef = useRef(draft);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(
    scene.scene.poses[0]?.card_id ?? null,
  );
  const [internalZoom, setInternalZoom] = useState(1);
  const [internalPan, setInternalPan] = useState<TablePoint>([0, 0]);
  const zoom = tableViewState?.zoom ?? internalZoom;
  const pan = tableViewState?.pan ?? internalPan;
  const updateTableViewState = useCallback(
    (next: VirtualTableViewState) => {
      if (tableViewState !== undefined) {
        onTableViewStateChange?.(next);
      } else {
        setInternalZoom(next.zoom);
        setInternalPan(next.pan);
      }
    },
    [onTableViewStateChange, tableViewState],
  );
  const setZoom = useCallback(
    (next: number | ((value: number) => number)) => {
      const resolved = typeof next === "function" ? next(zoom) : next;
      updateTableViewState({ zoom: resolved, pan });
    },
    [pan, updateTableViewState, zoom],
  );
  const setPan = useCallback(
    (next: TablePoint | ((value: TablePoint) => TablePoint)) => {
      const resolved = typeof next === "function" ? next(pan) : next;
      updateTableViewState({ zoom, pan: resolved });
    },
    [pan, updateTableViewState, zoom],
  );
  const [internalActiveView, setInternalActiveView] =
    useState<GestureView>("rectified");
  const activeView = activeViewProp ?? internalActiveView;
  const [editorMode, setEditorMode] = useState<EditorMode>("review");
  const [anchorConstraint, setAnchorConstraint] =
    useState<AnchorConstraint>("diagonal");
  const [anchorPreview, setAnchorPreview] = useState<AnchorPreview | null>(
    null,
  );
  const [anchorCornerIndex, setAnchorCornerIndex] = useState(0);
  const [numericAnchor, setNumericAnchor] = useState<{
    cardId: string;
    cornerIndex: number;
    point: TablePoint;
  } | null>(null);
  const anchorPreviewRef = useRef<AnchorPreview | null>(null);
  const dragRef = useRef<ActiveGesture | null>(null);
  const tableSvgRef = useRef<SVGSVGElement | null>(null);
  const sourceSvgRef = useRef<SVGSVGElement | null>(null);
  const sourceViewportRef = useRef<HTMLDivElement | null>(null);
  const anchorSequenceRef = useRef(0);
  const setAnchorPreviewState = useCallback((next: AnchorPreview | null) => {
    anchorPreviewRef.current = next;
    setAnchorPreview(next);
  }, []);
  const sourceMaskPrefix = useMemo(
    () => `pose-scene-${frame.itemId.replace(/[^A-Za-z0-9_-]/g, "-")}`,
    [frame.itemId],
  );

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const changeActiveView = useCallback(
    (next: GestureView) => {
      setInternalActiveView(next);
      onActiveViewChange?.(next);
    },
    [onActiveViewChange],
  );

  const commit = useCallback(
    (next: PoseSceneEnvelope, notice: string) => {
      draftRef.current = next;
      setDraft(next);
      void withSceneDigest(next).then(
        (digested) => onChange(digested, notice),
        () => onChange(next, notice),
      );
    },
    [onChange],
  );

  const selectedPose =
    draft.scene.poses.find((pose) => pose.card_id === selectedCardId) ??
    draft.scene.poses[0] ??
    null;
  const selectedReviewState =
    draft.card_review_states?.find(
      (state) => state.card_id === selectedPose?.card_id,
    ) ?? null;
  const unresolvedCardCount =
    draft.card_review_states?.filter((state) => state.state === "pending")
      .length ?? 0;
  const applyCardReviewState = useCallback(
    (cardId: string, state: "accepted" | "rejected") => {
      const current = draftRef.current;
      if (current.card_review_states === undefined) return;
      const card_review_states = current.card_review_states.map((candidate) =>
        candidate.card_id === cardId ? { ...candidate, state } : candidate,
      );
      const next = {
        ...current,
        card_review_states,
        completion_state: card_review_states.some(
          (candidate) => candidate.state === "pending",
        )
          ? ("pending" as const)
          : ("complete" as const),
        completion_reason: null,
      };
      draftRef.current = next;
      setDraft(next);
    },
    [],
  );
  const acceptRemainingCards = useCallback(() => {
    const current = draftRef.current;
    if (current.card_review_states === undefined) return;
    const next = {
      ...current,
      card_review_states: current.card_review_states.map((candidate) =>
        candidate.state === "pending"
          ? { ...candidate, state: "accepted" as const }
          : candidate,
      ),
      completion_state: "complete" as const,
      completion_reason: null,
    };
    draftRef.current = next;
    setDraft(next);
  }, []);
  const projectedFrameBounds = useMemo(
    () =>
      sourceUrl === null
        ? null
        : projectImageBounds(
            width,
            height,
            draft.projection.table_to_image_homography,
          ),
    [draft.projection.table_to_image_homography, height, sourceUrl, width],
  );
  const tableViewBox = useMemo(
    () =>
      getTableViewBox(
        draft.scene,
        draft.projection,
        zoom,
        pan,
        projectedFrameBounds,
      ),
    [draft.projection, draft.scene, pan, projectedFrameBounds, zoom],
  );
  const projectedPolygons = useMemo(
    () =>
      new Map(
        draft.scene.poses.map((pose) => [
          pose.card_id,
          cardPolygon(pose, draft.projection)
            .map((point) =>
              projectTablePoint(
                point,
                draft.projection.table_to_image_homography,
              ),
            )
            .filter((point): point is [number, number] => point !== null),
        ]),
      ),
    [draft.projection, draft.scene.poses],
  );
  const candidateProjection = useMemo<CardSceneProjection | null>(
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
  const candidateProjectedPolygons = useMemo(
    () =>
      candidateProjection === null
        ? new Map<string, [number, number][]>()
        : new Map(
            draft.scene.poses.map((pose) => [
              pose.card_id,
              cardPolygon(pose, candidateProjection)
                .map((point) =>
                  projectTablePoint(
                    point,
                    candidateProjection.table_to_image_homography,
                  ),
                )
                .filter((point): point is [number, number] => point !== null),
            ]),
          ),
    [candidateProjection, draft.scene.poses],
  );
  const getTablePoint = useCallback(
    (
      event: ReactPointerEvent<SVGSVGElement>,
      target = event.currentTarget,
    ): TablePoint | null => {
      const rect = target.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return null;
      return [
        tableViewBox.x +
          ((event.clientX - rect.left) / rect.width) * tableViewBox.width,
        tableViewBox.y +
          ((event.clientY - rect.top) / rect.height) * tableViewBox.height,
      ];
    },
    [tableViewBox],
  );

  const getSourcePoint = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>): [number, number] | null => {
      const rect = sourceViewportRef.current?.getBoundingClientRect();
      if (rect === undefined || rect.width <= 0 || rect.height <= 0)
        return null;
      return [
        ((event.clientX - rect.left) / rect.width) * width,
        ((event.clientY - rect.top) / rect.height) * height,
      ];
    },
    [height, width],
  );

  const getGestureTablePoint = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>): TablePoint | null => {
      const gesture = dragRef.current;
      if (gesture?.view === "source") {
        const sourcePoint = getSourcePoint(event);
        return sourcePoint === null
          ? null
          : projectImagePointToTable(
              sourcePoint,
              draftRef.current.projection.table_to_image_homography,
            );
      }
      return getTablePoint(event, tableSvgRef.current ?? event.currentTarget);
    },
    [getSourcePoint, getTablePoint],
  );

  const updateAnchorPreview = useCallback(
    (point: TablePoint) => {
      const gesture = dragRef.current;
      if (
        gesture === null ||
        gesture.kind !== "anchor" ||
        gesture.originalCorners === undefined ||
        gesture.movedCorner === undefined ||
        gesture.constraint === undefined
      )
        return;
      if (gesture.cardId === null) return;
      const corners = constrainAnchorQuad(
        gesture.originalCorners,
        gesture.movedCorner,
        point,
        gesture.constraint,
      );
      gesture.dirty = corners.some(
        (corner, index) =>
          corner[0] !== gesture.originalCorners?.[index]?.[0] ||
          corner[1] !== gesture.originalCorners?.[index]?.[1],
      );
      setAnchorPreviewState({
        cardId: gesture.cardId,
        movedCorner: gesture.movedCorner,
        constraint: gesture.constraint,
        corners,
      });
    },
    [setAnchorPreviewState],
  );

  const handleTablePointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const gesture = dragRef.current;
      if (gesture === null || gesture.pointerId !== event.pointerId) return;
      if (gesture.kind === "pan") {
        const startPan = gesture.startPan;
        const startViewBox = gesture.startViewBox;
        const rect = event.currentTarget.getBoundingClientRect();
        if (
          startPan === undefined ||
          startViewBox === undefined ||
          rect.width <= 0 ||
          rect.height <= 0
        )
          return;
        const deltaX = event.clientX - gesture.startClientX;
        const deltaY = event.clientY - gesture.startClientY;
        if (!gesture.dirty && Math.hypot(deltaX, deltaY) < DRAG_THRESHOLD_PX)
          return;
        gesture.dirty = true;
        setPan([
          startPan[0] - (deltaX / rect.width) * startViewBox.width,
          startPan[1] - (deltaY / rect.height) * startViewBox.height,
        ]);
        return;
      }
      if (readOnly) return;
      const point = getGestureTablePoint(event);
      if (point === null) return;
      if (gesture.kind === "anchor") {
        updateAnchorPreview(point);
        return;
      }
      if (gesture.cardId === null) return;
      if (
        !gesture.dirty &&
        Math.hypot(
          event.clientX - gesture.startClientX,
          event.clientY - gesture.startClientY,
        ) < DRAG_THRESHOLD_PX
      ) {
        return;
      }
      const pose = draftRef.current.scene.poses.find(
        (candidate) => candidate.card_id === gesture.cardId,
      );
      if (pose === undefined) return;
      const next = applyPoseSceneAction(
        draftRef.current,
        gesture.kind === "move"
          ? { type: "move", cardId: gesture.cardId, center: point }
          : {
              type: "rotate",
              cardId: gesture.cardId,
              rotationDegrees:
                (Math.atan2(
                  point[1] - pose.center[1],
                  point[0] - pose.center[0],
                ) *
                  180) /
                  Math.PI +
                90,
            },
      );
      gesture.dirty = true;
      draftRef.current = next;
      setDraft(next);
    },
    [getGestureTablePoint, readOnly, updateAnchorPreview],
  );

  const cancelGesture = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const gesture = dragRef.current;
      if (gesture === null || gesture.pointerId !== event.pointerId) return;
      dragRef.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (gesture.kind === "pan" && gesture.startPan !== undefined)
        setPan(gesture.startPan);
      draftRef.current = gesture.originalDraft;
      setDraft(gesture.originalDraft);
      setAnchorPreviewState(null);
    },
    [setAnchorPreviewState],
  );

  const finishGesture = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const gesture = dragRef.current;
      if (gesture === null || gesture.pointerId !== event.pointerId) return;
      dragRef.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (!gesture.dirty) {
        setAnchorPreviewState(null);
        return;
      }
      if (gesture.kind === "pan") return;
      if (
        gesture.kind === "anchor" &&
        gesture.originalCorners !== undefined &&
        gesture.movedCorner !== undefined &&
        gesture.constraint !== undefined &&
        anchorPreviewRef.current !== null
      ) {
        const command = createCalibrationAnchorCommand({
          command_id: `anchor-command-${frame.itemId}-${anchorSequenceRef.current + 1}`,
          sequence: anchorSequenceRef.current + 1,
          expected_draft_revision: 0,
          anchor_id: `anchor-${frame.itemId}-${gesture.cardId}`,
          moved_corner: gesture.movedCorner,
          constraint: gesture.constraint,
          corners: anchorPreviewRef.current.corners,
          operator_id: "local-operator",
        });
        anchorSequenceRef.current += 1;
        setAnchorPreviewState(null);
        onAnchorCommand?.(command);
        return;
      }
      commit(
        draftRef.current,
        gesture.kind === "move"
          ? "Card moved on the virtual table."
          : "Card rotation saved.",
      );
    },
    [commit, frame.itemId, onAnchorCommand, setAnchorPreviewState],
  );

  const startTablePointer = useCallback(
    (
      event: ReactPointerEvent<SVGElement>,
      cardId: string,
      mode: "move" | "rotate",
    ) => {
      if (readOnly || editorMode !== "review") {
        event.stopPropagation();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      setSelectedCardId(cardId);
      const gesture: ActiveGesture = {
        pointerId: event.pointerId,
        cardId,
        kind: mode,
        view: "rectified",
        dirty: false,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originalDraft: draftRef.current,
      };
      dragRef.current = gesture;
      tableSvgRef.current?.setPointerCapture?.(event.pointerId);
    },
    [editorMode, readOnly],
  );

  const startAnchorPointer = useCallback(
    (
      event: ReactPointerEvent<SVGElement>,
      cardId: string,
      movedCorner: number,
      view: GestureView,
      constraint = event.shiftKey
        ? ("card_x" as const)
        : event.altKey
          ? ("card_y" as const)
          : anchorConstraint,
    ) => {
      if (readOnly || editorMode !== "refine") return;
      const pose = draftRef.current.scene.poses.find(
        (candidate) => candidate.card_id === cardId,
      );
      if (pose === undefined) return;
      event.preventDefault();
      event.stopPropagation();
      setSelectedCardId(cardId);
      const corners = cardPolygon(pose, draftRef.current.projection);
      const gesture: ActiveGesture = {
        pointerId: event.pointerId,
        cardId,
        kind: "anchor",
        view,
        dirty: false,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originalDraft: draftRef.current,
        originalCorners: corners,
        movedCorner,
        constraint,
      };
      dragRef.current = gesture;
      setAnchorConstraint(constraint);
      setAnchorCornerIndex(movedCorner);
      setAnchorPreviewState({
        cardId,
        movedCorner,
        constraint,
        corners,
      });
      (view === "source"
        ? sourceSvgRef.current
        : tableSvgRef.current
      )?.setPointerCapture?.(event.pointerId);
    },
    [anchorConstraint, editorMode, readOnly, setAnchorPreviewState],
  );

  const startTablePan = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      if (
        event.button !== 0 ||
        event.target !== event.currentTarget ||
        dragRef.current !== null
      )
        return;
      event.preventDefault();
      const gesture: ActiveGesture = {
        pointerId: event.pointerId,
        cardId: null,
        kind: "pan",
        view: "rectified",
        dirty: false,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originalDraft: draftRef.current,
        startPan: [...pan],
        startViewBox: tableViewBox,
      };
      dragRef.current = gesture;
      tableSvgRef.current?.setPointerCapture?.(event.pointerId);
    },
    [pan, tableViewBox],
  );

  const handleTableWheel = useCallback(
    (event: ReactWheelEvent<SVGSVGElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || event.deltaY === 0) return;
      event.preventDefault();

      const deltaY =
        event.deltaY *
        (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1);
      const nextZoom = Math.min(
        3,
        Math.max(0.5, zoom * Math.pow(2, -deltaY / 240)),
      );
      if (nextZoom === zoom) return;

      const focusX = (event.clientX - rect.left) / rect.width;
      const focusY = (event.clientY - rect.top) / rect.height;
      const focusedPoint: TablePoint = [
        tableViewBox.x + focusX * tableViewBox.width,
        tableViewBox.y + focusY * tableViewBox.height,
      ];
      const nextViewBox = getTableViewBox(
        draft.scene,
        draft.projection,
        nextZoom,
        pan,
        projectedFrameBounds,
      );
      updateTableViewState({
        zoom: nextZoom,
        pan: [
          pan[0] +
            focusedPoint[0] -
            (nextViewBox.x + focusX * nextViewBox.width),
          pan[1] +
            focusedPoint[1] -
            (nextViewBox.y + focusY * nextViewBox.height),
        ],
      });
    },
    [
      draft,
      pan,
      projectedFrameBounds,
      tableViewBox,
      updateTableViewState,
      zoom,
    ],
  );

  const getAnchorCorners = useCallback(
    (cardId: string): TablePoint[] => {
      if (anchorPreview?.cardId === cardId) return anchorPreview.corners;
      const pose = draft.scene.poses.find(
        (candidate) => candidate.card_id === cardId,
      );
      return pose === undefined ? [] : cardPolygon(pose, draft.projection);
    },
    [anchorPreview, draft.projection, draft.scene.poses],
  );

  const projectedAnchorPolygons = useMemo(
    () =>
      new Map(
        draft.scene.poses.map((pose) => [
          pose.card_id,
          getAnchorCorners(pose.card_id)
            .map((point) =>
              projectTablePoint(
                point,
                draft.projection.table_to_image_homography,
              ),
            )
            .filter((point): point is [number, number] => point !== null),
        ]),
      ),
    [
      draft.projection.table_to_image_homography,
      draft.scene.poses,
      getAnchorCorners,
    ],
  );

  const emitNumericAnchorCommand = useCallback(() => {
    if (readOnly || editorMode !== "refine" || numericAnchor === null) return;
    const pose = draftRef.current.scene.poses.find(
      (candidate) => candidate.card_id === numericAnchor.cardId,
    );
    if (pose === undefined) return;
    const corners = cardPolygon(pose, draftRef.current.projection);
    const constrained = constrainAnchorQuad(
      corners,
      numericAnchor.cornerIndex,
      numericAnchor.point,
      anchorConstraint,
    );
    const command = createCalibrationAnchorCommand({
      command_id: `anchor-command-${frame.itemId}-${anchorSequenceRef.current + 1}`,
      sequence: anchorSequenceRef.current + 1,
      expected_draft_revision: 0,
      anchor_id: `anchor-${frame.itemId}-${numericAnchor.cardId}`,
      moved_corner: numericAnchor.cornerIndex,
      constraint: anchorConstraint,
      corners: constrained,
      operator_id: "local-operator",
    });
    anchorSequenceRef.current += 1;
    setNumericAnchor(null);
    onAnchorCommand?.(command);
  }, [
    anchorConstraint,
    editorMode,
    frame.itemId,
    numericAnchor,
    onAnchorCommand,
    readOnly,
  ]);

  const cancelActiveGesture = useCallback(() => {
    const gesture = dragRef.current;
    if (gesture === null) return;
    dragRef.current = null;
    if (gesture.kind === "pan" && gesture.startPan !== undefined)
      setPan(gesture.startPan);
    draftRef.current = gesture.originalDraft;
    setDraft(gesture.originalDraft);
    setAnchorPreviewState(null);
  }, [setAnchorPreviewState]);

  const handleSurfaceKeyDown = useCallback(
    (event: React.KeyboardEvent<SVGSVGElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelActiveGesture();
        return;
      }
      const nextConstraint: AnchorConstraint | null =
        event.key.toLowerCase() === "d"
          ? "diagonal"
          : event.key.toLowerCase() === "x"
            ? "card_x"
            : event.key.toLowerCase() === "y"
              ? "card_y"
              : null;
      if (nextConstraint !== null && editorMode === "refine") {
        event.preventDefault();
        setAnchorConstraint(nextConstraint);
      }
    },
    [cancelActiveGesture, editorMode],
  );

  const handleAnchorHandleKeyDown = useCallback(
    (
      event: React.KeyboardEvent<SVGCircleElement>,
      cardId: string,
      cornerIndex: number,
    ) => {
      if (readOnly || editorMode !== "refine") return;
      if (event.key === "Escape") {
        event.preventDefault();
        cancelActiveGesture();
        return;
      }
      if (event.key.toLowerCase() === "d") {
        event.preventDefault();
        setAnchorConstraint("diagonal");
      } else if (event.key.toLowerCase() === "x") {
        event.preventDefault();
        setAnchorConstraint("card_x");
      } else if (event.key.toLowerCase() === "y") {
        event.preventDefault();
        setAnchorConstraint("card_y");
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setSelectedCardId(cardId);
        setAnchorCornerIndex(cornerIndex);
      }
    },
    [cancelActiveGesture, editorMode, readOnly],
  );

  const applyAndCommit = useCallback(
    (action: Parameters<typeof applyPoseSceneAction>[1], notice: string) => {
      commit(applyPoseSceneAction(draftRef.current, action), notice);
    },
    [commit],
  );

  const addCard = useCallback(() => {
    if (readOnly) return;
    const center = selectedPose?.center ?? [0, 0];
    const cardId = nextManualPoseId(draftRef.current.scene);
    applyAndCommit(
      {
        type: "add",
        cardId,
        center: [center[0] + 0.2, center[1] + 0.2],
      },
      "Standard-size card added to the virtual table.",
    );
    setSelectedCardId(cardId);
  }, [applyAndCommit, readOnly, selectedPose]);

  const removeCard = useCallback(() => {
    if (readOnly || selectedPose === null || draft.scene.poses.length <= 1)
      return;
    applyAndCommit(
      { type: "remove", cardId: selectedPose.card_id },
      "Card removed from the virtual table.",
    );
    setSelectedCardId(
      draft.scene.poses.find((pose) => pose.card_id !== selectedPose.card_id)
        ?.card_id ?? null,
    );
  }, [applyAndCommit, draft.scene.poses, readOnly, selectedPose]);

  const handleCardKeyDown = useCallback(
    (event: React.KeyboardEvent<SVGGElement>, cardId: string) => {
      if (readOnly) return;
      const delta = event.shiftKey ? 0.1 : 0.025;
      if (
        event.key === "ArrowLeft" ||
        event.key === "ArrowRight" ||
        event.key === "ArrowUp" ||
        event.key === "ArrowDown"
      ) {
        event.preventDefault();
        applyAndCommit(
          {
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
          "Card nudge saved.",
        );
      } else if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        applyAndCommit(
          {
            type: "nudge",
            cardId,
            delta: [0, 0],
            rotationDeltaDegrees: event.shiftKey ? -5 : 5,
          },
          "Card rotation nudge saved.",
        );
      }
    },
    [applyAndCommit, readOnly],
  );

  const sourcePolygons = frame.outcome.candidates.flatMap((candidate) =>
    candidatePolygons(candidate, width, height).map((polygon) => ({
      candidate,
      polygon,
    })),
  );

  return (
    <section
      className={styles.poseEditor}
      aria-label="Calibrated card scene editor"
    >
      <div className={styles.poseToolbar} aria-label="Virtual table controls">
        <fieldset aria-label="Card scene view">
          <button
            className={
              activeView === "source"
                ? styles.pipelineToggleActive
                : styles.pipelineToggle
            }
            type="button"
            aria-pressed={activeView === "source"}
            onClick={() => changeActiveView("source")}
          >
            Source
          </button>
          <button
            className={
              activeView === "rectified"
                ? styles.pipelineToggleActive
                : styles.pipelineToggle
            }
            type="button"
            aria-pressed={activeView === "rectified"}
            onClick={() => changeActiveView("rectified")}
          >
            Rectified table
          </button>
        </fieldset>
        <fieldset aria-label="Card scene editing mode">
          <button
            className={
              editorMode === "review"
                ? styles.pipelineToggleActive
                : styles.pipelineToggle
            }
            type="button"
            aria-pressed={editorMode === "review"}
            onClick={() => {
              cancelActiveGesture();
              setEditorMode("review");
            }}
          >
            Review cards
          </button>
          <button
            className={
              editorMode === "refine"
                ? styles.pipelineToggleActive
                : styles.pipelineToggle
            }
            type="button"
            aria-pressed={editorMode === "refine"}
            onClick={() => {
              cancelActiveGesture();
              setEditorMode("refine");
            }}
          >
            Refine mapping
          </button>
        </fieldset>
        <div
          className={styles.poseViewActions}
          aria-label="Virtual table view controls"
        >
          <button
            type="button"
            onClick={() => setZoom((value) => Math.min(3, value * 1.25))}
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => setZoom((value) => Math.max(0.5, value / 1.25))}
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            onClick={() => setPan(([x, y]) => [x, y - 0.5])}
            aria-label="Pan table up"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => setPan(([x, y]) => [x, y + 0.5])}
            aria-label="Pan table down"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={() => setPan(([x, y]) => [x - 0.5, y])}
            aria-label="Pan table left"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => setPan(([x, y]) => [x + 0.5, y])}
            aria-label="Pan table right"
          >
            →
          </button>
          <button
            type="button"
            onClick={() => {
              updateTableViewState({ zoom: 1, pan: [0, 0] });
            }}
            aria-label="Fit virtual table"
          >
            ⌂
          </button>
        </div>
      </div>

      <div className={styles.poseEditorViews} data-active-view={activeView}>
        {activeView === "source" ? (
          <div className={styles.poseViewPanel}>
            {sourceUrl === null ? (
              <div className={styles.emptyView} aria-hidden="true" />
            ) : (
              <div
                ref={sourceViewportRef}
                className={styles.poseSourceViewport}
                style={{ aspectRatio: `${width} / ${height}` }}
              >
                <img src={sourceUrl} alt="Selected visible-card source frame" />
                <svg
                  ref={sourceSvgRef}
                  viewBox={`0 0 ${width} ${height}`}
                  role="img"
                  aria-label="Projected card scene"
                  tabIndex={0}
                  onPointerMove={handleTablePointerMove}
                  onPointerUp={finishGesture}
                  onPointerCancel={cancelGesture}
                  onLostPointerCapture={cancelGesture}
                  onKeyDown={handleSurfaceKeyDown}
                >
                  <defs>
                    {draft.scene.poses.map((pose) => {
                      const polygon = projectedPolygons.get(pose.card_id) ?? [];
                      const maskId = `${sourceMaskPrefix}-${pose.card_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
                      return (
                        <mask
                          key={maskId}
                          id={maskId}
                          maskUnits="userSpaceOnUse"
                          x="0"
                          y="0"
                          width={width}
                          height={height}
                        >
                          <rect
                            x="0"
                            y="0"
                            width={width}
                            height={height}
                            fill="black"
                          />
                          <polygon
                            points={pointsAttribute(polygon)}
                            fill="white"
                          />
                          {higherCards(draft.scene, pose.card_id).map(
                            (higher) => (
                              <polygon
                                key={higher.card_id}
                                points={pointsAttribute(
                                  projectedPolygons.get(higher.card_id) ?? [],
                                )}
                                fill="black"
                              />
                            ),
                          )}
                        </mask>
                      );
                    })}
                  </defs>
                  {sourcePolygons.map(({ candidate, polygon }, index) => (
                    <polygon
                      key={`${candidate.card_id}-${index}`}
                      points={pointsAttribute(polygon)}
                      fill="none"
                      stroke="#a7aebc"
                      strokeDasharray="5 5"
                      strokeWidth={Math.max(1, width / 500)}
                    />
                  ))}
                  {candidateProjection !== null
                    ? draft.scene.poses.map((pose) => (
                        <polygon
                          key={`${pose.card_id}-candidate-calibration`}
                          points={pointsAttribute(
                            candidateProjectedPolygons.get(pose.card_id) ?? [],
                          )}
                          fill="none"
                          stroke="#ffd166"
                          strokeDasharray="10 6"
                          strokeWidth={Math.max(1, width / 400)}
                          pointerEvents="none"
                        />
                      ))
                    : null}
                  {draft.scene.poses.map((pose) => {
                    const polygon = projectedPolygons.get(pose.card_id) ?? [];
                    const anchorPolygon =
                      projectedAnchorPolygons.get(pose.card_id) ?? [];
                    const selected = pose.card_id === selectedCardId;
                    const maskId = `${sourceMaskPrefix}-${pose.card_id.replace(/[^A-Za-z0-9_-]/g, "-")}`;
                    return (
                      <g key={pose.card_id}>
                        <polygon
                          points={pointsAttribute(polygon)}
                          fill="rgba(59, 205, 180, 0.2)"
                          mask={`url(#${maskId})`}
                          stroke="#30c9ac"
                          strokeWidth={
                            selected
                              ? Math.max(2, width / 250)
                              : Math.max(1, width / 500)
                          }
                          role="button"
                          tabIndex={0}
                          aria-label={`Reviewed card ${pose.card_id}`}
                          onClick={() => setSelectedCardId(pose.card_id)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ")
                              setSelectedCardId(pose.card_id);
                          }}
                        />
                        {editorMode === "refine" && !readOnly && selected
                          ? anchorPolygon.map((point, cornerIndex) => (
                              <circle
                                key={`${pose.card_id}-source-anchor-${cornerIndex}`}
                                cx={point[0]}
                                cy={point[1]}
                                r={Math.max(5, width / 120)}
                                fill="#ff8a65"
                                stroke="#18242f"
                                strokeWidth={Math.max(1, width / 600)}
                                tabIndex={0}
                                role="button"
                                aria-label={`Anchor corner ${cornerIndex + 1} for card ${pose.card_id}`}
                                onPointerDown={(event) =>
                                  startAnchorPointer(
                                    event,
                                    pose.card_id,
                                    cornerIndex,
                                    "source",
                                  )
                                }
                                onKeyDown={(event) =>
                                  handleAnchorHandleKeyDown(
                                    event,
                                    pose.card_id,
                                    cornerIndex,
                                  )
                                }
                              />
                            ))
                          : null}
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}
          </div>
        ) : null}
        {activeView === "rectified" ? (
          <div className={styles.poseViewPanel}>
            <svg
              ref={tableSvgRef}
              className={styles.poseTableSvg}
              viewBox={`${tableViewBox.x} ${tableViewBox.y} ${tableViewBox.width} ${tableViewBox.height}`}
              role="application"
              aria-label="Rectified virtual table"
              tabIndex={0}
              onPointerDown={startTablePan}
              onPointerMove={handleTablePointerMove}
              onPointerUp={finishGesture}
              onPointerCancel={cancelGesture}
              onLostPointerCapture={cancelGesture}
              onKeyDown={handleSurfaceKeyDown}
              onWheel={handleTableWheel}
            >
              {sourceUrl !== null && projectedFrameBounds !== null ? (
                <RectifiedSourceFrame
                  sourceUrl={sourceUrl}
                  width={width}
                  height={height}
                  homography={draft.projection.table_to_image_homography}
                  clipPrefix={`${sourceMaskPrefix}-rectified-background`}
                />
              ) : null}
              {rectifiedRenderOrder(draft.scene, selectedCardId).map((pose) => (
                <TableCard
                  key={pose.card_id}
                  pose={pose}
                  projection={draft.projection}
                  selected={pose.card_id === selectedCardId}
                  readOnly={readOnly}
                  editorMode={editorMode}
                  anchorCorners={getAnchorCorners(pose.card_id)}
                  onSelect={() => setSelectedCardId(pose.card_id)}
                  onPointerDown={(event, mode) =>
                    startTablePointer(event, pose.card_id, mode)
                  }
                  onAnchorPointerDown={(event, cornerIndex) =>
                    startAnchorPointer(
                      event,
                      pose.card_id,
                      cornerIndex,
                      "rectified",
                    )
                  }
                  onAnchorHandleKeyDown={(event, cornerIndex) =>
                    handleAnchorHandleKeyDown(event, pose.card_id, cornerIndex)
                  }
                  onKeyDown={(event) => handleCardKeyDown(event, pose.card_id)}
                />
              ))}
            </svg>
          </div>
        ) : null}
      </div>

      {!readOnly ? (
        <div className={styles.poseEditorControls}>
          {editorMode === "refine" && selectedPose !== null ? (
            <div className={styles.anchorControls}>
              {ANCHOR_CONSTRAINTS.map((constraint) => (
                <button
                  key={constraint}
                  type="button"
                  aria-label={`${constraint} anchor constraint`}
                  aria-pressed={anchorConstraint === constraint}
                  onClick={() => setAnchorConstraint(constraint)}
                >
                  {constraint === "diagonal"
                    ? "D"
                    : constraint === "card_x"
                      ? "X"
                      : "Y"}
                </button>
              ))}
              {[0, 1, 2, 3].map((cornerIndex) => (
                <button
                  key={cornerIndex}
                  type="button"
                  aria-label={`Anchor corner ${cornerIndex + 1}`}
                  aria-pressed={anchorCornerIndex === cornerIndex}
                  onClick={() => setAnchorCornerIndex(cornerIndex)}
                >
                  {cornerIndex + 1}
                </button>
              ))}
              <input
                aria-label="Anchor X"
                type="number"
                step="0.01"
                value={
                  numericAnchor?.cardId === selectedPose.card_id &&
                  numericAnchor.cornerIndex === anchorCornerIndex
                    ? numericAnchor.point[0]
                    : (getAnchorCorners(selectedPose.card_id)[
                        anchorCornerIndex
                      ]?.[0] ?? 0)
                }
                onChange={(event) => {
                  const point = getAnchorCorners(selectedPose.card_id)[
                    anchorCornerIndex
                  ];
                  const value = Number(event.target.value);
                  const currentPoint =
                    numericAnchor?.cardId === selectedPose.card_id &&
                    numericAnchor.cornerIndex === anchorCornerIndex
                      ? numericAnchor.point
                      : point;
                  if (currentPoint !== undefined && Number.isFinite(value))
                    setNumericAnchor({
                      cardId: selectedPose.card_id,
                      cornerIndex: anchorCornerIndex,
                      point: [value, currentPoint[1]],
                    });
                }}
              />
              <input
                aria-label="Anchor Y"
                type="number"
                step="0.01"
                value={
                  numericAnchor?.cardId === selectedPose.card_id &&
                  numericAnchor.cornerIndex === anchorCornerIndex
                    ? numericAnchor.point[1]
                    : (getAnchorCorners(selectedPose.card_id)[
                        anchorCornerIndex
                      ]?.[1] ?? 0)
                }
                onChange={(event) => {
                  const point = getAnchorCorners(selectedPose.card_id)[
                    anchorCornerIndex
                  ];
                  const value = Number(event.target.value);
                  const currentPoint =
                    numericAnchor?.cardId === selectedPose.card_id &&
                    numericAnchor.cornerIndex === anchorCornerIndex
                      ? numericAnchor.point
                      : point;
                  if (currentPoint !== undefined && Number.isFinite(value))
                    setNumericAnchor({
                      cardId: selectedPose.card_id,
                      cornerIndex: anchorCornerIndex,
                      point: [currentPoint[0], value],
                    });
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    emitNumericAnchorCommand();
                  }
                }}
              />
              <button
                type="button"
                aria-label="Apply anchor edit"
                onClick={emitNumericAnchorCommand}
                disabled={numericAnchor === null}
              >
                ✓
              </button>
            </div>
          ) : null}
          {selectedPose !== null && onCardDecision !== undefined ? (
            <div className={styles.poseCardReviewControls}>
              <button
                type="button"
                aria-label="Accept card"
                onClick={() => {
                  applyCardReviewState(selectedPose.card_id, "accepted");
                  onCardDecision(selectedPose.card_id, "accept");
                }}
                disabled={selectedReviewState?.state === "accepted"}
              >
                ✓
              </button>
              <button
                type="button"
                aria-label="Reject card"
                onClick={() => {
                  applyCardReviewState(selectedPose.card_id, "rejected");
                  onCardDecision(selectedPose.card_id, "reject");
                }}
                disabled={selectedReviewState?.state === "rejected"}
              >
                ×
              </button>
              {unresolvedCardCount > 0 && onResolveRemaining !== undefined ? (
                <button
                  type="button"
                  aria-label={`Accept remaining cards (${unresolvedCardCount})`}
                  onClick={() => {
                    acceptRemainingCards();
                    onResolveRemaining();
                  }}
                >
                  ✓{unresolvedCardCount}
                </button>
              ) : null}
            </div>
          ) : null}
          <button
            type="button"
            aria-label="Add standard-size card"
            onClick={addCard}
          >
            +
          </button>
          <button
            type="button"
            aria-label="Remove selected card"
            onClick={removeCard}
            disabled={selectedPose === null || draft.scene.poses.length <= 1}
          >
            −
          </button>
          <button
            type="button"
            aria-label="Bring forward"
            onClick={() =>
              selectedPose &&
              applyAndCommit(
                { type: "bring_forward", cardId: selectedPose.card_id },
                "Card brought forward.",
              )
            }
            disabled={selectedPose === null}
          >
            ↑
          </button>
          <button
            type="button"
            aria-label="Send backward"
            onClick={() =>
              selectedPose &&
              applyAndCommit(
                { type: "send_backward", cardId: selectedPose.card_id },
                "Card sent backward.",
              )
            }
            disabled={selectedPose === null}
          >
            ↓
          </button>
          <button
            type="button"
            aria-label="Restore initialized scene"
            onClick={() =>
              applyAndCommit(
                { type: "restore_initialized" },
                "Initialized card scene restored.",
              )
            }
          >
            ↺
          </button>
          {selectedPose !== null ? (
            <input
              aria-label="Selected card angle"
              type="number"
              step="1"
              value={selectedPose.rotation_degrees}
              onChange={(event) => {
                const value = Number(event.target.value);
                if (Number.isFinite(value)) {
                  const next = applyPoseSceneAction(draftRef.current, {
                    type: "rotate",
                    cardId: selectedPose.card_id,
                    rotationDegrees: value,
                  });
                  draftRef.current = next;
                  setDraft(next);
                }
              }}
              onBlur={() => commit(draftRef.current, "Card angle saved.")}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  commit(draftRef.current, "Card angle saved.");
                }
              }}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function TableCard({
  pose,
  projection,
  selected,
  readOnly,
  editorMode,
  anchorCorners,
  onSelect,
  onPointerDown,
  onAnchorPointerDown,
  onAnchorHandleKeyDown,
  onKeyDown,
}: {
  pose: PoseCard;
  projection: PoseSceneEnvelope["projection"];
  selected: boolean;
  readOnly: boolean;
  editorMode: EditorMode;
  anchorCorners: TablePoint[];
  onSelect: () => void;
  onPointerDown: (
    event: ReactPointerEvent<SVGElement>,
    mode: "move" | "rotate",
  ) => void;
  onAnchorPointerDown: (
    event: ReactPointerEvent<SVGElement>,
    cornerIndex: number,
  ) => void;
  onAnchorHandleKeyDown: (
    event: React.KeyboardEvent<SVGCircleElement>,
    cornerIndex: number,
  ) => void;
  onKeyDown: (event: React.KeyboardEvent<SVGGElement>) => void;
}) {
  const polygon = cardPolygon(pose, projection);
  const angle = (pose.rotation_degrees * Math.PI) / 180;
  const handle: TablePoint = [
    pose.center[0] + Math.sin(angle) * (projection.card_long_size / 2 + 0.18),
    pose.center[1] - Math.cos(angle) * (projection.card_long_size / 2 + 0.18),
  ];
  return (
    <g
      tabIndex={0}
      role="button"
      aria-label={`Virtual table card ${pose.card_id}`}
      onClick={onSelect}
      onKeyDown={onKeyDown}
    >
      <polygon
        points={pointsAttribute(polygon)}
        fill={selected ? "#2b8f83" : "#37606a"}
        fillOpacity="0.55"
        stroke={selected ? "#d9fff7" : "#80b6b7"}
        strokeWidth={selected ? 0.06 : 0.035}
        onPointerDown={(event) => {
          if (editorMode === "review") onPointerDown(event, "move");
        }}
      />
      {!readOnly && selected && editorMode === "review" ? (
        <circle
          cx={handle[0]}
          cy={handle[1]}
          r="0.11"
          fill="#ffd24f"
          stroke="#18242f"
          strokeWidth="0.035"
          aria-label={`Rotate ${pose.card_id}`}
          onPointerDown={(event) => onPointerDown(event, "rotate")}
        />
      ) : null}
      {!readOnly && selected && editorMode === "refine"
        ? anchorCorners.map((corner, cornerIndex) => (
            <circle
              key={`${pose.card_id}-table-anchor-${cornerIndex}`}
              cx={corner[0]}
              cy={corner[1]}
              r="0.11"
              fill="#ff8a65"
              stroke="#18242f"
              strokeWidth="0.035"
              tabIndex={0}
              role="button"
              aria-label={`Anchor corner ${cornerIndex + 1} for card ${pose.card_id}`}
              onPointerDown={(event) => onAnchorPointerDown(event, cornerIndex)}
              onKeyDown={(event) => onAnchorHandleKeyDown(event, cornerIndex)}
            />
          ))
        : null}
    </g>
  );
}

function getTableViewBox(
  scene: ReviewedCardScene,
  projection: PoseSceneEnvelope["projection"],
  zoom: number,
  pan: TablePoint,
  backgroundBounds: TableViewBox | null,
): TableViewBox {
  const halfShort = projection.card_short_size / 2;
  const halfLong = projection.card_long_size / 2;
  const xs = scene.poses.flatMap((pose) => [
    pose.center[0] - halfShort - halfLong,
    pose.center[0] + halfShort + halfLong,
  ]);
  const ys = scene.poses.flatMap((pose) => [
    pose.center[1] - halfShort - halfLong,
    pose.center[1] + halfShort + halfLong,
  ]);
  const minX = Math.min(...xs, backgroundBounds?.x ?? Infinity, -1) - 0.5;
  const maxX =
    Math.max(
      ...xs,
      backgroundBounds === null
        ? -Infinity
        : backgroundBounds.x + backgroundBounds.width,
      1,
    ) + 0.5;
  const minY = Math.min(...ys, backgroundBounds?.y ?? Infinity, -1) - 0.5;
  const maxY =
    Math.max(
      ...ys,
      backgroundBounds === null
        ? -Infinity
        : backgroundBounds.y + backgroundBounds.height,
      1,
    ) + 0.5;
  const width = (maxX - minX) / zoom;
  const height = (maxY - minY) / zoom;
  const centerX = (minX + maxX) / 2 + pan[0];
  const centerY = (minY + maxY) / 2 + pan[1];
  return { x: centerX - width / 2, y: centerY - height / 2, width, height };
}

type RectifiedBackgroundPatch = {
  clipId: string;
  sourceTriangle: TablePoint[];
  transform: string;
};

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
  if (patches.length === 0) return null;

  return (
    <g
      opacity="0.48"
      pointerEvents="none"
      role="img"
      aria-label="Source frame background"
    >
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
): RectifiedBackgroundPatch[] {
  if (width <= 0 || height <= 0) return [];
  const patches: RectifiedBackgroundPatch[] = [];
  let index = 0;
  for (let row = 0; row < RECTIFIED_BACKGROUND_GRID_SIZE; row += 1) {
    for (let column = 0; column < RECTIFIED_BACKGROUND_GRID_SIZE; column += 1) {
      const left = (column * width) / RECTIFIED_BACKGROUND_GRID_SIZE;
      const right = ((column + 1) * width) / RECTIFIED_BACKGROUND_GRID_SIZE;
      const top = (row * height) / RECTIFIED_BACKGROUND_GRID_SIZE;
      const bottom = ((row + 1) * height) / RECTIFIED_BACKGROUND_GRID_SIZE;
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
        const tableTriangle = sourceTriangle.map((point) =>
          projectImagePointToTable(point, homography),
        );
        if (tableTriangle.some((point) => point === null)) continue;
        const transform = affineTriangleTransform(
          sourceTriangle,
          tableTriangle as TablePoint[],
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

function projectImageBounds(
  width: number,
  height: number,
  homography: number[][],
): TableViewBox | null {
  const points = (
    [
      [0, 0],
      [width, 0],
      [width, height],
      [0, height],
    ] as [number, number][]
  )
    .map((point) => projectImagePointToTable(point, homography))
    .filter((point): point is TablePoint => point !== null);
  if (points.length !== 4) return null;
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    x: minX,
    y: minY,
    width: maxX - minX,
    height: maxY - minY,
  };
}

function higherCards(scene: ReviewedCardScene, cardId: string): PoseCard[] {
  const index = scene.stacking_order.card_ids.indexOf(cardId);
  return scene.stacking_order.card_ids
    .slice(0, Math.max(0, index))
    .map((id) => scene.poses.find((pose) => pose.card_id === id))
    .filter((pose): pose is PoseCard => pose !== undefined);
}

function rectifiedRenderOrder(
  scene: ReviewedCardScene,
  selectedCardId: string | null,
): PoseCard[] {
  const poses = new Map(scene.poses.map((pose) => [pose.card_id, pose]));
  const ordered = [...scene.stacking_order.card_ids]
    .reverse()
    .map((cardId) => poses.get(cardId))
    .filter((pose): pose is PoseCard => pose !== undefined);
  const selected = ordered.find((pose) => pose.card_id === selectedCardId);
  if (selected === undefined) return ordered;
  return [
    ...ordered.filter((pose) => pose.card_id !== selectedCardId),
    selected,
  ];
}

function candidatePolygons(
  candidate: Candidate,
  width: number,
  height: number,
): Array<Array<[number, number]>> {
  if (candidate.geometry.visible_region !== undefined)
    return candidate.geometry.visible_region.polygons.map((polygon) =>
      polygon.map((point) => [
        (point.x * width) / 1000,
        (point.y * height) / 1000,
      ]),
    );
  const box = candidate.geometry.box_2d;
  return box === undefined
    ? []
    : [
        [
          [(box.x_min * width) / 1000, (box.y_min * height) / 1000],
          [(box.x_max * width) / 1000, (box.y_min * height) / 1000],
          [(box.x_max * width) / 1000, (box.y_max * height) / 1000],
          [(box.x_min * width) / 1000, (box.y_max * height) / 1000],
        ],
      ];
}

function pointsAttribute(points: Array<[number, number]>): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}
