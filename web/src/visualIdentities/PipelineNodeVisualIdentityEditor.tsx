import { createPortal } from "react-dom";
import { useEffect, useMemo, useState } from "react";

import { pipelineIdentityCropPath } from "../api/pipelineProcessingClient";
import {
  GeometrySurface,
  type GeometryOverlay,
} from "../workingArea/GeometrySurface";
import { useWorkingAreaFrame } from "../workingArea/workingAreaFrame";
import { useProfileName } from "../profile/profile";
import {
  editPipelineNode,
  getPipelineNodeRevision,
  listPipelineNodeReviews,
  reviewPipelineNodeItem,
  reviewPipelineNodeOverall,
  type PipelineNodeRevision,
} from "../pipeline/pipelineNodeClient";

type IdentityOutcome = Record<string, unknown> & {
  card_id: string;
  frame_identity: Record<string, unknown>;
  geometry: Record<string, unknown>;
  candidates: unknown[];
  crop_identity?: Record<string, unknown> | null;
};
type IdentityContent = Record<string, unknown> & {
  outcomes: IdentityOutcome[];
};

export function PipelineNodeVisualIdentityEditor({
  recordingId,
  nodeId,
  revisionId,
  selectionItemId,
  selectionTimeUs,
  sourceSha256,
  onPositionChange,
  onRevisionChange,
}: {
  recordingId: string;
  nodeId: string;
  revisionId: string;
  selectionItemId: string | null;
  selectionTimeUs: number | null;
  sourceSha256: string;
  onPositionChange: (itemId: string, timeUs: number) => void;
  onRevisionChange: (
    sourceNodeId: string,
    sourceRevisionId: string,
    nodeId: string,
    revisionId: string,
    itemId: string,
    timeUs: number,
  ) => void;
}) {
  const profileName = useProfileName();
  const [node, setNode] = useState<PipelineNodeRevision | null>(null);
  const [content, setContent] = useState<IdentityContent | null>(null);
  const [reviews, setReviews] = useState<Array<Record<string, unknown>>>([]);
  const [selectedId, setSelectedId] = useState<string | null>(selectionItemId);
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState("Loading selected identity revision…");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [portalTargets, setPortalTargets] = useState<{
    center: Element | null;
    inspector: Element | null;
  }>({ center: null, inspector: null });
  const [cropZoom, setCropZoom] = useState(1);
  const [cropFocus, setCropFocus] = useState(false);
  const [cropLoadedKey, setCropLoadedKey] = useState<string | null>(null);
  const [cropErrorKey, setCropErrorKey] = useState<string | null>(null);
  const reviewerId =
    profileName
      .trim()
      .replace(/[^A-Za-z0-9._:-]+/g, "-")
      .slice(0, 128) || "workspace-operator";

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      getPipelineNodeRevision(nodeId, revisionId),
      listPipelineNodeReviews(nodeId, revisionId),
    ])
      .then(([loaded, loadedReviews]) => {
        if (
          loaded.content_type !== "visual_identities" ||
          !Array.isArray(loaded.content.outcomes)
        )
          throw new Error(
            "The selected node does not contain visual identities.",
          );
        const outcomes = loaded.content.outcomes.filter(isOutcome);
        if (cancelled) return;
        setNode(loaded);
        setContent({ ...loaded.content, outcomes });
        setReviews(loadedReviews);
        const wanted = selectionItemId ?? outcomes[0]?.card_id ?? null;
        const chosen = outcomes.find((item) => item.card_id === wanted);
        setSelectedId(chosen?.card_id ?? null);
        setDraft(chosen === undefined ? "" : JSON.stringify(chosen, null, 2));
        setMessage(
          loaded.head_revision_id === loaded.revision_id
            ? "Current revision"
            : "Historical revision · read only",
        );
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId, revisionId, selectionItemId]);

  const outcomes = content?.outcomes ?? [];
  const selected = outcomes.find((item) => item.card_id === selectedId);
  const readOnly = node !== null && node.head_revision_id !== node.revision_id;
  const selectedTimeUs = numberField(
    selected?.frame_identity.requested_time_us,
  );
  const cropSource = selected?.crop_input_provenance ?? null;
  const provenance =
    typeof cropSource === "object" && cropSource !== null
      ? (cropSource as Record<string, unknown>)
      : null;
  const cropPolicy = selected?.crop_identity?.crop_policy;
  const cropUrl = (() => {
    if (
      selected === undefined ||
      selected.crop_identity?.status !== "usable" ||
      provenance === null ||
      typeof provenance.source_revision_id !== "string" ||
      typeof provenance.source_revision_digest !== "string" ||
      typeof provenance.manifest_digest !== "string"
    )
      return null;
    return pipelineIdentityCropPath(recordingId, revisionId, selected.card_id);
  })();
  const cropKey = `${revisionId}:${selected?.card_id ?? "none"}:${String(selected?.crop_identity?.image_sha256 ?? "")}`;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPortalTargets({
        center: document.querySelector('[data-slot="center"]'),
        inspector: document.querySelector(
          '[data-identity-inspector-slot="action"]',
        ),
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const inspector = portalTargets.inspector?.closest<HTMLElement>(
      '[data-slot="inspector"]',
    );
    if (inspector === null || inspector === undefined) return;
    if (cropFocus) inspector.dataset.cropFocused = "true";
    else delete inspector.dataset.cropFocused;
    return () => {
      delete inspector.dataset.cropFocused;
    };
  }, [cropFocus, portalTargets.inspector]);

  const requestedTimeUs = selectedTimeUs ?? selectionTimeUs ?? 0;
  const frameState = useWorkingAreaFrame({
    recordingId,
    sourceId: recordingId,
    sourceSha256: portalTargets.center === null ? "" : sourceSha256,
    requestedTimeUs,
    mode: "exact",
    ...(typeof selected?.frame_identity.frame_index === "number"
      ? { frameIndex: selected.frame_identity.frame_index }
      : {}),
  });
  const frameMatches =
    selected !== undefined &&
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
      selected.frame_identity.image_sha256;
  const overlays = useMemo(() => {
    if (!frameMatches || selected === undefined || frameState.state !== "ready")
      return [];
    const polygons = selected.geometry.polygons;
    if (!Array.isArray(polygons)) return [];
    const points = polygons[0];
    if (!Array.isArray(points)) return [];
    const converted = points.flatMap((raw) => {
      if (typeof raw !== "object" || raw === null) return [];
      const point = raw as Record<string, unknown>;
      if (typeof point.x !== "number" || typeof point.y !== "number") return [];
      return [
        [
          (point.x / 1000) * frameState.frame.identity.width,
          (point.y / 1000) * frameState.frame.identity.height,
        ] as const,
      ];
    });
    if (converted.length < 3) return [];
    return [
      {
        id: selected.card_id,
        label: `Visual identity ${selected.card_id}`,
        frame: frameState.frame.identity,
        calibration: null,
        geometry: { kind: "polygon" as const, points: converted },
      } satisfies GeometryOverlay,
    ];
  }, [frameMatches, selected, frameState]);

  const choose = (item: IdentityOutcome) => {
    setSelectedId(item.card_id);
    setDraft(JSON.stringify(item, null, 2));
    const timeUs = numberField(item.frame_identity.requested_time_us);
    if (timeUs !== null) onPositionChange(item.card_id, timeUs);
  };
  const chooseCandidate = (candidate: unknown) => {
    if (
      readOnly ||
      busy ||
      selected === undefined ||
      typeof candidate !== "object" ||
      candidate === null
    )
      return;
    const value = candidate as Record<string, unknown>;
    if (typeof value.identity !== "string") return;
    const scoreField = Object.hasOwn(value, "score") ? "score" : "probability";
    const edited = {
      ...selected,
      candidates: [{ ...value, [scoreField]: 1 }],
      status: "classified",
      error: null,
      unusable_reason: null,
    };
    setDraft(JSON.stringify(edited, null, 2));
  };
  const save = async () => {
    if (content === null || node === null || selected === undefined || readOnly)
      return;
    setBusy(true);
    setError(null);
    try {
      const edited: unknown = JSON.parse(draft);
      if (
        !isOutcome(edited) ||
        edited.card_id !== selected.card_id ||
        JSON.stringify(edited.frame_identity) !==
          JSON.stringify(selected.frame_identity) ||
        JSON.stringify(edited.geometry) !== JSON.stringify(selected.geometry) ||
        JSON.stringify(edited.crop_input_provenance) !==
          JSON.stringify(selected.crop_input_provenance) ||
        JSON.stringify(edited.crop_identity) !==
          JSON.stringify(selected.crop_identity)
      )
        throw new Error(
          "Keep card, frame, geometry, and crop source fields unchanged. Edit identity classification fields only.",
        );
      const next = {
        ...content,
        outcomes: content.outcomes.map((item) =>
          item.card_id === selected.card_id ? edited : item,
        ),
      };
      const pointers = Object.fromEntries(
        next.outcomes.map((item, index) => [
          item.card_id,
          `/outcomes/${index}`,
        ]),
      );
      const basePointers = Object.fromEntries(
        content.outcomes.map((item, index) => [
          item.card_id,
          `/outcomes/${index}`,
        ]),
      );
      const result = await editPipelineNode(nodeId, {
        expected_revision_id: revisionId,
        idempotency_key: `identity-edit-${crypto.randomUUID()}`,
        actor: { kind: "human", id: reviewerId },
        content: next,
        pointers,
        base_pointers: basePointers,
        operations: [
          {
            kind: "replace",
            before: [selected.card_id],
            after: [selected.card_id],
          },
        ],
      });
      setContent(next);
      setMessage(
        result.copied
          ? `Saved to copy “${result.name ?? result.node_id}”. The original remains in lineage.`
          : "Identity correction saved as a new revision.",
      );
      onRevisionChange(
        nodeId,
        revisionId,
        result.node_id,
        result.revision_id,
        selected.card_id,
        selectedTimeUs ?? 0,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const review = async (decision: "accepted" | "rejected") => {
    if (node === null || selected === undefined) return;
    setBusy(true);
    setError(null);
    try {
      await reviewPipelineNodeItem(nodeId, {
        review_id: crypto.randomUUID(),
        revision_id: revisionId,
        item_id: selected.card_id,
        question: "Is this visual identity correct?",
        decision,
        reviewer: { kind: "human", id: reviewerId },
        evidence: {
          policy: "visual-identity-review/v1",
          frame_identity: selected.frame_identity,
          crop_identity: selected.crop_identity ?? null,
        },
      });
      setReviews(await listPipelineNodeReviews(nodeId, revisionId));
      setMessage(`Identity marked ${decision}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  const overall = async (decision: "accepted" | "rejected") => {
    if (node === null) return;
    setBusy(true);
    setError(null);
    try {
      await reviewPipelineNodeOverall(nodeId, {
        review_id: crypto.randomUUID(),
        revision_id: revisionId,
        question: "Is this visual identity data set correct?",
        decision,
        reviewer: { kind: "human", id: reviewerId },
        evidence: {
          policy: "visual-identity-review/v1",
          item_count: outcomes.length,
          inspected_item_ids: reviews
            .filter((r) => r.kind === "item")
            .map((r) => r.item_id),
        },
      });
      setReviews(await listPipelineNodeReviews(nodeId, revisionId));
      setMessage(`Data set marked ${decision}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (node === null || content === null)
    return (
      <section aria-label="Visual identity data">
        <p role="status">{error ?? message}</p>
      </section>
    );
  const itemReview = reviews.find(
    (review) => review.kind === "item" && review.item_id === selected?.card_id,
  );
  const overallReview = reviews.find((review) => review.kind === "overall");
  const center = (
    <section aria-label="Visual identity source frame">
      {frameState.state === "ready" ? (
        <GeometrySurface
          frame={frameState.frame.identity}
          imageUrl={frameState.frame.imageUrl}
          overlays={overlays}
          selectedId={selectedId}
          onSelect={(itemId) => {
            const item = outcomes.find((outcome) => outcome.card_id === itemId);
            if (item !== undefined) choose(item);
          }}
        />
      ) : (
        <p role={frameState.state === "failed" ? "alert" : "status"}>
          {frameState.state === "failed"
            ? `Source frame unavailable: ${frameState.reason}`
            : "Loading exact source frame…"}
        </p>
      )}
    </section>
  );
  const editor = (
    <section aria-label="Visual identity data">
      <header>
        <h2>{node.name} · visual identities</h2>
        <p>{message}</p>
      </header>
      <p>
        {outcomes.length} identity outcomes ·{" "}
        {readOnly ? "Historical revision · read only" : "Current revision"}
      </p>
      {selected === undefined ? (
        <p>No identity outcome is selected.</p>
      ) : (
        <>
          <p>
            Frame {String(selected.frame_identity.frame_index ?? "unknown")} ·
            requested {selectedTimeUs ?? "unknown"} μs
          </p>
          {frameState.state === "failed" ? (
            <p role="alert">{frameState.reason}</p>
          ) : null}
          {frameState.state === "ready" && !frameMatches ? (
            <p role="alert">
              The loaded source frame does not match this exact identity
              outcome. Its geometry is hidden.
            </p>
          ) : null}
          <section aria-label="Selected identity crop">
            <h3>Frozen processor input crop</h3>
            {cropUrl === null ? (
              <p>
                {selected.crop_identity?.status === "face_down" ||
                selected.status === "face_down"
                  ? "This outcome is face down. No identity crop is available."
                  : selected.crop_identity?.status === "unusable" ||
                      selected.status === "unusable"
                    ? `The crop is unusable${selected.unusable_reason ? `: ${String(selected.unusable_reason)}` : "."}`
                    : selected.crop_identity?.status === "failed" ||
                        selected.status === "failed"
                      ? `Crop processing failed${selected.error ? `: ${String(selected.error)}` : "."}`
                      : "The processor input crop is missing or its source revision is unavailable."}
              </p>
            ) : (
              <>
                {cropLoadedKey !== cropKey && cropErrorKey !== cropKey ? (
                  <p role="status">Loading the selected frozen crop…</p>
                ) : null}
                {cropErrorKey === cropKey ? (
                  <p role="alert">The selected crop is stale or unavailable.</p>
                ) : null}
                <div
                  style={{
                    overflow: "auto",
                    resize: "vertical",
                    height: "18rem",
                    minHeight: "8rem",
                    maxHeight: "50vh",
                  }}
                >
                  <img
                    key={cropKey}
                    alt={`Frozen processor input crop for ${selected.card_id}`}
                    src={cropUrl}
                    onLoad={() => setCropLoadedKey(cropKey)}
                    onError={() => setCropErrorKey(cropKey)}
                    style={{
                      display: cropLoadedKey === cropKey ? "block" : "none",
                      width: `${Math.min(100, 100 * cropZoom)}%`,
                      height: "auto",
                    }}
                  />
                </div>
                <label>
                  Crop zoom{" "}
                  <input
                    aria-label="Crop zoom"
                    type="range"
                    min="0.5"
                    max="3"
                    step="0.25"
                    value={cropZoom}
                    onChange={(event) =>
                      setCropZoom(Number(event.target.value))
                    }
                  />
                </label>
                <button type="button" onClick={() => setCropZoom(1)}>
                  Fit crop
                </button>
                <button
                  type="button"
                  aria-pressed={cropFocus}
                  onClick={() => setCropFocus((focused) => !focused)}
                >
                  {cropFocus ? "Show all inspector sections" : "Focus crop"}
                </button>
              </>
            )}
            <dl>
              <div>
                <dt>Crop policy</dt>
                <dd>{String(cropPolicy ?? "Unavailable")}</dd>
              </div>
              <div>
                <dt>Crop digest</dt>
                <dd>
                  {String(
                    selected.crop_identity?.image_sha256 ?? "Unavailable",
                  )}
                </dd>
              </div>
              <div>
                <dt>Input kind</dt>
                <dd>
                  {String(
                    (cropSource as Record<string, unknown> | null)
                      ?.input_kind ?? "Unavailable",
                  )}
                </dd>
              </div>
              <div>
                <dt>Source revision</dt>
                <dd>
                  {String(
                    (cropSource as Record<string, unknown> | null)
                      ?.source_revision_id ?? "Unavailable",
                  )}
                </dd>
              </div>
              <div>
                <dt>Source revision digest</dt>
                <dd>
                  {String(
                    (cropSource as Record<string, unknown> | null)
                      ?.source_revision_digest ?? "Unavailable",
                  )}
                </dd>
              </div>
              <div>
                <dt>Source node</dt>
                <dd>
                  {String(
                    (cropSource as Record<string, unknown> | null)
                      ?.source_node_id ?? "Unavailable",
                  )}
                </dd>
              </div>
              <div>
                <dt>Source node revision</dt>
                <dd>
                  {String(
                    (cropSource as Record<string, unknown> | null)
                      ?.source_node_revision_id ?? "Unavailable",
                  )}
                </dd>
              </div>
            </dl>
          </section>
          <nav aria-label="Identity outcomes">
            {outcomes.map((item) => (
              <button
                key={item.card_id}
                type="button"
                aria-pressed={selectedId === item.card_id}
                onClick={() => choose(item)}
              >
                {item.card_id} · {String(item.status ?? "unknown")} ·{" "}
                {String(item.crop_identity?.status ?? "crop missing")}
              </button>
            ))}
          </nav>
          <section
            aria-label="Identity classification choices"
            tabIndex={0}
            onKeyDown={(event) => {
              if (
                event.target instanceof HTMLInputElement ||
                event.target instanceof HTMLTextAreaElement
              )
                return;
              const index = Number(event.key) - 1;
              if (
                index >= 0 &&
                index < 9 &&
                index < selected.candidates.length
              ) {
                event.preventDefault();
                chooseCandidate(selected.candidates[index]);
              }
            }}
          >
            <h3>Identity choices</h3>
            <p>
              Press 1–9 to choose a candidate while focus is in this section.
            </p>
            {selected.candidates.map((candidate, index) => {
              const value =
                typeof candidate === "object" && candidate !== null
                  ? (candidate as Record<string, unknown>)
                  : {};
              return (
                <button
                  key={`${String(value.identity)}-${index}`}
                  type="button"
                  disabled={readOnly || busy}
                  onClick={() => chooseCandidate(candidate)}
                >
                  {index + 1}. {String(value.identity ?? "Unknown identity")} ·{" "}
                  {String(value.probability ?? value.score ?? "no score")}
                </button>
              );
            })}
          </section>
          <label>
            Identity outcome JSON
            <textarea
              aria-label="Identity outcome JSON"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={readOnly || busy}
              rows={16}
            />
          </label>
          {!readOnly ? (
            <>
              <button type="button" disabled={busy} onClick={() => void save()}>
                Save identity correction
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void review("accepted")}
              >
                Accept identity
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void review("rejected")}
              >
                Reject identity
              </button>
              <p>
                Item review: {String(itemReview?.decision ?? "not reviewed")}
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => void overall("accepted")}
              >
                Accept data set
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void overall("rejected")}
              >
                Reject data set
              </button>
              <p>
                Overall review:{" "}
                {String(overallReview?.decision ?? "not reviewed")}
              </p>
            </>
          ) : null}
        </>
      )}
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
  return (
    <>
      {portalTargets.center === null
        ? center
        : createPortal(center, portalTargets.center)}
      {portalTargets.inspector === null
        ? editor
        : createPortal(editor, portalTargets.inspector)}
    </>
  );
}

function isOutcome(value: unknown): value is IdentityOutcome {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as IdentityOutcome).card_id === "string" &&
    typeof (value as IdentityOutcome).frame_identity === "object" &&
    (value as IdentityOutcome).frame_identity !== null &&
    typeof (value as IdentityOutcome).geometry === "object" &&
    (value as IdentityOutcome).geometry !== null &&
    Array.isArray((value as IdentityOutcome).candidates)
  );
}
function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
