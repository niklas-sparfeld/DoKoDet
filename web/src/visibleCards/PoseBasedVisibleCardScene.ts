export const REVIEWED_CARD_SCENE_EDITOR_SCHEMA =
  "reviewed-card-scene-editor/v1" as const;
export const REVIEWED_CARD_SCENE_SCHEMA = "reviewed-card-scene/v1" as const;

export type TablePoint = [number, number];

export const ANCHOR_STATES = [
  "candidate",
  "accepted",
  "adjusted",
  "pinned",
  "excluded",
] as const;
export type AnchorState = (typeof ANCHOR_STATES)[number];

export type CalibrationAnchorCommand = {
  schema_version: "calibration-anchor-command/v1";
  command_id: string;
  sequence: number;
  expected_draft_revision: number;
  anchor_id: string;
  operation: "set_state" | "set_corners" | "restore";
  state: AnchorState | null;
  moved_corner: number | null;
  constraint: null;
  corners: TablePoint[] | null;
  operator_id: string;
};

export type DigestedCalibrationAnchorCommand = CalibrationAnchorCommand & {
  command_digest: string;
};

export type PoseCard = {
  schema_version: "card-pose/v1";
  card_id: string;
  center: TablePoint;
  rotation_degrees: number;
  source_suggestion_id: string | null;
  fit_diagnostics_digest: string | null;
};

export type PoseStackingOrder = {
  schema_version: "card-stacking-order/v1";
  card_ids: string[];
  uncertain_edges: Array<[string, string]>;
  contradictions: string[];
};

export type ReviewedCardScene = {
  schema_version: typeof REVIEWED_CARD_SCENE_SCHEMA;
  source_frame_id: string;
  source_frame_width: number;
  source_frame_height: number;
  calibration_revision_id: string;
  calibration_digest: string;
  poses: PoseCard[];
  stacking_order: PoseStackingOrder;
  derivation_recipe_version: string;
  scene_digest: string;
};

export type CardSceneProjection = {
  table_to_image_homography: number[][];
  card_short_size: number;
  card_long_size: number;
};

export type CardReviewState = {
  card_id: string;
  source: "proposal" | "manual";
  proposal_id: string | null;
  state: "pending" | "accepted" | "adjusted" | "rejected";
};

export type PoseSceneEnvelope = {
  schema_version: typeof REVIEWED_CARD_SCENE_EDITOR_SCHEMA;
  scene: ReviewedCardScene;
  initialized_scene: ReviewedCardScene;
  projection: CardSceneProjection;
  derived_region_receipt?: Record<string, unknown>;
  card_review_states?: CardReviewState[];
  completion_state?: "pending" | "complete" | "unusable";
  completion_reason?: string | null;
};

export type PoseSceneAction =
  | { type: "move"; cardId: string; center: TablePoint }
  | { type: "rotate"; cardId: string; rotationDegrees: number }
  | {
      type: "nudge";
      cardId: string;
      delta: TablePoint;
      rotationDeltaDegrees?: number;
    }
  | { type: "place"; cardId: string; index: number }
  | { type: "bring_forward"; cardId: string }
  | { type: "send_backward"; cardId: string }
  | {
      type: "add";
      cardId: string;
      center: TablePoint;
      rotationDegrees?: number;
    }
  | { type: "remove"; cardId: string }
  | { type: "restore_initialized" };

export function moveAnchorCorner(
  corners: TablePoint[],
  movedCorner: number,
  pointer: TablePoint,
): TablePoint[] {
  if (corners.length !== 4 || !Number.isInteger(movedCorner)) {
    return corners.map((point) => [...point] as TablePoint);
  }
  const original = corners.map((point) => [...point] as TablePoint);
  if (movedCorner < 0 || movedCorner > 3) return original;
  const result = original;
  result[movedCorner] = roundPoint(pointer);
  return result;
}

export function createCalibrationAnchorCommand(
  input: Omit<
    CalibrationAnchorCommand,
    | "schema_version"
    | "operation"
    | "state"
    | "moved_corner"
    | "constraint"
    | "corners"
  > & {
    moved_corner: number;
    corners: TablePoint[];
  },
): CalibrationAnchorCommand {
  return {
    schema_version: "calibration-anchor-command/v1",
    operation: "set_corners",
    state: "adjusted",
    ...input,
    constraint: null,
    corners: input.corners.map(roundPoint),
  };
}

