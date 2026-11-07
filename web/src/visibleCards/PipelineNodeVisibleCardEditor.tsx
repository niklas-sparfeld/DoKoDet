import { createPortal } from "react-dom";
import { useEffect, useMemo, useState } from "react";
import { useProfileName } from "../profile/profile";
import {
  GeometrySurface,
  type GeometryOverlay,
} from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";
import styles from "./PipelineNodeVisibleCardEditor.module.css";
import {
  editPipelineNode,
  getPipelineNodeRevision,
  listPipelineNodeReviews,
  reviewPipelineNodeCoverage,
  reviewPipelineNodeItem,
  reviewPipelineNodeOverall,
  type PipelineNodeRevision,
} from "../pipeline/pipelineNodeClient";

type Outcome = Record<string, unknown> & {
  event_id: string;
  frame_identity: Record<string, unknown> | null;
  candidates: unknown[];
  ignored_regions: unknown[];
  pile_regions?: unknown[];
};

type VisibleCardContent = Record<string, unknown> & {
  outcomes: Outcome[];
};

type Props = {
  recordingId: string;
  sourceSha256: string;
  nodeId: string;
  revisionId: string;
  selectionItemId: string | null;
  selectionTimeUs: number | null;
  onPositionChange: (itemId: string, timeUs: number | null) => void;
  onRevisionChange: (
    sourceNodeId: string,
    sourceRevisionId: string,
    nodeId: string,
    revisionId: string,
    itemId: string,
    timeUs: number | null,
  ) => void;
};

function asContent(value: Record<string, unknown>): VisibleCardContent {
  if (!Array.isArray(value.outcomes))
    throw new Error("Visible-card outcomes are missing.");
  return value as VisibleCardContent;
}

function jsonArray(value: unknown[]): string {
  return JSON.stringify(value, null, 2);
}

function frameTimeUs(outcome: Outcome): number | null {
  const identity = outcome.frame_identity;
  const timestamp = identity?.requested_time_us;
  return typeof timestamp === "number" && Number.isFinite(timestamp)
    ? timestamp
    : null;
}

