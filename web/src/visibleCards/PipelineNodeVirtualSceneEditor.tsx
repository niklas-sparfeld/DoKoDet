import { useEffect, useMemo, useRef, useState } from "react";
import { repositoryBundleVideoPath } from "../api/client";
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

type SceneFrame = Record<string, unknown> & {
  frame_id: string;
  frame_identity: Record<string, unknown>;
  calibration: { revision_id: string; digest: string };
  scene: Record<string, unknown> | null;
};
type SceneContent = Record<string, unknown> & {
  schema_version: "virtual-scene-data/v1";
  frames: SceneFrame[];
};

type Props = {
  recordingId: string;
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
  nodeId,
  revisionId,
  selectionItemId,
  onPositionChange,
  onRevisionChange,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
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
  const [message, setMessage] = useState(
    "Loading selected virtual-scene revision…",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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
    const timeUs = selected === undefined ? null : frameTime(selected);
    const video = videoRef.current;
    if (video !== null && timeUs !== null && video.readyState >= 1)
      video.currentTime = timeUs / 1_000_000;
  }, [selected]);

  const choose = (frame: SceneFrame) => {
    setSelectedId(frame.frame_id);
    setDraft(frame.scene === null ? "null" : json(frame.scene));
    onPositionChange(frame.frame_id, frameTime(frame));
  };

  const save = async () => {
    if (
      content === null ||
      revision === null ||
      selected === undefined ||
      readOnly
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
    if (revision === null || selected === undefined) return;
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
      inspected.size !== frames.length
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
  return (
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
        <nav className={styles.navigation} aria-label="Scene frames">
          <ol>
            {frames.map((frame) => (
              <li key={frame.frame_id}>
                <button
                  type="button"
                  aria-current={
                    selectedId === frame.frame_id ? "true" : undefined
                  }
                  onClick={() => choose(frame)}
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
        <div className={styles.content}>
          {selected === undefined ? (
            <p>
              {selectionItemId === null
                ? "No scene frame is available."
                : "The selected frame is missing from this revision."}
            </p>
          ) : (
            <>
              <video
                ref={videoRef}
                src={repositoryBundleVideoPath(recordingId)}
                controls
                preload="metadata"
                aria-label="Recording video at selected scene frame"
              />
              <p>
                Frame {selected.frame_id} ·{" "}
                {frameTime(selected) === null
                  ? "time unavailable"
                  : `${frameTime(selected)} µs`}
              </p>
              <p>
                Calibration revision {selected.calibration.revision_id} · digest{" "}
                {selected.calibration.digest}
              </p>
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
                  readOnly={readOnly}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
              <div className={styles.actions}>
                <button
                  type="button"
                  disabled={busy || inspected.has(selected.frame_id)}
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
                  disabled={busy || readOnly}
                  onClick={() => void save()}
                >
                  Save scene
                </button>
                <button
                  type="button"
                  disabled={busy || selected.scene === null}
                  onClick={() => void review("accept")}
                >
                  Accept frame
                </button>
                <button
                  type="button"
                  disabled={busy || selected.scene === null}
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
                    frames.length === 0 ||
                    inspected.size !== frames.length
                  }
                  onClick={() => void recordCoverage()}
                >
                  Record full scene coverage ({inspected.size}/{frames.length})
                </button>
                <button
                  type="button"
                  disabled={busy || frames.length === 0}
                  onClick={() => void review("overall-accept")}
                >
                  Accept scene data set
                </button>
                <button
                  type="button"
                  disabled={busy || frames.length === 0}
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
}
