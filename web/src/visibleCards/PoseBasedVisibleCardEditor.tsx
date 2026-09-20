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
  applyPoseSceneAction,
  cardPolygon,
  nextManualPoseId,
  projectTablePoint,
  withSceneDigest,
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
};

type TableViewBox = { x: number; y: number; width: number; height: number };

export function PoseBasedVisibleCardEditor({
  recordingId,
  frame,
  scene,
  readOnly,
  onChange,
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
  const dragRef = useRef<{
    pointerId: number;
    cardId: string;
    mode: "move" | "rotate";
    dirty: boolean;
  } | null>(null);
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

  const getTablePoint = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>): TablePoint | null => {
      const rect = event.currentTarget.getBoundingClientRect();
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

  const handleTablePointerMove = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId || readOnly)
        return;
      const point = getTablePoint(event);
      const pose = draftRef.current.scene.poses.find(
        (candidate) => candidate.card_id === drag.cardId,
      );
      if (point === null || pose === undefined) return;
      const next = applyPoseSceneAction(
        draftRef.current,
        drag.mode === "move"
          ? { type: "move", cardId: drag.cardId, center: point }
          : {
              type: "rotate",
              cardId: drag.cardId,
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
      drag.dirty = true;
      draftRef.current = next;
      setDraft(next);
    },
    [getTablePoint, readOnly],
  );

  const finishTablePointer = useCallback(
    (event: ReactPointerEvent<SVGSVGElement>) => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      dragRef.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      if (drag.dirty) {
        commit(
          draftRef.current,
          drag.mode === "move"
            ? "Card moved on the virtual table."
            : "Card rotation saved.",
        );
      }
    },
    [commit],
  );

  const startTablePointer = useCallback(
    (
      event: ReactPointerEvent<SVGElement>,
      cardId: string,
      mode: "move" | "rotate",
    ) => {
      if (readOnly) return;
      event.preventDefault();
      event.stopPropagation();
      setSelectedCardId(cardId);
      dragRef.current = {
        pointerId: event.pointerId,
        cardId,
        mode,
        dirty: false,
      };
      (event.currentTarget as SVGSVGElement).setPointerCapture?.(
        event.pointerId,
      );
    },
    [readOnly],
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

      <div className={styles.poseEditorViews}>
        <div className={styles.poseViewPanel}>
          <h3>Source frame</h3>
          {sourceUrl === null ? (
            <p className={styles.editorHelp}>
              No exact source frame is available.
            </p>
          ) : (
            <div
              className={styles.poseSourceViewport}
              style={{ aspectRatio: `${width} / ${height}` }}
            >
              <img src={sourceUrl} alt="Selected visible-card source frame" />
              <svg
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label="Projected card scene"
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
                {draft.scene.poses.map((pose) => {
                  const polygon = projectedPolygons.get(pose.card_id) ?? [];
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
            <span data-tone="model">Dashed: model suggestion</span>
            <span data-tone="reviewed">
              Teal: derived visible-region preview
            </span>
          </p>
        </div>

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
            className={styles.poseTableSvg}
            viewBox={`${tableViewBox.x} ${tableViewBox.y} ${tableViewBox.width} ${tableViewBox.height}`}
            role="application"
            aria-label="Rectified virtual table"
            onPointerMove={handleTablePointerMove}
            onPointerUp={finishTablePointer}
            onPointerCancel={finishTablePointer}
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
                onSelect={() => setSelectedCardId(pose.card_id)}
                onPointerDown={(event, mode) =>
                  startTablePointer(event, pose.card_id, mode)
                }
                onKeyDown={(event) => handleCardKeyDown(event, pose.card_id)}
              />
            ))}
          </svg>
          <p className={styles.editorHelp}>
            Select a card, drag its body to move it, or drag the handle to
            rotate it. Arrow keys nudge the selected card; hold Shift for a
            coarse step.
          </p>
        </div>
      </div>

      {!readOnly ? (
        <div className={styles.poseEditorControls}>
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
    </section>
  );
}

function TableCard({
  pose,
  projection,
  selected,
  readOnly,
  onSelect,
  onPointerDown,
  onKeyDown,
}: {
  pose: PoseCard;
  projection: PoseSceneEnvelope["projection"];
  selected: boolean;
  readOnly: boolean;
  onSelect: () => void;
  onPointerDown: (
    event: ReactPointerEvent<SVGElement>,
    mode: "move" | "rotate",
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
        onPointerDown={(event) => onPointerDown(event, "move")}
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
      {!readOnly && selected ? (
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
