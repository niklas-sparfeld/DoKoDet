import { createPortal } from "react-dom";
import { useEffect, useMemo, useState } from "react";
import {
  createDokoDetectorClient,
  type PipelineCalibration,
} from "../api/client";
import { useProfileName } from "../profile/profile";
import {
  editPipelineNode,
  getPipelineNodeRevision,
  reviewPipelineNodeCoverage,
  listPipelineNodeReviews,
  reviewPipelineNodeItem,
  reviewPipelineNodeOverall,
  type PipelineNodeRevision,
} from "../pipeline/pipelineNodeClient";
import styles from "./PipelineNodeVisibleCardEditor.module.css";
import {
  GeometrySurface,
  type GeometryFrameIdentity,
  type GeometryOverlay,
} from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";

type SceneFrame = Record<string, unknown> & {
  frame_id: string;
  frame_identity: Record<string, unknown>;
  calibration: { revision_id: string; digest: string } | null;
  scene: Record<string, unknown> | null;
};
type SceneContent = Record<string, unknown> & {
  schema_version: "virtual-scene-data/v1";
  frames: SceneFrame[];
};

type CardPose = {
  card_id: string;
  center: [number, number];
  rotation_degrees: number;
};

function posesForScene(scene: Record<string, unknown> | null): CardPose[] {
  if (scene === null || !Array.isArray(scene.poses)) return [];
  return scene.poses.filter((pose): pose is CardPose => {
    if (pose === null || typeof pose !== "object") return false;
    const value = pose as Record<string, unknown>;
    return (
      typeof value.card_id === "string" &&
      Array.isArray(value.center) &&
      value.center.length === 2 &&
      value.center.every(
        (part) => typeof part === "number" && Number.isFinite(part),
      ) &&
      typeof value.rotation_degrees === "number" &&
      Number.isFinite(value.rotation_degrees)
    );
  });
}

function parseSceneDraft(
  draft: string,
  fallback: Record<string, unknown> | null,
): Record<string, unknown> {
  const value: unknown = JSON.parse(draft);
  if (value === null) return fallback ?? {};
  if (typeof value !== "object" || Array.isArray(value))
    throw new Error("Scene data must be an object or null.");
  return value as Record<string, unknown>;
}

function projectPoint(
  matrix: number[][],
  x: number,
  y: number,
): [number, number] | null {
  if (matrix.length !== 3 || matrix.some((row) => row.length !== 3))
    return null;
  const denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2];
  if (!Number.isFinite(denominator) || Math.abs(denominator) < 1e-12)
    return null;
  const projected: [number, number] = [
    (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
    (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
  ];
  return projected.every(Number.isFinite) ? projected : null;
}

function virtualSceneOverlays(
  frame: SceneFrame,
  identity: GeometryFrameIdentity,
  calibration: PipelineCalibration | null,
  viewpoint: "source" | "rectified",
): GeometryOverlay[] {
  if (frame.scene === null || calibration === null) return [];
  const poses = posesForScene(frame.scene);
  const overlays: GeometryOverlay[] = [];
  for (const pose of poses) {
    const angle = (pose.rotation_degrees * Math.PI) / 180;
    const short = calibration.card_short_size / 2;
    const long = calibration.card_long_size / 2;
    const shortAxis: [number, number] = [Math.cos(angle), Math.sin(angle)];
    const longAxis: [number, number] = [-Math.sin(angle), Math.cos(angle)];
    const tablePoints = [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ].map(
      ([shortSign, longSign]) =>
        [
          pose.center[0] +
            shortSign * short * shortAxis[0] +
            longSign * long * longAxis[0],
          pose.center[1] +
            shortSign * short * shortAxis[1] +
            longSign * long * longAxis[1],
        ] as [number, number],
    );
    const bounds =
      viewpoint === "rectified"
        ? tableBounds(calibration, identity.width, identity.height)
        : null;
    const points = tablePoints.map(([x, y]) =>
      viewpoint === "source"
        ? projectPoint(calibration.table_to_image, x, y)
        : bounds === null
          ? null
          : ([
              ((x - bounds.minX) / (bounds.maxX - bounds.minX)) *
                identity.width,
              ((y - bounds.minY) / (bounds.maxY - bounds.minY)) *
                identity.height,
            ] as [number, number]),
    );
    if (points.some((point) => point === null)) continue;
    overlays.push({
      id: pose.card_id,
      label: `Card pose ${pose.card_id}`,
      pattern: "dashed",
      frame: identity,
      calibration: {
        revisionId: calibration.calibration_revision_id,
        digest: calibration.calibration_digest,
      },
      requiresCalibration: true,
      geometry: { kind: "polygon", points: points as [number, number][] },
    });
  }
  return overlays;
}

function tableBounds(
  calibration: PipelineCalibration,
  width: number,
  height: number,
): { minX: number; maxX: number; minY: number; maxY: number } | null {
  const corners = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ] as const;
  const points = corners.map(([x, y]) =>
    projectPoint(calibration.image_to_table, x, y),
  );
  if (points.some((point) => point === null)) return null;
  const valid = points as [number, number][];
  const bounds = {
    minX: Math.min(...valid.map(([x]) => x)),
    maxX: Math.max(...valid.map(([x]) => x)),
    minY: Math.min(...valid.map(([, y]) => y)),
    maxY: Math.max(...valid.map(([, y]) => y)),
  };
  return bounds.maxX > bounds.minX && bounds.maxY > bounds.minY ? bounds : null;
}

