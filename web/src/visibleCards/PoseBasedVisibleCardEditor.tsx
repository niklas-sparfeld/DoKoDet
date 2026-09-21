import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
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

type TableViewBox = { x: number; y: number; width: number; height: number };
type EditorMode = "review" | "refine";
type GestureKind = "move" | "rotate" | "anchor";
type GestureView = "source" | "rectified";
type AnchorPreview = {
  cardId: string;
  movedCorner: number;
  constraint: AnchorConstraint;
  corners: TablePoint[];
};
type ActiveGesture = {
  pointerId: number;
  cardId: string;
  kind: GestureKind;
  view: GestureView;
  dirty: boolean;
  originalDraft: PoseSceneEnvelope;
  originalCorners?: TablePoint[];
  movedCorner?: number;
  constraint?: AnchorConstraint;
};

export function PoseBasedVisibleCardEditor({
  recordingId,
  frame,
  scene,
  readOnly,
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
  const [draft, setDraft] = useState(scene);
  const draftRef = useRef(scene);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(
    scene.scene.poses[0]?.card_id ?? null,
  );
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<TablePoint>([0, 0]);
  const [activeView, setActiveView] = useState<"source" | "rectified">(
    "rectified",
  );
  const [editorMode, setEditorMode] = useState<EditorMode>("review");
  const [anchorConstraint, setAnchorConstraint] =
    useState<AnchorConstraint>("diagonal");
  const [anchorPreview, setAnchorPreview] = useState<AnchorPreview | null>(
    null,
  );
  const [lastAnchorCommand, setLastAnchorCommand] =
    useState<CalibrationAnchorCommand | null>(null);
  const [anchorCornerIndex, setAnchorCornerIndex] = useState(0);
  const [numericAnchor, setNumericAnchor] = useState<{
    cardId: string;
    cornerIndex: number;
    point: TablePoint;
  } | null>(null);
  const anchorPreviewRef = useRef<AnchorPreview | null>(null);
  const [activeGesture, setActiveGesture] = useState<ActiveGesture | null>(
    null,
  );
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
    draftRef.current = scene;
  }, [scene]);

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
  const tableViewBox = useMemo(
    () => getTableViewBox(draft.scene, draft.projection, zoom, pan),
    [draft.projection, draft.scene, pan, zoom],
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
      if (gesture === null || gesture.pointerId !== event.pointerId || readOnly)
        return;
      const point = getGestureTablePoint(event);
      if (point === null) return;
      if (gesture.kind === "anchor") {
        updateAnchorPreview(point);
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
      setActiveGesture(null);
      event.currentTarget.releasePointerCapture?.(event.pointerId);
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
      setActiveGesture(null);
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (!gesture.dirty) {
        setAnchorPreviewState(null);
        return;
      }
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
        setLastAnchorCommand(command);
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
      if (readOnly || editorMode !== "review") return;
      event.preventDefault();
      event.stopPropagation();
      setSelectedCardId(cardId);
      const gesture: ActiveGesture = {
        pointerId: event.pointerId,
        cardId,
        kind: mode,
        view: "rectified",
        dirty: false,
        originalDraft: draftRef.current,
      };
      dragRef.current = gesture;
      setActiveGesture(gesture);
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
        originalDraft: draftRef.current,
        originalCorners: corners,
        movedCorner,
        constraint,
      };
      dragRef.current = gesture;
      setActiveGesture(gesture);
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
    setLastAnchorCommand(command);
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
    setActiveGesture(null);
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
      <div className={styles.poseEditorHeader}>
        <div>
          <h2>Calibrated card scene</h2>
          <p className={styles.editorHelp}>
            Move fixed-size cards on the virtual table. Model polygons stay dim
            so they remain evidence, not editable geometry.
          </p>
        </div>
        <span className={styles.poseEditorStatus} role="status">
          {draft.scene.poses.length} card
          {draft.scene.poses.length === 1 ? "" : "s"} · card order is front to
          back
        </span>
      </div>
      <fieldset
        className={styles.pipelineToggleGroup}
        aria-label="Card scene view"
      >
        <legend className={styles.visuallyHidden}>Card scene view</legend>
        <button
          className={
            activeView === "source"
              ? styles.pipelineToggleActive
              : styles.pipelineToggle
          }
          type="button"
          aria-pressed={activeView === "source"}
          onClick={() => setActiveView("source")}
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
          onClick={() => setActiveView("rectified")}
        >
          Rectified table
        </button>
      </fieldset>
      <fieldset
        className={styles.pipelineToggleGroup}
        aria-label="Card scene editing mode"
      >
        <legend className={styles.visuallyHidden}>
          Card scene editing mode
        </legend>
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
      {editorMode === "refine" ? (
        <p className={styles.poseEditorWarning} role="note">
          Refine mapping changes recording-wide calibration anchors. Drag a
          corner to preview a constrained anchor edit; release saves one ordered
          anchor command. Press Escape to cancel.
        </p>
      ) : null}
      <ol
        className={styles.poseEditorGuidance}
        aria-label="Pose review checklist"
      >
        <li>
          Check calibration coverage and rejected candidates before editing
          cards.
        </li>
        <li>
          Correct card count, center, rotation, and front-to-back order on the
          virtual table.
        </li>
        <li>
          Use an ignore region or mark the frame unusable when an external
          occluder is not explained by card poses.
        </li>
      </ol>
      <details className={styles.poseEditorGuidance}>
        <summary>How to review and refine</summary>
        <ul>
          <li>
            Use Source to check the detector suggestion against the frame. Use
            Rectified table to judge fixed-size card placement and stacking.
          </li>
          <li>
            Review cards changes only this frame. Drag a card body or use the
            keyboard to move it; use the handle to rotate it.
          </li>
          <li>
            Refine mapping changes the recording-wide homography. Use a corner
            handle, choose Diagonal, Card X, or Card Y, and press Escape to
            cancel a gesture.
          </li>
          <li>
            Use complete, visible, non-occluded cards as calibration anchors. Do
            not promote clipped or rejected candidates to anchors.
          </li>
          <li>
            Preview checks the calibration gates and lists affected frames.
            Apply creates a new immutable revision; Discard removes this
            preview. If a gate fails, correct or exclude the listed anchor and
            retry. Use Apply and mark affected only when the review accepts the
            displacement.
          </li>
        </ul>
      </details>

      <div className={styles.poseEditorViews} data-active-view={activeView}>
        {activeView === "source" ? (
          <div className={styles.poseViewPanel}>
            <h3>Source frame</h3>
            {sourceUrl === null ? (
              <p className={styles.editorHelp}>
                No exact source frame is available.
              </p>
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
                        {selected ? (
                          <text
                            x={polygon[0]?.[0] ?? 0}
                            y={polygon[0]?.[1] ?? 0}
                            fill="#d9fff7"
                            fontSize={Math.max(10, width / 45)}
                          >
                            {pose.card_id}
                          </text>
                        ) : null}
                      </g>
                    );
                  })}
                </svg>
              </div>
            )}
            <p className={styles.poseLegend}>
              <span data-tone="model">Dashed: detector suggestion</span>
              <span data-tone="proposal">Teal outline: proposed card</span>
              {candidateProjection !== null ? (
                <span data-tone="candidate">
                  Gold dashed: candidate calibration
                </span>
              ) : null}
              <span data-tone="reviewed">
                Filled: reviewed geometry and derived visible region
              </span>
            </p>
          </div>
        ) : null}
        {activeView === "rectified" ? (
          <div className={styles.poseViewPanel}>
            <div className={styles.poseViewHeading}>
              <h3>Virtual table</h3>
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
                  onClick={() =>
                    setZoom((value) => Math.max(0.5, value / 1.25))
                  }
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
                    setZoom(1);
                    setPan([0, 0]);
                  }}
                  aria-label="Fit virtual table"
                >
                  Fit
                </button>
              </div>
            </div>
            <svg
              ref={tableSvgRef}
              className={styles.poseTableSvg}
              viewBox={`${tableViewBox.x} ${tableViewBox.y} ${tableViewBox.width} ${tableViewBox.height}`}
              role="application"
              aria-label="Rectified virtual table"
              tabIndex={0}
              onPointerMove={handleTablePointerMove}
              onPointerUp={finishGesture}
              onPointerCancel={cancelGesture}
              onLostPointerCapture={cancelGesture}
              onKeyDown={handleSurfaceKeyDown}
            >
              <rect
                x={tableViewBox.x}
                y={tableViewBox.y}
                width={tableViewBox.width}
                height={tableViewBox.height}
                fill="rgba(24, 36, 47, 0.82)"
              />
              {draft.scene.poses.map((pose) => (
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
            <p className={styles.editorHelp}>
              {editorMode === "review"
                ? "Select a card, drag its body to move it, or drag the handle to rotate it. Arrow keys nudge the selected card; hold Shift for a coarse step."
                : "Drag a corner handle to refine its calibration anchor. Use D, X, or Y to change the constraint; Escape cancels the gesture."}
            </p>
            <p className={styles.poseLegend}>
              <span data-tone="model">
                Detector suggestions are shown in Source
              </span>
              <span data-tone="proposal">
                Card outlines: immutable proposal
              </span>
              <span data-tone="reviewed">Filled: reviewed card geometry</span>
            </p>
          </div>
        ) : null}
      </div>

      {editorMode === "refine" && anchorPreview !== null ? (
        <div
          className={styles.anchorGesturePreview}
          aria-label="Anchor gesture previews"
        >
          <strong>Anchor gesture preview</strong>
          <span>
            {anchorPreview.constraint} · corner {anchorPreview.movedCorner + 1}
          </span>
          <div className={styles.anchorGesturePreviewGrid}>
            <div>
              <h4>Source preview</h4>
              <svg
                className={styles.anchorPreviewSvg}
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label="Source anchor gesture preview"
              >
                {projectedAnchorPolygons.get(anchorPreview.cardId) !==
                undefined ? (
                  <polygon
                    points={pointsAttribute(
                      projectedAnchorPolygons.get(anchorPreview.cardId) ?? [],
                    )}
                    fill="rgba(255, 138, 101, 0.18)"
                    stroke="#ff8a65"
                    strokeWidth={Math.max(2, width / 300)}
                  />
                ) : null}
              </svg>
            </div>
            <div>
              <h4>Rectified preview</h4>
              <svg
                className={styles.anchorPreviewSvg}
                viewBox={`${tableViewBox.x} ${tableViewBox.y} ${tableViewBox.width} ${tableViewBox.height}`}
                role="img"
                aria-label="Rectified anchor gesture preview"
              >
                <polygon
                  points={pointsAttribute(anchorPreview.corners)}
                  fill="rgba(255, 138, 101, 0.18)"
                  stroke="#ff8a65"
                  strokeWidth="0.05"
                />
              </svg>
            </div>
          </div>
        </div>
      ) : null}
      {activeGesture !== null && activeGesture.kind !== "anchor" ? (
        <div
          className={styles.anchorGesturePreview}
          aria-label="Card gesture previews"
        >
          <strong>Card gesture preview</strong>
          <span>
            {activeGesture.kind === "move" ? "translation" : "rotation"} · card{" "}
            {activeGesture.cardId}
          </span>
          <div className={styles.anchorGesturePreviewGrid}>
            <div>
              <h4>Source preview</h4>
              <svg
                className={styles.anchorPreviewSvg}
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label="Source card gesture preview"
              >
                <polygon
                  points={pointsAttribute(
                    projectedPolygons.get(activeGesture.cardId) ?? [],
                  )}
                  fill="rgba(48, 201, 172, 0.18)"
                  stroke="#30c9ac"
                  strokeWidth={Math.max(2, width / 300)}
                />
              </svg>
            </div>
            <div>
              <h4>Rectified preview</h4>
              <svg
                className={styles.anchorPreviewSvg}
                viewBox={`${tableViewBox.x} ${tableViewBox.y} ${tableViewBox.width} ${tableViewBox.height}`}
                role="img"
                aria-label="Rectified card gesture preview"
              >
                <polygon
                  points={pointsAttribute(
                    cardPolygon(
                      draft.scene.poses.find(
                        (pose) => pose.card_id === activeGesture.cardId,
                      ) ?? draft.scene.poses[0],
                      draft.projection,
                    ),
                  )}
                  fill="rgba(48, 201, 172, 0.18)"
                  stroke="#30c9ac"
                  strokeWidth="0.05"
                />
              </svg>
            </div>
          </div>
        </div>
      ) : null}

      {!readOnly ? (
        <div className={styles.poseEditorControls}>
          {editorMode === "refine" && selectedPose !== null ? (
            <div className={styles.anchorControls}>
              <span>Anchor constraint</span>
              {ANCHOR_CONSTRAINTS.map((constraint) => (
                <button
                  key={constraint}
                  type="button"
                  aria-pressed={anchorConstraint === constraint}
                  onClick={() => setAnchorConstraint(constraint)}
                >
                  {constraint === "diagonal"
                    ? "Diagonal (D)"
                    : constraint === "card_x"
                      ? "Card X (X)"
                      : "Card Y (Y)"}
                </button>
              ))}
              <span>Corner</span>
              {[0, 1, 2, 3].map((cornerIndex) => (
                <button
                  key={cornerIndex}
                  type="button"
                  aria-pressed={anchorCornerIndex === cornerIndex}
                  onClick={() => setAnchorCornerIndex(cornerIndex)}
                >
                  {cornerIndex + 1}
                </button>
              ))}
              <label>
                Anchor X
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
              </label>
              <label>
                Anchor Y
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
              </label>
              <button
                type="button"
                onClick={emitNumericAnchorCommand}
                disabled={numericAnchor === null}
              >
                Apply anchor edit
              </button>
            </div>
          ) : null}
          {selectedPose !== null && onCardDecision !== undefined ? (
            <div className={styles.poseCardReviewControls}>
              <span>
                Card review: {selectedReviewState?.state ?? "reviewed"}
              </span>
              <button
                type="button"
                onClick={() => {
                  applyCardReviewState(selectedPose.card_id, "accepted");
                  onCardDecision(selectedPose.card_id, "accept");
                }}
                disabled={selectedReviewState?.state === "accepted"}
              >
                Accept card
              </button>
              <button
                type="button"
                onClick={() => {
                  applyCardReviewState(selectedPose.card_id, "rejected");
                  onCardDecision(selectedPose.card_id, "reject");
                }}
                disabled={selectedReviewState?.state === "rejected"}
              >
                Reject card
              </button>
              {unresolvedCardCount > 0 && onResolveRemaining !== undefined ? (
                <button
                  type="button"
                  onClick={() => {
                    acceptRemainingCards();
                    onResolveRemaining();
                  }}
                >
                  Accept remaining ({unresolvedCardCount})
                </button>
              ) : null}
            </div>
          ) : null}
          <button type="button" onClick={addCard}>
            Add standard-size card
          </button>
          <button
            type="button"
            onClick={removeCard}
            disabled={selectedPose === null || draft.scene.poses.length <= 1}
          >
            Remove selected card
          </button>
          <button
            type="button"
            onClick={() =>
              selectedPose &&
              applyAndCommit(
                { type: "bring_forward", cardId: selectedPose.card_id },
                "Card brought forward.",
              )
            }
            disabled={selectedPose === null}
          >
            Bring forward
          </button>
          <button
            type="button"
            onClick={() =>
              selectedPose &&
              applyAndCommit(
                { type: "send_backward", cardId: selectedPose.card_id },
                "Card sent backward.",
              )
            }
            disabled={selectedPose === null}
          >
            Send backward
          </button>
          <button
            type="button"
            onClick={() =>
              applyAndCommit(
                { type: "restore_initialized" },
                "Initialized card scene restored.",
              )
            }
          >
            Restore initialized scene
          </button>
          {selectedPose !== null ? (
            <label>
              Angle
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
            </label>
          ) : null}
        </div>
      ) : null}
      <p className={styles.poseEditorHelp}>
        {readOnly
          ? "Generated card scenes are immutable suggestions."
          : "One completed gesture produces one saved scene command. Polygon points are not part of this editor."}
      </p>
      {lastAnchorCommand !== null ? (
        <p className={styles.poseEditorStatus} role="status">
          Anchor command {lastAnchorCommand.sequence} ready for calibration
          refinement. Card geometry and homography are unchanged.
        </p>
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
        stroke={selected ? "#d9fff7" : "#80b6b7"}
        strokeWidth={selected ? 0.06 : 0.035}
        onPointerDown={(event) => {
          if (editorMode === "review") onPointerDown(event, "move");
        }}
      />
      <text
        x={pose.center[0]}
        y={pose.center[1]}
        textAnchor="middle"
        dominantBaseline="middle"
        fill="white"
        fontSize="0.14"
        pointerEvents="none"
      >
        {pose.card_id}
      </text>
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
  const minX = Math.min(...xs, -1) - 0.5;
  const maxX = Math.max(...xs, 1) + 0.5;
  const minY = Math.min(...ys, -1) - 0.5;
  const maxY = Math.max(...ys, 1) + 0.5;
  const width = (maxX - minX) / zoom;
  const height = (maxY - minY) / zoom;
  const centerX = (minX + maxX) / 2 + pan[0];
  const centerY = (minY + maxY) / 2 + pan[1];
  return { x: centerX - width / 2, y: centerY - height / 2, width, height };
}

function higherCards(scene: ReviewedCardScene, cardId: string): PoseCard[] {
  const index = scene.stacking_order.card_ids.indexOf(cardId);
  return scene.stacking_order.card_ids
    .slice(0, Math.max(0, index))
    .map((id) => scene.poses.find((pose) => pose.card_id === id))
    .filter((pose): pose is PoseCard => pose !== undefined);
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