export function createCalibrationAnchorStateCommand(input: {
  command_id: string;
  sequence: number;
  expected_draft_revision: number;
  anchor_id: string;
  state: AnchorState;
  operator_id: string;
}): CalibrationAnchorCommand {
  return {
    schema_version: "calibration-anchor-command/v1",
    command_id: input.command_id,
    sequence: input.sequence,
    expected_draft_revision: input.expected_draft_revision,
    anchor_id: input.anchor_id,
    operation: "set_state",
    state: input.state,
    moved_corner: null,
    constraint: null,
    corners: null,
    operator_id: input.operator_id,
  };
}

export async function withCalibrationAnchorCommandDigest(
  command: CalibrationAnchorCommand,
): Promise<DigestedCalibrationAnchorCommand> {
  const core = {
    ...command,
    corners: command.corners?.map(roundPoint) ?? null,
  };
  const bytes = new TextEncoder().encode(canonicalAnchorCommandStringify(core));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return { ...core, command_digest: hex };
}

export function readPoseScene(value: unknown): PoseSceneEnvelope | null {
  if (!isRecord(value)) return null;
  if (value.schema_version === REVIEWED_CARD_SCENE_EDITOR_SCHEMA) {
    const scene = readReviewedCardScene(value.scene);
    const initialized = readReviewedCardScene(value.initialized_scene);
    const projection = readProjection(value.projection);
    const reviewStates = readCardReviewStates(value.card_review_states);
    if (scene === null || initialized === null || projection === null)
      return null;
    return {
      schema_version: REVIEWED_CARD_SCENE_EDITOR_SCHEMA,
      scene,
      initialized_scene: initialized,
      projection,
      ...(reviewStates === null ? {} : { card_review_states: reviewStates }),
      ...(value.completion_state === "pending" ||
      value.completion_state === "complete" ||
      value.completion_state === "unusable"
        ? {
            completion_state: value.completion_state,
            completion_reason:
              typeof value.completion_reason === "string"
                ? value.completion_reason
                : null,
          }
        : {}),
      ...(readDerivedRegionReceipt(value.derived_region_receipt) === null
        ? {}
        : {
            derived_region_receipt: readDerivedRegionReceipt(
              value.derived_region_receipt,
            )!,
          }),
    };
  }
  if (value.schema_version === "card-scene-draft/v1") {
    const proposal = isRecord(value.proposal) ? value.proposal : null;
    const initialized = proposal?.initialized_scene;
    const projection = readProjection(value.projection);
    const states = readCardReviewStates(value.card_states);
    const completion = isRecord(value.completion) ? value.completion : null;
    if (
      initialized === null ||
      !isRecord(initialized) ||
      projection === null ||
      states === null ||
      completion === null ||
      !isCardSceneStatus(completion.state)
    )
      return null;
    const scene =
      completion.state === "pending"
        ? initialized
        : isRecord(value.reviewed) && isRecord(value.reviewed.scene)
          ? value.reviewed.scene
          : initialized;
    const parsedScene = readReviewedCardScene(scene);
    const parsedInitialized = readReviewedCardScene(initialized);
    if (parsedScene === null || parsedInitialized === null) return null;
    return {
      schema_version: REVIEWED_CARD_SCENE_EDITOR_SCHEMA,
      scene: parsedScene,
      initialized_scene: parsedInitialized,
      projection,
      card_review_states: states,
      completion_state: completion.state,
      completion_reason:
        typeof completion.reason === "string" ? completion.reason : null,
    };
  }
  if (value.schema_version !== REVIEWED_CARD_SCENE_SCHEMA) return null;
  const scene = readReviewedCardScene(value);
  const projection = readProjection(
    value.projection ?? value.editor_projection,
  );
  if (scene === null || projection === null) return null;
  return {
    schema_version: REVIEWED_CARD_SCENE_EDITOR_SCHEMA,
    scene,
    initialized_scene: cloneScene(scene),
    projection,
    ...(readDerivedRegionReceipt(value.derived_region_receipt) === null
      ? {}
      : {
          derived_region_receipt: readDerivedRegionReceipt(
            value.derived_region_receipt,
          )!,
        }),
  };
}

function readCardReviewStates(value: unknown): CardReviewState[] | null {
  if (!Array.isArray(value)) return null;
  const states = value.map((item) => {
    if (!isRecord(item)) return null;
    if (
      typeof item.card_id !== "string" ||
      (item.source !== "proposal" && item.source !== "manual") ||
      (item.state !== "pending" &&
        item.state !== "accepted" &&
        item.state !== "adjusted" &&
        item.state !== "rejected")
    )
      return null;
    return {
      card_id: item.card_id,
      source: item.source,
      proposal_id:
        typeof item.proposal_id === "string" ? item.proposal_id : null,
      state: item.state,
    } as CardReviewState;
  });
  return states.every((item): item is CardReviewState => item !== null)
    ? states
    : null;
}