async function rectifyImage(
  imageUrl: string,
  calibration: PipelineCalibration,
): Promise<string> {
  const image = new Image();
  image.src = imageUrl;
  await image.decode();
  const width = calibration.frame_width;
  const height = calibration.frame_height;
  const bounds = tableBounds(calibration, width, height);
  if (bounds === null)
    throw new Error(
      "Calibration cannot map the source frame to table coordinates.",
    );
  const sourceCanvas = document.createElement("canvas");
  sourceCanvas.width = width;
  sourceCanvas.height = height;
  const sourceContext = sourceCanvas.getContext("2d", {
    willReadFrequently: true,
  });
  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = width;
  outputCanvas.height = height;
  const outputContext = outputCanvas.getContext("2d");
  if (sourceContext === null || outputContext === null)
    throw new Error("Canvas rendering is unavailable.");
  sourceContext.drawImage(image, 0, 0, width, height);
  const source = sourceContext.getImageData(0, 0, width, height);
  const output = outputContext.createImageData(width, height);
  for (let y = 0; y < height; y += 1) {
    const tableY =
      bounds.minY + ((y + 0.5) / height) * (bounds.maxY - bounds.minY);
    for (let x = 0; x < width; x += 1) {
      const tableX =
        bounds.minX + ((x + 0.5) / width) * (bounds.maxX - bounds.minX);
      const sourcePoint = projectPoint(
        calibration.table_to_image,
        tableX,
        tableY,
      );
      if (sourcePoint === null) continue;
      const sourceX = Math.round(sourcePoint[0]);
      const sourceY = Math.round(sourcePoint[1]);
      if (sourceX < 0 || sourceX >= width || sourceY < 0 || sourceY >= height)
        continue;
      const sourceIndex = (sourceY * width + sourceX) * 4;
      const targetIndex = (y * width + x) * 4;
      output.data.set(
        source.data.subarray(sourceIndex, sourceIndex + 4),
        targetIndex,
      );
    }
  }
  outputContext.putImageData(output, 0, 0);
  return outputCanvas.toDataURL("image/png");
}

type Props = {
  recordingId: string;
  sourceSha256: string;
  nodeId: string;
  revisionId: string;
  selectionItemId: string | null;
  onPositionChange: (itemId: string, timeUs: number | null) => void;
  onRevisionChange: (
    sourceNodeId: string,
    sourceRevisionId: string,
    nodeId: string,
    revisionId: string,
    frameId: string,
    timeUs: number | null,
  ) => void;
};

function parseContent(value: Record<string, unknown>): SceneContent {
  if (
    value.schema_version !== "virtual-scene-data/v1" ||
    !Array.isArray(value.frames)
  )
    throw new Error("The selected node does not contain virtual scenes.");
  return value as SceneContent;
}