export function PipelineNodeVisibleCardEditor({
  recordingId,
  sourceSha256,
  nodeId,
  revisionId,
  selectionItemId,
  selectionTimeUs,
  onPositionChange,
  onRevisionChange,
}: Props) {
  const profileName = useProfileName();
  const [revision, setRevision] = useState<PipelineNodeRevision | null>(null);
  const [content, setContent] = useState<VisibleCardContent | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(selectionItemId);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [reviews, setReviews] = useState<Array<Record<string, unknown>>>([]);
  const [inspected, setInspected] = useState<Set<string>>(() => new Set());
  const [portalTargets, setPortalTargets] = useState<{
    inspector: Element | null;
    center: Element | null;
    rail: Element | null;
  }>({ inspector: null, center: null, rail: null });
  const [message, setMessage] = useState(
    "Loading selected visible-card revision…",
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reviewerId =
    profileName
      .trim()
      .replace(/[^A-Za-z0-9._:-]+/g, "-")
      .replace(/^[^A-Za-z0-9]+/, "")
      .slice(0, 128) || "workspace-operator";
  const outcomes = useMemo(() => content?.outcomes ?? [], [content]);
  const outcomeById = useMemo(
    () => new Map(outcomes.map((outcome) => [outcome.event_id, outcome])),
    [outcomes],
  );
  const selected =
    selectedId === null ? undefined : outcomeById.get(selectedId);
  const readOnly =
    revision !== null && revision.head_revision_id !== revision.revision_id;
  const sceneOnlyItems = revision?.metadata.scene_only_frame_ids;
  const sceneOnlyCount = Array.isArray(sceneOnlyItems)
    ? sceneOnlyItems.length
    : 0;

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      getPipelineNodeRevision(nodeId, revisionId),
      listPipelineNodeReviews(nodeId, revisionId),
    ])
      .then(([loaded, loadedReviews]) => {
        if (loaded.content_type !== "visible_cards")
          throw new Error("The selected node does not contain visible cards.");
        if (cancelled) return;
        const next = asContent(loaded.content);
        setRevision(loaded);
        setContent(next);
        setReviews(loadedReviews);
        const desiredItemId =
          selectionItemId ?? next.outcomes[0]?.event_id ?? null;
        const itemExists =
          desiredItemId !== null &&
          next.outcomes.some((item) => item.event_id === desiredItemId);
        setSelectedId(itemExists ? desiredItemId : null);
        setMessage(
          !itemExists && selectionItemId !== null
            ? "The selected outcome is not present in this revision. No other outcome was selected."
            : loaded.head_revision_id === loaded.revision_id
              ? "Current revision"
              : "Historical revision · read only",
        );
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setMessage("Could not load this exact visible-card revision.");
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

  const timeUs = selected === undefined ? null : frameTimeUs(selected);
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: recordingId,
    sourceSha256: portalTargets.center === null ? "" : sourceSha256,
    requestedTimeUs: timeUs ?? 0,
    mode: "exact",
  });
  const frameMatches =
    portalTargets.center === null ||
    (selected?.frame_identity !== null &&
      selected?.frame_identity.source_video_sha256 === sourceSha256 &&
      typeof selected?.frame_identity.requested_time_us === "number" &&
      frameState.state === "ready" &&
      frameState.frame.requestedTimeUs ===
        selected.frame_identity.requested_time_us);
  const overlays = useMemo(
    () =>
      selected === undefined
        ? []
        : visibleCardOverlays(
            selected,
            frameState.state === "ready" ? frameState.frame.identity : null,
          ),
    [selected, frameState],
  );
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewpoint, setViewpoint] = useState<"source" | "rectified">("source");

  const choose = (outcome: Outcome) => {
    setSelectedId(outcome.event_id);
    onPositionChange(outcome.event_id, frameTimeUs(outcome));
  };

  const saveOutcome = async () => {
    if (
      content === null ||
      revision === null ||
      selected === undefined ||
      readOnly
    )
      return;
    if (reviewerId === "") {
      setError("Set a profile name before editing visible cards.");
      return;
    }
    const index = content.outcomes.findIndex(
      (item) => item.event_id === selected.event_id,
    );
    const fields = ["candidates", "ignored_regions", "pile_regions"] as const;
    let updated = { ...selected };
    try {
      for (const field of fields) {
        const raw = drafts[`${selected.event_id}:${field}`];
        if (raw === undefined) continue;
        const parsed: unknown = JSON.parse(raw);
        if (!Array.isArray(parsed))
          throw new Error(`${field} must be a JSON array.`);
        updated = { ...updated, [field]: parsed };
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return;
    }
    const nextContent: VisibleCardContent = {
      ...content,
      outcomes: content.outcomes.map((item, itemIndex) =>
        itemIndex === index ? updated : item,
      ),
    };
    if (JSON.stringify(updated) === JSON.stringify(selected)) {
      setDrafts({});
      setMessage("No visible-card changes to save.");
      return;
    }
    const pointers = Object.fromEntries(
      nextContent.outcomes.map((item, itemIndex) => [
        item.event_id,
        `/outcomes/${itemIndex}`,
      ]),
    );
    const basePointers = Object.fromEntries(
      content.outcomes.map((item, itemIndex) => [
        item.event_id,
        `/outcomes/${itemIndex}`,
      ]),
    );
    setBusy(true);
    setError(null);
    setMessage("Saving visible-card changes…");
    try {
      const result = await editPipelineNode(nodeId, {
        expected_revision_id: revision.revision_id,
        idempotency_key: `visible-card-edit-${crypto.randomUUID()}`,
        actor: { kind: "human", id: reviewerId },
        content: nextContent,
        base_pointers: basePointers,
        pointers,
        operations: [
          {
            kind: "replace",
            before: [selected.event_id],
            after: [selected.event_id],
          },
        ],
      });
      setDrafts({});
      setMessage(
        result.copied
          ? `Saved to copy “${result.name ?? result.node_id}” from ${nodeId} because accepted downstream use protects the original. The original remains available in lineage.`
          : "Saved a new visible-card revision.",
      );
      onRevisionChange(
        nodeId,
        revision.revision_id,
        result.node_id,
        result.revision_id,
        selected.event_id,
        frameTimeUs(selected),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setMessage("Visible-card changes were not saved.");
    } finally {
      setBusy(false);
    }
  };

  const submitReview = async (
    kind: "accept" | "reject" | "coverage" | "overall",
  ) => {
    if (revision === null || selected === undefined) return;
    if (reviewerId === "") {
      setError("Set a profile name before reviewing visible cards.");
      return;
    }
    const actor = { kind: "human" as const, id: reviewerId };
    const reviewId = `visible-cards-${kind}-${crypto.randomUUID()}`;
    setBusy(true);
    setError(null);
    try {
      if (kind === "coverage") {
        const review = await reviewPipelineNodeCoverage(nodeId, {
          review_id: reviewId,
          revision_id: revision.revision_id,
          question: "full_recording_visible_card_coverage",
          coverage: {
            complete: true,
            reviewed_item_ids: outcomes.map((item) => item.event_id),
          },
          reviewer: actor,
          evidence: {
            policy: "visible-card-review/v1",
            inspected_item_ids: [...inspected],
          },
        });
        setReviews((current) => [...current, review]);
        setMessage("Full-recording coverage was saved for this revision.");
      } else if (kind === "overall") {
        const review = await reviewPipelineNodeOverall(nodeId, {
          review_id: reviewId,
          revision_id: revision.revision_id,
          question: "visible_cards_acceptable",
          decision: "accepted",
          reviewer: actor,
          evidence: {
            policy: "visible-card-review/v1",
            outcome_count: outcomes.length,
          },
        });
        setReviews((current) => [...current, review]);
        setMessage("Overall acceptance was saved for this revision.");
      } else {
        const review = await reviewPipelineNodeItem(nodeId, {
          review_id: reviewId,
          revision_id: revision.revision_id,
          item_id: selected.event_id,
          question: "visible_card_outcome",
          decision: kind === "accept" ? "accepted" : "rejected",
          reviewer: actor,
          evidence: {
            policy: "visible-card-review/v1",
            frame_identity: selected.frame_identity,
          },
        });
        setReviews((current) => [...current, review]);
        setMessage(`Outcome ${kind} decision was saved for this revision.`);
        window.dispatchEvent(
          new CustomEvent("frame-review-node-reviewed", {
            detail: {
              itemId: selected.event_id,
              nodeId,
              revisionId: revision.revision_id,
              reviewId,
            },
          }),
        );
      }
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const editor = (
    <section aria-label="Visible-card lineage editor" className={styles.editor}>
      <header className={styles.header}>
        <h2>{revision?.name ?? "Visible cards"}</h2>
        <p>{message}</p>
        <small>
          Node {nodeId} · revision {revisionId}
        </small>
      </header>
      {error ? <p role="alert">{error}</p> : null}
      {sceneOnlyCount > 0 ? (
        <p>
          Open Virtual scenes to inspect {sceneOnlyCount} frame
          {sceneOnlyCount === 1 ? "" : "s"} with scene data but no
          visible-region data.
        </p>
      ) : null}
      {outcomes.length === 0 ? (
        <p>This revision has no visible-card outcomes.</p>
      ) : selected === undefined ? (
        <p role="status">
          The selected outcome is unavailable in this revision.
        </p>
      ) : (
        <>
          {frameMatches && frameState.state === "ready"
            ? portalTargets.center === null
              ? null
              : createPortal(
                  <GeometrySurface
                    frame={frameState.frame.identity}
                    imageUrl={frameState.frame.imageUrl}
                    overlays={overlays}
                    viewport={{ zoom, ...pan }}
                    viewpoint={viewpoint}
                  />,
                  portalTargets.center,
                )
            : null}
          <article className={styles.content}>
            <h3>Frame {selected.event_id}</h3>
            {!frameMatches ? (
              <p role="status">
                {timeUs === null
                  ? "This outcome has no exact frame time. Geometry editing is unavailable."
                  : frameState.state === "loading"
                    ? "Loading the exact source frame…"
                    : frameState.state === "failed"
                      ? frameState.reason
                      : "The source or frame identity does not match this outcome. Geometry editing is blocked."}
              </p>
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
                  <option value="rectified" disabled>
                    Rectified (calibration unavailable)
                  </option>
                </select>
              </label>
              <label>
                Zoom
                <input
                  aria-label="View zoom"
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
            <p>
              Calibration diagnostics: visible-card regions use exact
              source-frame coordinates. No table-plane calibration is required.
            </p>
            <p>
              Item decision:{" "}
              {reviews
                .filter(
                  (review) =>
                    review.kind === "item" &&
                    review.item_id === selected.event_id,
                )
                .map((review) => String(review.decision))
                .join(", ") || "No decision"}
            </p>
            <pre>{JSON.stringify(selected.frame_identity, null, 2)}</pre>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                setInspected((current) =>
                  new Set(current).add(selected.event_id),
                )
              }
            >
              {inspected.has(selected.event_id)
                ? "Frame inspected"
                : "Mark frame inspected"}
            </button>
            {(["candidates", "pile_regions", "ignored_regions"] as const).map(
              (field) => (
                <label key={field}>
                  {field === "candidates"
                    ? "Visible regions"
                    : field === "pile_regions"
                      ? "Pile regions"
                      : "Ignore regions"}
                  <textarea
                    aria-label={`${field} JSON`}
                    spellCheck={false}
                    readOnly={readOnly}
                    rows={Math.min(
                      14,
                      Math.max(
                        4,
                        JSON.stringify(selected[field] ?? [], null, 2).split(
                          "\n",
                        ).length,
                      ),
                    )}
                    value={
                      drafts[`${selected.event_id}:${field}`] ??
                      jsonArray((selected[field] ?? []) as unknown[])
                    }
                    onChange={(event) =>
                      setDrafts((current) => ({
                        ...current,
                        [`${selected.event_id}:${field}`]: event.target.value,
                      }))
                    }
                  />
                </label>
              ),
            )}
            {!readOnly && frameMatches ? (
              <button
                type="button"
                disabled={busy || Object.keys(drafts).length === 0}
                onClick={() => void saveOutcome()}
              >
                Save visible-card changes
              </button>
            ) : null}
            <div
              aria-label="Visible-card review decisions"
              className={styles.actions}
            >
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitReview("accept")}
              >
                Accept outcome
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitReview("reject")}
              >
                Reject outcome
              </button>
              <button
                type="button"
                disabled={busy || inspected.size < outcomes.length}
                onClick={() => void submitReview("coverage")}
              >
                Accept full-recording coverage
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitReview("overall")}
              >
                Accept visible-card content
              </button>
            </div>
          </article>
          {portalTargets.rail === null ? (
            <div
              className={styles.navigation}
              data-visible-card-frame-navigation
            >
              <OutcomeNavigation
                outcomes={outcomes}
                selectedId={selected.event_id}
                onSelect={choose}
              />
            </div>
          ) : (
            createPortal(
              <OutcomeNavigation
                outcomes={outcomes}
                selectedId={selected.event_id}
                onSelect={choose}
              />,
              portalTargets.rail,
            )
          )}
        </>
      )}
      <section aria-label="Revision-bound visible-card reviews">
        <h3>Reviews for this revision</h3>
        {reviews.length === 0 ? (
          <p>No reviews are recorded for this revision.</p>
        ) : (
          <ul>
            {reviews.map((review) => (
              <li key={String(review.review_id)}>
                {String(review.kind)} · {String(review.question)} ·{" "}
                {String(review.decision ?? "coverage recorded")}
              </li>
            ))}
          </ul>
        )}
      </section>
      {selectionTimeUs !== null ? <span hidden>{selectionTimeUs}</span> : null}
    </section>
  );
  return portalTargets.inspector === null
    ? editor
    : createPortal(editor, portalTargets.inspector);
}

function OutcomeNavigation({
  outcomes,
  selectedId,
  onSelect,
}: {
  outcomes: Outcome[];
  selectedId: string;
  onSelect: (outcome: Outcome) => void;
}) {
  return (
    <nav aria-label="Visible-card frames" className={styles.navigation}>
      <ol>
        {outcomes.map((outcome) => (
          <li key={outcome.event_id}>
            <button
              type="button"
              aria-current={
                selectedId === outcome.event_id ? "true" : undefined
              }
              onClick={() => onSelect(outcome)}
            >
              {outcome.event_id} · {String(outcome.status)}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function visibleCardOverlays(
  outcome: Outcome,
  frame: import("../workingArea/GeometrySurface").GeometryFrameIdentity | null,
): GeometryOverlay[] {
  if (frame === null) return [];
  const values: GeometryOverlay[] = [];
  const add = (items: unknown, kind: string, colorLabel: string) => {
    if (!Array.isArray(items)) return;
    for (const [index, raw] of items.entries()) {
      if (typeof raw !== "object" || raw === null) continue;
      const item = raw as Record<string, unknown>;
      const geometry = item.geometry as Record<string, unknown> | undefined;
      const polygons = geometry?.polygons;
      if (!Array.isArray(polygons)) continue;
      const points = polygons[0];
      if (!Array.isArray(points) || points.length < 3) continue;
      const converted = points.flatMap((point) => {
        if (typeof point !== "object" || point === null) return [];
        const coordinates = point as Record<string, unknown>;
        const x = coordinates.x;
        const y = coordinates.y;
        if (typeof x !== "number" || typeof y !== "number") return [];
        return [[(x / 1000) * frame.width, (y / 1000) * frame.height] as const];
      });
      if (converted.length < 3) continue;
      values.push({
        id: `${kind}-${index}`,
        label: `${colorLabel} ${index + 1}`,
        frame,
        calibration: null,
        geometry: { kind: "polygon", points: converted },
      });
    }
  };
  add(outcome.candidates, "region", "Visible region");
  add(outcome.pile_regions, "pile", "Pile region");
  add(outcome.ignored_regions, "ignore", "Ignore region");
  return values;
}
