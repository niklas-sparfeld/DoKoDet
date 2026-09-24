import type { Point } from "./PipelineVisibleCardTypes";
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
import { posePolygon } from "./VisibleCardWorkbenchGeometry";
import {
  layerForSelection,
  type WorkbenchSelection,
  type WorkbenchViewpoint,
} from "./VisibleCardReviewWorkbenchState";
import type { Candidate } from "./PipelineVisibleCardTypes";

export function editorPoint(
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

export function sourcePointToTablePoint(
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

export function matchProjectionCornersToAnchor(
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

export function mappingStrokeWidth(
  viewpoint: WorkbenchViewpoint,
  width: number,
  zoom: number,
): number {
  return strokeWidth(viewpoint, width) / Math.max(zoom, 0.01);
}

export function mappingCornerRadius(
  viewpoint: WorkbenchViewpoint,
  width: number,
  zoom: number,
  rectifiedRadius: number,
): number {
  const radius =
    viewpoint === "camera" ? Math.max(4, width / 110) : rectifiedRadius;
  return radius / Math.max(zoom, 0.01);
}

export function candidatePolygons(
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

export function sourceCandidatePolygons(
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

export function transformSourcePolygon(
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

export function candidatePosePolygon(
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

export function sourcePoint(
  point: Point,
  width: number,
  height: number,
): [number, number] {
  return [(point.x * width) / 1000, (point.y * height) / 1000];
}

export function isSelected(
  selection: WorkbenchSelection | null,
  candidate: WorkbenchSelection,
): boolean {
  return (
    selection !== null &&
    layerForSelection(selection) === layerForSelection(candidate) &&
    selection.id === candidate.id
  );
}

export function renderOrder(
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

export function rotationHandle(
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

export function strokeWidth(
  viewpoint: WorkbenchViewpoint,
  width: number,
  selected = false,
): number {
  if (viewpoint === "rectified") return selected ? 0.06 : 0.035;
  return selected ? Math.max(2, width / 250) : Math.max(1.25, width / 500);
}

export function pointsAttribute(points: Array<[number, number]>): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

export function pathAttribute(points: Array<[number, number]>): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  return `M ${first[0]} ${first[1]} ${rest
    .map(([x, y]) => `L ${x} ${y}`)
    .join(" ")} Z`;
}

export function tableViewBox(
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

export function cameraViewBox(
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

export function surfaceViewBox(
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

export function rectifiedBackgroundPatches(
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