function frameTime(frame: SceneFrame): number | null {
  const value = frame.frame_identity.requested_time_us;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function PipelineNodeVirtualSceneEditor({
  recordingId,
  sourceSha256,
  nodeId,
  revisionId,
  selectionItemId,
  onPositionChange,
  onRevisionChange,
}: Props) {
  const profileName = useProfileName();
  const reviewer =
    profileName
      .trim()
      .replace(/[^A-Za-z0-9._:-]+/g, "-")
      .slice(0, 128) || "workspace-operator";
  const [revision, setRevision] = useState<PipelineNodeRevision | null>(null);
  const [content, setContent] = useState<SceneContent | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(selectionItemId);
  const [draft, setDraft] = useState("");
  const [reviews, setReviews] = useState<Array<Record<string, unknown>>>([]);
  const [inspected, setInspected] = useState<Set<string>>(() => new Set());
  const [portalTargets, setPortalTargets] = useState<{
    inspector: Element | null;
    center: Element | null;
    rail: Element | null;
  }>({ inspector: null, center: null, rail: null });
  const [message, setMessage] = useState(
    "Loading selected virtual-scene revision…",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewpoint, setViewpoint] = useState<"source" | "rectified">("source");
  const [selectedPoseId, setSelectedPoseId] = useState<string | null>(null);
  const [calibrationResponse, setCalibrationResponse] =
    useState<PipelineCalibration | null>(null);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);
  const client = useMemo(() => createDokoDetectorClient(), []);
  const frames = useMemo(() => content?.frames ?? [], [content]);
  const selected =
    selectedId === null
      ? undefined
      : frames.find((frame) => frame.frame_id === selectedId);
  const readOnly =
    revision !== null && revision.head_revision_id !== revision.revision_id;
  const geometryUnavailableFrameIds =
    revision?.metadata.migration !== null &&
    typeof revision?.metadata.migration === "object" &&
    Array.isArray(
      (revision.metadata.migration as Record<string, unknown>)
        .geometry_unavailable_frame_ids,
    )
      ? ((revision.metadata.migration as Record<string, unknown>)
          .geometry_unavailable_frame_ids as unknown[])
      : [];
  const geometryUnavailable =
    selectedId !== null && geometryUnavailableFrameIds.includes(selectedId);
  const selectedReviews = reviews.filter(
    (review) => review.kind === "item" && review.item_id === selectedId,
  );

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      getPipelineNodeRevision(nodeId, revisionId),
      listPipelineNodeReviews(nodeId, revisionId),
    ])
      .then(([loaded, loadedReviews]) => {
        if (loaded.content_type !== "virtual_scenes")
          throw new Error("The selected node is not a virtual-scene data set.");
        if (cancelled) return;
        const next = parseContent(loaded.content);
        setRevision(loaded);
        setContent(next);
        setReviews(loadedReviews);
        const wanted = selectionItemId ?? next.frames[0]?.frame_id ?? null;
        const exists =
          wanted !== null &&
          next.frames.some((frame) => frame.frame_id === wanted);
        setSelectedId(exists ? wanted : null);
        const initialFrame = exists
          ? next.frames.find((frame) => frame.frame_id === wanted)
          : undefined;
        setDraft(
          initialFrame?.scene === null || initialFrame === undefined
            ? "null"
            : json(initialFrame.scene),
        );
        setMessage(
          !exists && selectionItemId !== null
            ? "The selected frame is not present in this revision. No other frame was selected."
            : loaded.head_revision_id === loaded.revision_id
              ? "Current revision"
              : "Historical revision · read only",
        );
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setMessage("Could not load this exact virtual-scene revision.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId, revisionId, selectionItemId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPortalTargets({
        inspector: document.querySelector(
          '[data-visible-card-inspector-slot="action"]',
        ),
        center: document.querySelector('[data-slot="center"]'),
        rail: document.querySelector("[data-visible-card-navigation-slot]"),
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const timeUs = selected === undefined ? null : frameTime(selected);
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: recordingId,
    sourceSha256: portalTargets.center === null ? "" : sourceSha256,
    requestedTimeUs: timeUs ?? 0,
    mode: "exact",
  });
  const frameMatches =
    portalTargets.center === null ||
    (selected !== undefined &&
      selected.frame_identity.source_video_sha256 === sourceSha256 &&
      typeof selected.frame_identity.requested_time_us === "number" &&
      typeof selected.frame_identity.frame_index === "number" &&
      typeof selected.frame_identity.presentation_timestamp_us === "number" &&
      typeof selected.frame_identity.width === "number" &&
      typeof selected.frame_identity.height === "number" &&
      typeof selected.frame_identity.image_sha256 === "string" &&
      frameState.state === "ready" &&
      frameState.frame.requestedTimeUs ===
        selected.frame_identity.requested_time_us &&
      frameState.frame.identity.frameId ===
        `${selected.frame_identity.frame_index}@${selected.frame_identity.presentation_timestamp_us}` &&
      frameState.frame.resolvedTimeUs ===
        selected.frame_identity.presentation_timestamp_us &&
      frameState.frame.identity.width === selected.frame_identity.width &&
      frameState.frame.identity.height === selected.frame_identity.height &&
      frameState.frame.identity.contentSha256 ===
        selected.frame_identity.image_sha256);
  useEffect(() => {
    const calibrationId = selected?.calibration?.revision_id;
    if (portalTargets.center === null || calibrationId === undefined) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void client
        .getPipelineCalibration(recordingId, calibrationId, {
          signal: controller.signal,
        })
        .then((value) => {
          if (controller.signal.aborted) return;
          if (
            value.recording_id !== recordingId ||
            value.calibration_revision_id !== calibrationId ||
            value.calibration_digest !== selected?.calibration?.digest
          ) {
            setCalibrationError(
              "The calibration response does not match this scene revision.",
            );
            return;
          }
          setCalibrationError(null);
          setCalibrationResponse(value);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setCalibrationError(
            reason instanceof Error
              ? reason.message
              : "The exact calibration could not be loaded.",
          );
        });
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [client, portalTargets.center, recordingId, selected?.calibration]);
  const calibrationMatches =
    frameMatches &&
    selected?.calibration !== null &&
    selected?.calibration !== undefined &&
    selected.calibration.revision_id.length > 0 &&
    /^[a-f\d]{64}$/i.test(selected.calibration.digest) &&
    (portalTargets.center === null ||
      (calibrationResponse?.recording_id === recordingId &&
        calibrationResponse.calibration_revision_id ===
          selected.calibration.revision_id &&
        calibrationResponse.calibration_digest ===
          selected.calibration.digest &&
        frameState.state === "ready" &&
        calibrationResponse.frame_width === frameState.frame.identity.width &&
        calibrationResponse.frame_height ===
          frameState.frame.identity.height)) &&
    (selected.scene === null ||
      ((portalTargets.center === null ||
        (frameState.state === "ready" &&
          selected.scene.source_frame_id === selected.frame_id &&
          selected.scene.source_frame_width ===
            frameState.frame.identity.width &&
          selected.scene.source_frame_height ===
            frameState.frame.identity.height)) &&
        selected.scene.calibration_revision_id ===
          selected.calibration.revision_id &&
        selected.scene.calibration_digest === selected.calibration.digest));
  const [rectifiedResult, setRectifiedResult] = useState<{
    sourceUrl: string;
    calibrationId: string;
    calibrationDigest: string;
    imageUrl: string;
  } | null>(null);
  const exactImageUrl =
    frameState.state === "ready" ? frameState.frame.imageUrl : null;
  const rectifiedImageUrl =
    calibrationMatches &&
    exactImageUrl !== null &&
    rectifiedResult?.sourceUrl === exactImageUrl &&
    rectifiedResult.calibrationId ===
      calibrationResponse?.calibration_revision_id &&
    rectifiedResult.calibrationDigest ===
      calibrationResponse?.calibration_digest
      ? rectifiedResult.imageUrl
      : null;
  useEffect(() => {
    if (
      !calibrationMatches ||
      exactImageUrl === null ||
      calibrationResponse === null
    )
      return;
    let current = true;
    void rectifyImage(exactImageUrl, calibrationResponse)
      .then((url) => {
        if (current)
          setRectifiedResult({
            sourceUrl: exactImageUrl,
            calibrationId: calibrationResponse.calibration_revision_id,
            calibrationDigest: calibrationResponse.calibration_digest,
            imageUrl: url,
          });
      })
      .catch((reason: unknown) => {
        if (current) {
          setCalibrationError(
            reason instanceof Error
              ? reason.message
              : "Rectified viewpoint is unavailable.",
          );
        }
      });
    return () => {
      current = false;
    };
  }, [calibrationMatches, calibrationResponse, exactImageUrl]);
  let draftScene = selected?.scene ?? null;
  try {
    const parsed = JSON.parse(draft) as unknown;
    draftScene =
      parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
  } catch {
    // Keep the last valid source geometry visible while the JSON editor is incomplete.
  }
  const scenePoses = posesForScene(draftScene);
  const activePose =
    scenePoses.find((pose) => pose.card_id === selectedPoseId) ??
    scenePoses[0] ??
    null;
  const overlays =
    frameMatches &&
    calibrationMatches &&
    selected !== undefined &&
    frameState.state === "ready"
      ? virtualSceneOverlays(
          { ...selected, scene: draftScene },
          frameState.frame.identity,
          calibrationResponse,
          viewpoint,
        )
      : [];

  const choose = (frame: SceneFrame) => {
    setSelectedId(frame.frame_id);
    setSelectedPoseId(null);
    setDraft(frame.scene === null ? "null" : json(frame.scene));
    onPositionChange(frame.frame_id, frameTime(frame));
  };

  const updatePose = (
    field: "center" | "rotation_degrees",
    value: number[] | number,
  ) => {
    if (selected === undefined || activePose === null) return;
    const scene = parseSceneDraft(draft, selected.scene);
    const poses = posesForScene(scene);
    const nextPoses = poses.map((pose) =>
      pose.card_id === activePose.card_id ? { ...pose, [field]: value } : pose,
    );
    setDraft(json({ ...scene, poses: nextPoses }));
  };
  const updatePoseFromSurface = (poseId: string, x: number, y: number) => {
    if (
      selected === undefined ||
      !frameMatches ||
      !calibrationMatches ||
      calibrationResponse === null
    )
      return;
    const tablePoint =
      viewpoint === "source"
        ? projectPoint(calibrationResponse.image_to_table, x, y)
        : (() => {
            const bounds = tableBounds(
              calibrationResponse,
              calibrationResponse.frame_width,
              calibrationResponse.frame_height,
            );
            return bounds === null
              ? null
              : ([
                  bounds.minX +
                    (x / calibrationResponse.frame_width) *
                      (bounds.maxX - bounds.minX),
                  bounds.minY +
                    (y / calibrationResponse.frame_height) *
                      (bounds.maxY - bounds.minY),
                ] as [number, number]);
          })();
    if (tablePoint === null) return;
    const scene = parseSceneDraft(draft, selected.scene);
    const nextPoses = posesForScene(scene).map((pose) =>
      pose.card_id === poseId ? { ...pose, center: tablePoint } : pose,
    );
    setDraft(json({ ...scene, poses: nextPoses }));
  };

  const stackingOrder = draftScene?.stacking_order;
  const orderedCardIds =
    stackingOrder !== null &&
    typeof stackingOrder === "object" &&
    Array.isArray((stackingOrder as Record<string, unknown>).card_ids)
      ? (
          (stackingOrder as Record<string, unknown>).card_ids as unknown[]
        ).filter((cardId): cardId is string => typeof cardId === "string")
      : [];
  const canReorderPose = (direction: -1 | 1) => {
    if (activePose === null) return true;
    const index = orderedCardIds.indexOf(activePose.card_id);
    return (
      index >= 0 &&
      index + direction >= 0 &&
      index + direction < orderedCardIds.length
    );
  };
  const reorderPose = (direction: -1 | 1) => {
    if (
      selected === undefined ||
      activePose === null ||
      !canReorderPose(direction)
    )
      return;
    const scene = parseSceneDraft(draft, selected.scene);
    const order = [...orderedCardIds];
    const index = order.indexOf(activePose.card_id);
    [order[index], order[index + direction]] = [
      order[index + direction],
      order[index],
    ];
    const current = scene.stacking_order;
    const previous =
      current !== null && typeof current === "object"
        ? (current as Record<string, unknown>)
        : {};
    setDraft(
      json({ ...scene, stacking_order: { ...previous, card_ids: order } }),
    );
  };

  const save = async () => {
    if (
      content === null ||
      revision === null ||
      selected === undefined ||
      readOnly ||
      !calibrationMatches
    )
      return;
    let scene: unknown;
    try {
      scene = JSON.parse(draft) as unknown;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return;
    }
    if (scene !== null && (typeof scene !== "object" || Array.isArray(scene))) {
      setError("Scene data must be an object or null.");
      return;
    }
    const updatedFrame = {
      ...selected,
      scene: scene as Record<string, unknown> | null,
    };
    const nextContent: SceneContent = {
      ...content,
      frames: content.frames.map((frame) =>
        frame.frame_id === selected.frame_id ? updatedFrame : frame,
      ),
    };
    if (JSON.stringify(selected.scene) === JSON.stringify(scene)) {
      setMessage("No scene changes to save.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage("Saving scene changes…");
    try {
      const result = await editPipelineNode(nodeId, {
        expected_revision_id: revision.revision_id,
        idempotency_key: `virtual-scene-edit-${crypto.randomUUID()}`,
        actor: { kind: "human", id: reviewer },
        content: nextContent,
        base_pointers: Object.fromEntries(
          content.frames.map((frame, index) => [
            frame.frame_id,
            `/frames/${index}`,
          ]),
        ),
        pointers: Object.fromEntries(
          nextContent.frames.map((frame, index) => [
            frame.frame_id,
            `/frames/${index}`,
          ]),
        ),
        operations: [
          {
            kind: "replace",
            before: [selected.frame_id],
            after: [selected.frame_id],
          },
        ],
      });
      setMessage(
        result.copied
          ? `Saved to copy “${result.name ?? result.node_id}” from ${nodeId} because accepted downstream use protects the original. The original remains available in lineage.`
          : "Saved a new virtual-scene revision.",
      );
      onRevisionChange(
        nodeId,
        revision.revision_id,
        result.node_id,
        result.revision_id,
        selected.frame_id,
        frameTime(selected),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage(
        "Scene changes were not saved. Check scene and calibration validation.",
      );
    } finally {
      setBusy(false);
    }
  };

  const review = async (
    decision: "accept" | "reject" | "overall-accept" | "overall-reject",
  ) => {
    if (
      revision === null ||
      selected === undefined ||
      selected.calibration === null ||
      !frameMatches ||
      !calibrationMatches ||
      readOnly
    )
      return;
    setBusy(true);
    setError(null);
    try {
      const actor = { kind: "human" as const, id: reviewer };
      if (decision.startsWith("overall")) {
        await reviewPipelineNodeOverall(nodeId, {
          review_id: `virtual-scenes-${crypto.randomUUID()}`,
          revision_id: revision.revision_id,
          question: "virtual-scene-review/v1",
          decision: decision.endsWith("accept") ? "accept" : "reject",
          reviewer: actor,
          evidence: {
            policy: "virtual-scene-review/v1",
            frame_ids: frames.map((frame) => frame.frame_id),
          },
        });
      } else {
        await reviewPipelineNodeItem(nodeId, {
          review_id: `virtual-scenes-${crypto.randomUUID()}`,
          revision_id: revision.revision_id,
          item_id: selected.frame_id,
          question: "virtual-scene-frame/v1",
          decision,
          reviewer: actor,
          evidence: {
            policy: "virtual-scene-review/v1",
            calibration_revision_id: selected.calibration.revision_id,
            calibration_digest: selected.calibration.digest,
          },
        });
      }
      setReviews(await listPipelineNodeReviews(nodeId, revision.revision_id));
      setMessage("Review decision saved for this exact revision.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const recordCoverage = async () => {
    if (
      revision === null ||
      frames.length === 0 ||
      inspected.size !== frames.length ||
      !frameMatches ||
      !calibrationMatches ||
      readOnly
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await reviewPipelineNodeCoverage(nodeId, {
        review_id: `virtual-scenes-coverage-${crypto.randomUUID()}`,
        revision_id: revision.revision_id,
        question: "virtual-scene-coverage/v1",
        coverage: {
          kind: "all_frames",
          frame_ids: frames.map((frame) => frame.frame_id),
        },
        reviewer: { kind: "human", id: reviewer },
        evidence: {
          policy: "virtual-scene-review/v1",
          frame_ids: frames.map((frame) => frame.frame_id),
        },
      });
      setReviews(await listPipelineNodeReviews(nodeId, revision.revision_id));
      setMessage("Full scene-frame coverage saved for this exact revision.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (error !== null && revision === null)
    return (
      <section className={styles.editor} aria-label="Virtual-scene editor">
        <p role="alert">{error}</p>
      </section>
    );
  const editor = (
    <section className={styles.editor} aria-label="Virtual-scene editor">
      <header className={styles.header}>
        <h2>Virtual scenes</h2>
        <p>
          {revision?.name} · revision {revisionId}
        </p>
        <p role="status">{message}</p>
        {error !== null ? <p role="alert">{error}</p> : null}
      </header>
      <div className={styles.layout}>
        {portalTargets.rail === null ? (
          <SceneFrameNavigation
            frames={frames}
            selectedId={selectedId}
            onSelect={choose}
          />
        ) : (
          createPortal(
            <SceneFrameNavigation
              frames={frames}
              selectedId={selectedId}
              onSelect={choose}
            />,
            portalTargets.rail,
          )
        )}
        <div className={styles.content}>
          {selected === undefined ? (
            <p>
              {selectionItemId === null
                ? "No scene frame is available."
                : "The selected frame is missing from this revision."}
            </p>
          ) : (
            <>
              {frameMatches &&
              frameState.state === "ready" &&
              portalTargets.center !== null
                ? createPortal(
                    <GeometrySurface
                      frame={frameState.frame.identity}
                      imageUrl={
                        viewpoint === "rectified" && rectifiedImageUrl !== null
                          ? rectifiedImageUrl
                          : frameState.frame.imageUrl
                      }
                      overlays={overlays}
                      selectedId={selectedPoseId}
                      onSelect={setSelectedPoseId}
                      onDrag={updatePoseFromSurface}
                      viewport={{ zoom, ...pan }}
                      viewpoint={viewpoint}
                      calibration={
                        calibrationMatches
                          ? {
                              revisionId: selected.calibration!.revision_id,
                              digest: selected.calibration!.digest,
                            }
                          : null
                      }
                    />,
                    portalTargets.center,
                  )
                : null}
              {!frameMatches ? (
                <p role="status">
                  {frameState.state === "loading"
                    ? "Loading the exact source frame…"
                    : frameState.state === "failed"
                      ? frameState.reason
                      : "The source or frame identity does not match this scene. Geometry editing is blocked."}
                </p>
              ) : null}
              <p>
                Frame {selected.frame_id} ·{" "}
                {frameTime(selected) === null
                  ? "time unavailable"
                  : `${frameTime(selected)} µs`}
              </p>
              <p>
                Calibration revision{" "}
                {selected.calibration?.revision_id ?? "missing"} · digest{" "}
                {selected.calibration?.digest ?? "missing"}
              </p>
              <p role="status">
                {calibrationMatches
                  ? "The exact calibration revision and frame dimensions match this scene. Pose edits are available."
                  : (calibrationError ??
                    "Loading or validating the exact calibration. Pose edits are blocked until it matches.")}
              </p>
              {calibrationResponse !== null ? (
                <details>
                  <summary>Calibration diagnostics</summary>
                  <p>
                    Source revision {calibrationResponse.source_revision} ·
                    frame {calibrationResponse.frame_width} ×{" "}
                    {calibrationResponse.frame_height} · card{" "}
                    {calibrationResponse.card_short_size} ×{" "}
                    {calibrationResponse.card_long_size} table units
                  </p>
                  <pre>
                    {JSON.stringify(calibrationResponse.diagnostics, null, 2)}
                  </pre>
                </details>
              ) : null}
              {activePose !== null && calibrationMatches ? (
                <fieldset>
                  <legend>Selected card pose</legend>
                  <p>{activePose.card_id}</p>
                  <label>
                    Table center X
                    <input
                      type="number"
                      step="0.01"
                      value={activePose.center[0]}
                      onChange={(event) =>
                        updatePose("center", [
                          Number(event.target.value),
                          activePose.center[1],
                        ])
                      }
                    />
                  </label>
                  <label>
                    Table center Y
                    <input
                      type="number"
                      step="0.01"
                      value={activePose.center[1]}
                      onChange={(event) =>
                        updatePose("center", [
                          activePose.center[0],
                          Number(event.target.value),
                        ])
                      }
                    />
                  </label>
                  <label>
                    Rotation
                    <input
                      type="number"
                      step="1"
                      value={activePose.rotation_degrees}
                      onChange={(event) =>
                        updatePose(
                          "rotation_degrees",
                          Number(event.target.value),
                        )
                      }
                    />
                  </label>
                  <div className={styles.actions}>
                    <button
                      type="button"
                      disabled={!canReorderPose(-1)}
                      onClick={() => reorderPose(-1)}
                    >
                      Move forward
                    </button>
                    <button
                      type="button"
                      disabled={!canReorderPose(1)}
                      onClick={() => reorderPose(1)}
                    >
                      Move backward
                    </button>
                  </div>
                </fieldset>
              ) : null}
              <fieldset>
                <legend>View controls</legend>
                <label>
                  Viewpoint
                  <select
                    value={viewpoint}
                    onChange={(event) =>
                      setViewpoint(event.target.value as "source" | "rectified")
                    }
                  >
                    <option value="source">Source</option>
                    <option
                      value="rectified"
                      disabled={
                        !calibrationMatches || rectifiedImageUrl === null
                      }
                    >
                      Rectified table view
                    </option>
                  </select>
                </label>
                <label>
                  Zoom
                  <input
                    aria-label="Scene view zoom"
                    type="range"
                    min="1"
                    max="4"
                    step="0.25"
                    value={zoom}
                    onChange={(event) => setZoom(Number(event.target.value))}
                  />
                </label>
                <button
                  type="button"
                  onClick={() =>
                    setPan((value) => ({ ...value, x: value.x - 24 }))
                  }
                >
                  Pan left
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPan((value) => ({ ...value, x: value.x + 24 }))
                  }
                >
                  Pan right
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPan((value) => ({ ...value, y: value.y - 24 }))
                  }
                >
                  Pan up
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPan((value) => ({ ...value, y: value.y + 24 }))
                  }
                >
                  Pan down
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPan({ x: 0, y: 0 });
                    setZoom(1);
                  }}
                >
                  Reset view
                </button>
              </fieldset>
              {geometryUnavailable && selected?.scene === null ? (
                <p role="status">
                  Geometry was not available in the retained draft. The recorded
                  review facts remain in this revision.
                </p>
              ) : null}
              {selectedReviews.length > 0 ? (
                <details>
                  <summary>Frame review records</summary>
                  {selectedReviews.map((review) => (
                    <div key={String(review.review_id)}>
                      <p>Frame decision: {String(review.decision)}</p>
                      <p>{String(review.question)}</p>
                      <p>Reviewer was not recorded.</p>
                    </div>
                  ))}
                </details>
              ) : null}
              <label>
                Scene poses and stacking order
                <textarea
                  aria-label="Scene JSON"
                  rows={20}
                  value={
                    draft ||
                    (selected.scene === null ? "null" : json(selected.scene))
                  }
                  readOnly={readOnly || !frameMatches || !calibrationMatches}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
              <div className={styles.actions}>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    inspected.has(selected.frame_id)
                  }
                  onClick={() =>
                    setInspected((current) =>
                      new Set(current).add(selected.frame_id),
                    )
                  }
                >
                  {inspected.has(selected.frame_id)
                    ? "Frame inspected"
                    : "Mark frame inspected"}
                </button>
                <button
                  type="button"
                  disabled={
                    busy || readOnly || !frameMatches || !calibrationMatches
                  }
                  onClick={() => void save()}
                >
                  Save scene
                </button>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    selected.scene === null ||
                    selected.calibration === null
                  }
                  onClick={() => void review("accept")}
                >
                  Accept frame
                </button>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    selected.scene === null ||
                    selected.calibration === null
                  }
                  onClick={() => void review("reject")}
                >
                  Reject frame
                </button>
              </div>
              <div className={styles.actions}>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    frames.length === 0 ||
                    inspected.size !== frames.length
                  }
                  onClick={() => void recordCoverage()}
                >
                  Record full scene coverage ({inspected.size}/{frames.length})
                </button>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    frames.length === 0
                  }
                  onClick={() => void review("overall-accept")}
                >
                  Accept scene data set
                </button>
                <button
                  type="button"
                  disabled={
                    busy ||
                    readOnly ||
                    !frameMatches ||
                    !calibrationMatches ||
                    frames.length === 0
                  }
                  onClick={() => void review("overall-reject")}
                >
                  Reject scene data set
                </button>
              </div>
              <p>{reviews.length} review record(s) for this revision.</p>
            </>
          )}
        </div>
      </div>
    </section>
  );
  return portalTargets.inspector === null
    ? editor
    : createPortal(editor, portalTargets.inspector);
}

function SceneFrameNavigation({
  frames,
  selectedId,
  onSelect,
}: {
  frames: SceneFrame[];
  selectedId: string | null;
  onSelect: (frame: SceneFrame) => void;
}) {
  return (
    <nav className={styles.navigation} aria-label="Scene frames">
      <ol>
        {frames.map((frame) => (
          <li key={frame.frame_id}>
            <button
              type="button"
              aria-current={selectedId === frame.frame_id ? "true" : undefined}
              onClick={() => onSelect(frame)}
            >
              {frame.frame_id} ·{" "}
              {frame.scene === null
                ? "no scene"
                : `${Array.isArray(frame.scene.poses) ? frame.scene.poses.length : 0} poses`}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
