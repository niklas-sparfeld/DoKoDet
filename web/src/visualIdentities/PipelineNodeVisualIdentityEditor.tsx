import { useEffect, useState } from "react";

import {
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
} from "../api/client";
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
  onPositionChange,
  onRevisionChange,
}: {
  recordingId: string;
  nodeId: string;
  revisionId: string;
  selectionItemId: string | null;
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
  const cropUrl = (() => {
    if (selected === undefined || selected.crop_identity?.status !== "usable")
      return null;
    const sourceRevisionId =
      selected.crop_input_provenance &&
      typeof selected.crop_input_provenance === "object"
        ? (selected.crop_input_provenance as Record<string, unknown>)
            .identity_revision_id
        : null;
    return typeof sourceRevisionId === "string"
      ? pipelineIdentityCropPath(
          recordingId,
          sourceRevisionId,
          selected.card_id,
        )
      : null;
  })();

  const choose = (item: IdentityOutcome) => {
    setSelectedId(item.card_id);
    setDraft(JSON.stringify(item, null, 2));
    const timeUs = numberField(item.frame_identity.requested_time_us);
    if (timeUs !== null) onPositionChange(item.card_id, timeUs);
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
  return (
    <section aria-label="Visual identity data">
      <header>
        <h2>{node.name} · visual identities</h2>
        <p>{message}</p>
      </header>
      <p>
        {outcomes.length} identity outcomes ·{" "}
        {readOnly ? "Historical revision · read only" : "Current revision"}
      </p>
      <nav aria-label="Identity outcomes">
        {outcomes.map((item) => (
          <button
            key={item.card_id}
            type="button"
            aria-pressed={selectedId === item.card_id}
            onClick={() => choose(item)}
          >
            {item.card_id} · {String(item.status ?? "unknown")}
          </button>
        ))}
      </nav>
      {selected === undefined ? (
        <p>No identity outcome is selected.</p>
      ) : (
        <>
          {selectedTimeUs !== null ? (
            <video
              controls
              preload="metadata"
              src={`/api/recordings/${encodeURIComponent(recordingId)}/video`}
              onLoadedMetadata={(event) => {
                event.currentTarget.currentTime = selectedTimeUs / 1_000_000;
              }}
            />
          ) : null}
          <img
            alt={`Exact source frame for ${selected.card_id}`}
            src={pipelineDerivedFramePath(recordingId, selectedTimeUs ?? 0)}
          />
          <p>
            Frame {String(selected.frame_identity.frame_index ?? "unknown")} ·
            requested {selectedTimeUs ?? "unknown"} μs · crop{" "}
            {String(
              (selected.crop_identity?.image_sha256 as string | undefined) ??
                "unavailable",
            )}
          </p>
          {cropUrl === null ? (
            <p>
              The exact crop is recorded by its digest. No source revision is
              available for crop preview.
            </p>
          ) : (
            <img
              alt={`Exact identity crop for ${selected.card_id}`}
              src={cropUrl}
            />
          )}
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