function isCardSceneStatus(
  value: unknown,
): value is "pending" | "complete" | "unusable" {
  return value === "pending" || value === "complete" || value === "unusable";
}

export function applyPoseSceneAction(
  envelope: PoseSceneEnvelope,
  action: PoseSceneAction,
): PoseSceneEnvelope {
  if (action.type === "restore_initialized") {
    return {
      ...envelope,
      scene: cloneScene(envelope.initialized_scene),
    };
  }
  const scene = cloneScene(envelope.scene);
  const cardIndex = scene.poses.findIndex(
    (pose) => pose.card_id === action.cardId,
  );
  if (action.type !== "add" && cardIndex < 0) {
    return envelope;
  }

  if (action.type === "move") {
    scene.poses[cardIndex].center = [...action.center];
  } else if (action.type === "rotate") {
    scene.poses[cardIndex].rotation_degrees = normalizeDegrees(
      action.rotationDegrees,
    );
  } else if (action.type === "nudge") {
    const pose = scene.poses[cardIndex];
    pose.center = [
      pose.center[0] + action.delta[0],
      pose.center[1] + action.delta[1],
    ];
    pose.rotation_degrees = normalizeDegrees(
      pose.rotation_degrees + (action.rotationDeltaDegrees ?? 0),
    );
  } else if (action.type === "place") {
    scene.stacking_order.card_ids = placeId(
      scene.stacking_order.card_ids,
      action.cardId,
      action.index,
    );
  } else if (action.type === "bring_forward") {
    scene.stacking_order.card_ids = placeId(
      scene.stacking_order.card_ids,
      action.cardId,
      scene.stacking_order.card_ids.indexOf(action.cardId) - 1,
    );
  } else if (action.type === "send_backward") {
    scene.stacking_order.card_ids = placeId(
      scene.stacking_order.card_ids,
      action.cardId,
      scene.stacking_order.card_ids.indexOf(action.cardId) + 1,
    );
  } else if (action.type === "add") {
    if (scene.poses.some((pose) => pose.card_id === action.cardId))
      return envelope;
    scene.poses.push({
      schema_version: "card-pose/v1",
      card_id: action.cardId,
      center: [...action.center],
      rotation_degrees: normalizeDegrees(action.rotationDegrees ?? 0),
      source_suggestion_id: null,
      fit_diagnostics_digest: null,
    });
    scene.stacking_order.card_ids.push(action.cardId);
  } else if (action.type === "remove") {
    if (scene.poses.length <= 1) return envelope;
    scene.poses.splice(cardIndex, 1);
    scene.stacking_order.card_ids = scene.stacking_order.card_ids.filter(
      (cardId) => cardId !== action.cardId,
    );
  }
  return {
    ...envelope,
    scene,
  };
}

export function nextManualPoseId(scene: ReviewedCardScene): string {
  const used = new Set(scene.poses.map((pose) => pose.card_id));
  let index = 1;
  while (used.has(`manual-card-${index}`)) index += 1;
  return `manual-card-${index}`;
}

export function cardPolygon(
  pose: PoseCard,
  projection: CardSceneProjection,
): TablePoint[] {
  const angle = (pose.rotation_degrees * Math.PI) / 180;
  const shortAxis: TablePoint = [Math.cos(angle), Math.sin(angle)];
  const longAxis: TablePoint = [-Math.sin(angle), Math.cos(angle)];
  const short = scale(shortAxis, projection.card_short_size / 2);
  const long = scale(longAxis, projection.card_long_size / 2);
  const center = pose.center;
  return [
    subtract(subtract(center, short), long),
    add(subtract(center, long), short),
    add(add(center, short), long),
    subtract(add(center, long), short),
  ];
}

export function projectTablePoint(
  point: TablePoint,
  homography: number[][],
): [number, number] | null {
  if (homography.length !== 3 || homography.some((row) => row.length !== 3))
    return null;
  const denominator =
    homography[2][0] * point[0] +
    homography[2][1] * point[1] +
    homography[2][2];
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-9)
    return null;
  const x =
    (homography[0][0] * point[0] +
      homography[0][1] * point[1] +
      homography[0][2]) /
    denominator;
  const y =
    (homography[1][0] * point[0] +
      homography[1][1] * point[1] +
      homography[1][2]) /
    denominator;
  return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
}

