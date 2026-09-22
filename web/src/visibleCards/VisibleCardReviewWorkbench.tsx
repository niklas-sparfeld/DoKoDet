import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { pipelineDerivedFramePath } from "../api/client";
import styles from "./PipelineVisibleCardEditor.module.css";
import {
  cardPolygon,
  projectImagePointToTable,
  projectTablePoint,
  type CardSceneProjection,
  type PoseCard,
  type PoseSceneEnvelope,
  type ReviewedCardScene,
  type TablePoint,
} from "./PoseBasedVisibleCardScene";
import type {
  Candidate,
  EditableFrame,
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

export type VisibleCardReviewWorkbenchProps = {
  recordingId: string;
  frame: EditableFrame;
  readOnly: boolean;
  candidateCalibration?: CandidateCalibration | null;
  initialPreferences?: Partial<WorkbenchPreferences>;
  onSelectionChange?: (selection: WorkbenchSelection | null) => void;
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

const M1_EDIT_REASON =
  "Editing is disabled while the shared workbench surface is being introduced.";

export function VisibleCardReviewWorkbench({
  recordingId,
  frame,
  readOnly,
  candidateCalibration = null,
  initialPreferences,
  onSelectionChange,
}: VisibleCardReviewWorkbenchProps) {
  const capabilities = workbenchCapabilitiesFromFrame(frame, readOnly);
  const [state, dispatch] = useReducer(
    visibleCardReviewWorkbenchReducer,
    { capabilities, preferences: initialPreferences },
    ({ capabilities: initialCapabilities, preferences }) =>
      createVisibleCardReviewWorkbenchState(initialCapabilities, preferences),
  );
  const previousFrameId = useRef(frame.itemId);

  useEffect(() => {
    if (previousFrameId.current === frame.itemId) return;
    previousFrameId.current = frame.itemId;
    dispatch({ type: "navigate_frame", capabilities });
  }, [capabilities, frame.itemId]);

  const activeState =
    state.frameId === frame.itemId
      ? state
      : createVisibleCardReviewWorkbenchState(
          capabilities,
          getWorkbenchPreferences(state),
        );
  const availability = getWorkbenchAvailability(capabilities);
  const scene = frame.outcome.card_scene ?? null;
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
        onToggleViewpoint={() => dispatch({ type: "toggle_viewpoint" })}
        onToggleLayer={(layer) => dispatch({ type: "toggle_layer", layer })}
      />
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
        onSelect={select}
        onKeyDown={handleSurfaceKeyDown}
      />
    </section>
  );
}

function WorkbenchCommandBar({
  state,
  availability,
  readOnly,
  onToggleViewpoint,
  onToggleLayer,
}: {
  state: VisibleCardReviewWorkbenchState;
  availability: ReturnType<typeof getWorkbenchAvailability>;
  readOnly: boolean;
  onToggleViewpoint: () => void;
  onToggleLayer: (layer: WorkbenchLayer) => void;
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
            const disabledReason = readOnly
              ? toolAvailability.mutationDisabledReason
              : M1_EDIT_REASON;
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
  onSelect,
  onKeyDown,
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
  onSelect: (selection: WorkbenchSelection) => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGSVGElement>) => void;
}) {
  const count = frame.outcome.candidates.length;
  const proposalLabel = `${count} visible-card proposal${count === 1 ? "" : "s"}`;
  if (viewpoint === "rectified" && scene !== null) {
    const viewBox = tableViewBox(scene.scene, scene.projection, viewport);
    return (
      <svg
        className={styles.workbenchRectifiedSurface}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        role="img"
        aria-label={`Rectified visible-card workbench with ${proposalLabel}`}
        tabIndex={0}
        onKeyDown={onKeyDown}
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
        onKeyDown={onKeyDown}
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
};

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
          aria-label={`Select visible card ${candidate.card_id}, polygon ${polygonIndex + 1}`}
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
}: LayerRenderContext) {
  if (scene === null) return null;
  return renderOrder(scene.scene).map((pose) => {
    const polygon = posePolygon(pose, scene.projection, viewpoint);
    const selected = isSelected(selection, {
      type: "virtual_card",
      id: pose.card_id,
    });
    return (
      <polygon
        key={pose.card_id}
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
        onClick={(event) => {
          event.stopPropagation();
          onSelect({ type: "virtual_card", id: pose.card_id });
        }}
      />
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

function renderOrder(scene: ReviewedCardScene): PoseCard[] {
  const poses = new Map(scene.poses.map((pose) => [pose.card_id, pose]));
  const ordered = scene.stacking_order.card_ids
    .slice()
    .reverse()
    .map((cardId) => poses.get(cardId))
    .filter((pose): pose is PoseCard => pose !== undefined);
  return [
    ...ordered,
    ...scene.poses.filter(
      (pose) => !scene.stacking_order.card_ids.includes(pose.card_id),
    ),
  ];
}

function strokeWidth(
  viewpoint: WorkbenchViewpoint,
  width: number,
  selected = false,
): number {
  if (viewpoint === "rectified") return selected ? 0.06 : 0.035;
  return selected ? Math.max(2, width / 250) : Math.max(1, width / 500);
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