export function projectImagePointToTable(
  point: [number, number],
  homography: number[][],
): TablePoint | null {
  const inverse = invertHomography(homography);
  return inverse === null ? null : projectTablePoint(point, inverse);
}

export async function withSceneDigest(
  envelope: PoseSceneEnvelope,
): Promise<PoseSceneEnvelope> {
  const scene = cloneScene(envelope.scene);
  const core = Object.fromEntries(
    Object.entries(scene).filter(([key]) => key !== "scene_digest"),
  );
  const bytes = new TextEncoder().encode(stableStringify(core));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  return {
    ...envelope,
    scene: { ...scene, scene_digest: hex },
  };
}

export function cloneScene(scene: ReviewedCardScene): ReviewedCardScene {
  return {
    ...scene,
    poses: scene.poses.map((pose) => ({ ...pose, center: [...pose.center] })),
    stacking_order: {
      ...scene.stacking_order,
      card_ids: [...scene.stacking_order.card_ids],
      uncertain_edges: scene.stacking_order.uncertain_edges.map((edge) => [
        ...edge,
      ]),
      contradictions: [...scene.stacking_order.contradictions],
    },
  };
}

function readReviewedCardScene(value: unknown): ReviewedCardScene | null {
  if (!isRecord(value) || value.schema_version !== REVIEWED_CARD_SCENE_SCHEMA)
    return null;
  const rawPoses = value.poses;
  const rawOrder = value.stacking_order;
  if (
    typeof value.source_frame_id !== "string" ||
    !isPositiveInteger(value.source_frame_width) ||
    !isPositiveInteger(value.source_frame_height) ||
    typeof value.calibration_revision_id !== "string" ||
    typeof value.calibration_digest !== "string" ||
    !Array.isArray(rawPoses) ||
    rawPoses.length === 0 ||
    !isRecord(rawOrder) ||
    typeof value.derivation_recipe_version !== "string" ||
    typeof value.scene_digest !== "string"
  )
    return null;
  const poses = rawPoses
    .map(readPose)
    .filter((pose): pose is PoseCard => pose !== null);
  if (
    poses.length !== rawPoses.length ||
    new Set(poses.map((pose) => pose.card_id)).size !== poses.length
  )
    return null;
  const order = readStackingOrder(rawOrder);
  if (order === null || order.card_ids.length !== poses.length) return null;
  if (new Set(order.card_ids).size !== order.card_ids.length) return null;
  if (
    order.card_ids.some(
      (cardId) => !poses.some((pose) => pose.card_id === cardId),
    )
  )
    return null;
  return {
    schema_version: REVIEWED_CARD_SCENE_SCHEMA,
    source_frame_id: value.source_frame_id,
    source_frame_width: value.source_frame_width,
    source_frame_height: value.source_frame_height,
    calibration_revision_id: value.calibration_revision_id,
    calibration_digest: value.calibration_digest,
    poses,
    stacking_order: order,
    derivation_recipe_version: value.derivation_recipe_version,
    scene_digest: value.scene_digest,
  };
}

function readPose(value: unknown): PoseCard | null {
  if (!isRecord(value) || value.schema_version !== "card-pose/v1") return null;
  const center = value.center;
  if (
    typeof value.card_id !== "string" ||
    !Array.isArray(center) ||
    center.length !== 2 ||
    !center.every(
      (coordinate) =>
        typeof coordinate === "number" && Number.isFinite(coordinate),
    ) ||
    typeof value.rotation_degrees !== "number" ||
    !Number.isFinite(value.rotation_degrees) ||
    (value.source_suggestion_id !== null &&
      typeof value.source_suggestion_id !== "string") ||
    (value.fit_diagnostics_digest !== null &&
      typeof value.fit_diagnostics_digest !== "string")
  )
    return null;
  return {
    schema_version: "card-pose/v1",
    card_id: value.card_id,
    center: [center[0], center[1]],
    rotation_degrees: value.rotation_degrees,
    source_suggestion_id: value.source_suggestion_id,
    fit_diagnostics_digest: value.fit_diagnostics_digest,
  };
}

function readStackingOrder(
  value: Record<string, unknown>,
): PoseStackingOrder | null {
  if (
    value.schema_version !== "card-stacking-order/v1" ||
    !Array.isArray(value.card_ids) ||
    !Array.isArray(value.uncertain_edges) ||
    !Array.isArray(value.contradictions) ||
    value.card_ids.some((cardId) => typeof cardId !== "string") ||
    value.contradictions.some((entry) => typeof entry !== "string")
  )
    return null;
  const uncertainEdges = value.uncertain_edges
    .filter(
      (edge): edge is unknown[] =>
        Array.isArray(edge) &&
        edge.length === 2 &&
        edge.every((cardId) => typeof cardId === "string"),
    )
    .map((edge) => [edge[0] as string, edge[1] as string] as [string, string]);
  if (uncertainEdges.length !== value.uncertain_edges.length) return null;
  return {
    schema_version: "card-stacking-order/v1",
    card_ids: [...value.card_ids],
    uncertain_edges: uncertainEdges,
    contradictions: [...value.contradictions],
  };
}

function readProjection(value: unknown): CardSceneProjection | null {
  if (!isRecord(value)) return null;
  const homography = value.table_to_image_homography;
  if (
    !Array.isArray(homography) ||
    homography.length !== 3 ||
    homography.some(
      (row) =>
        !Array.isArray(row) ||
        row.length !== 3 ||
        row.some(
          (entry) => typeof entry !== "number" || !Number.isFinite(entry),
        ),
    ) ||
    typeof value.card_short_size !== "number" ||
    value.card_short_size <= 0 ||
    typeof value.card_long_size !== "number" ||
    value.card_long_size <= 0
  )
    return null;
  return {
    table_to_image_homography: homography.map((row) => [...row]),
    card_short_size: value.card_short_size,
    card_long_size: value.card_long_size,
  };
}

function readDerivedRegionReceipt(
  value: unknown,
): Record<string, unknown> | null {
  return isRecord(value) ? { ...value } : null;
}

function placeId(
  ids: string[],
  cardId: string,
  requestedIndex: number,
): string[] {
  const currentIndex = ids.indexOf(cardId);
  if (currentIndex < 0) return ids;
  const next = ids.filter((id) => id !== cardId);
  const index = Math.max(0, Math.min(next.length, requestedIndex));
  next.splice(index, 0, cardId);
  return next;
}

function normalizeDegrees(value: number): number {
  const normalized = ((((value + 180) % 360) + 360) % 360) - 180;
  return Object.is(normalized, -0) ? 0 : normalized;
}

function add(left: TablePoint, right: TablePoint): TablePoint {
  return [left[0] + right[0], left[1] + right[1]];
}

function subtract(left: TablePoint, right: TablePoint): TablePoint {
  return [left[0] - right[0], left[1] - right[1]];
}

function scale(point: TablePoint, factor: number): TablePoint {
  return [point[0] * factor, point[1] * factor];
}

function invertHomography(homography: number[][]): number[][] | null {
  if (homography.length !== 3 || homography.some((row) => row.length !== 3))
    return null;
  const [a, b, c] = homography[0];
  const [d, e, f] = homography[1];
  const [g, h, i] = homography[2];
  const determinant =
    a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-9)
    return null;
  return [
    [
      (e * i - f * h) / determinant,
      (c * h - b * i) / determinant,
      (b * f - c * e) / determinant,
    ],
    [
      (f * g - d * i) / determinant,
      (a * i - c * g) / determinant,
      (c * d - a * f) / determinant,
    ],
    [
      (d * h - e * g) / determinant,
      (b * g - a * h) / determinant,
      (a * e - b * d) / determinant,
    ],
  ];
}

function roundPoint(point: TablePoint): TablePoint {
  return [Number(point[0].toFixed(6)), Number(point[1].toFixed(6))];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, child]) => `${JSON.stringify(key)}:${stableStringify(child)}`);
  return `{${entries.join(",")}}`;
}

function canonicalAnchorCommandStringify(
  command: CalibrationAnchorCommand,
): string {
  const entries = Object.entries(command)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, value]) => {
      if (key !== "corners") {
        return `${JSON.stringify(key)}:${stableStringify(value)}`;
      }
      const corners = (value as TablePoint[])
        .map(
          (point) =>
            `[${point.map((coordinate) => canonicalFloat(coordinate)).join(",")}]`,
        )
        .join(",");
      return `${JSON.stringify(key)}:[${corners}]`;
    });
  return `{${entries.join(",")}}`;
}

function canonicalFloat(value: number): string {
  const rounded = Number(value.toFixed(6));
  if (Object.is(rounded, -0)) return "-0.0";
  if (Number.isInteger(rounded)) return `${rounded.toFixed(1)}`;
  return JSON.stringify(rounded);
}
