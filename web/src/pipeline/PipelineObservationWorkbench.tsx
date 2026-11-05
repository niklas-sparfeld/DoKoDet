import { useEffect, useState } from "react";
import {
  repositoryBundleVideoPath,
  type PipelineWorkspaceStage,
} from "../api/client";
import {
  getPipelineNodeRevision,
  type PipelineNodeRevision,
} from "./pipelineNodeClient";
import type { PipelineLineageGraph } from "./pipelineLineageSelection";
import styles from "../App.module.css";

type RawRecord = Record<string, unknown>;

export function PipelineObservationWorkbench({
  recordingId,
  stage,
  selectedItemId,
  selectedNode,
  lineageGraph,
  onSelectNodeObservation,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  selectedItemId: string | null;
  selectedNode?: { nodeId: string; revisionId: string } | null;
  lineageGraph?: PipelineLineageGraph | null;
  onSelectNodeObservation?: (itemId: string, timeUs: number) => void;
}) {
  if (selectedNode !== undefined && selectedNode !== null)
    return (
      <PipelineNodeObservationWorkbench
        recordingId={recordingId}
        nodeId={selectedNode.nodeId}
        revisionId={selectedNode.revisionId}
        selectedItemId={selectedItemId}
        stage={stage}
        lineageGraph={lineageGraph ?? null}
        onSelect={onSelectNodeObservation ?? (() => undefined)}
      />
    );
  const observation = findObservation(stage, selectedItemId);

  return (
    <div className={styles.observationWorkbenchSurface}>
      <video
        className={styles.cardEventSourceVideo}
        data-recording-source-video={recordingId}
        src={repositoryBundleVideoPath(recordingId)}
        controls
        preload="none"
        aria-label={`Table-observation source video ${recordingId}`}
      />
      {observation === null ? (
        <p className={styles.detailEmptyState}>
          {stage.runs.length === 0
            ? "Choose compatible inputs in the inspector to assemble table observations."
            : "Select an observation interval from the Timeline Rail."}
        </p>
      ) : (
        <section className={styles.observationWorkbenchSummary}>
          <div>
            <p className={styles.statusLabel}>Selected table observation</p>
            <h2>Observation {observation.id}</h2>
          </div>
          <dl>
            <div>
              <dt>Source time</dt>
              <dd>{formatTime(observation.observedAtMs)}</dd>
            </div>
            <div>
              <dt>Outcome</dt>
              <dd>{observation.status ?? "Unavailable"}</dd>
            </div>
            <div>
              <dt>Visible cards</dt>
              <dd>
                {observation.cardCount} visible card
                {observation.cardCount === 1 ? "" : "s"}
              </dd>
            </div>
            <div>
              <dt>Capabilities</dt>
              <dd>{observation.capabilities || "Unavailable"}</dd>
            </div>
          </dl>
        </section>
      )}
    </div>
  );
}

function PipelineNodeObservationWorkbench({
  recordingId,
  nodeId,
  revisionId,
  selectedItemId,
  stage,
  lineageGraph,
  onSelect,
}: {
  recordingId: string;
  nodeId: string;
  revisionId: string;
  selectedItemId: string | null;
  stage: PipelineWorkspaceStage;
  lineageGraph: PipelineLineageGraph | null;
  onSelect: (itemId: string, timeUs: number) => void;
}) {
  const [revision, setRevision] = useState<PipelineNodeRevision | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getPipelineNodeRevision(nodeId, revisionId)
      .then((loaded) => {
        if (
          loaded.content_type !== "table_observations" ||
          !Array.isArray(loaded.content.observations)
        )
          throw new Error(
            "The selected node does not contain table observations.",
          );
        if (!cancelled) {
          setRevision(loaded);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId, revisionId]);

  const observations = Array.isArray(revision?.content.observations)
    ? revision.content.observations.filter(isRecord)
    : [];
  const selected = observations.find(
    (value) => value.observation_id === selectedItemId,
  );
  const target = JSON.stringify(["revision", nodeId, revisionId]);
  const directEdges =
    lineageGraph?.edges.filter((edge) => JSON.stringify(edge.to) === target) ??
    [];
  const producer = directEdges.find((edge) => edge.kind === "produced");
  const inputs =
    producer === undefined
      ? []
      : (lineageGraph?.edges.filter(
          (edge) =>
            edge.kind === "used" &&
            JSON.stringify(edge.to) === JSON.stringify(producer.from),
        ) ?? []);
  const failedRuns = stage.runs.filter(
    (run) => run.status === "failed" || run.status === "partial",
  );
  return (
    <div className={styles.observationWorkbenchSurface}>
      <video
        className={styles.cardEventSourceVideo}
        data-recording-source-video={recordingId}
        src={repositoryBundleVideoPath(recordingId)}
        controls
        preload="none"
        aria-label={`Table-observation source video ${recordingId}`}
      />
      <section aria-label="Selected observation revision">
        <h2>{revision?.name ?? "Table observation revision"}</h2>
        <p>
          Revision {revisionId} · {observations.length} observation
          {observations.length === 1 ? "" : "s"}
        </p>
        {inputs.length === 0 ? (
          <p>No recorded processor inputs for this revision.</p>
        ) : (
          <section aria-label="Observation input provenance">
            <h3>Exact processor inputs</h3>
            <ul>
              {inputs.map((edge, index) => (
                <li key={`${edge.from.join("-")}-${index}`}>
                  {edge.role ?? "input"}: {edge.from.slice(1).join(" / ")}
                </li>
              ))}
            </ul>
          </section>
        )}
        {observations.length === 0 ? (
          <p>This observation revision has no observations.</p>
        ) : (
          <nav aria-label="Observations">
            {observations.map((observation) => {
              const id =
                typeof observation.observation_id === "string"
                  ? observation.observation_id
                  : "";
              const timeUs =
                typeof observation.observed_at_ms === "number"
                  ? observation.observed_at_ms * 1_000
                  : 0;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={id === selectedItemId}
                  onClick={() => onSelect(id, timeUs)}
                >
                  {id || "Observation without an ID"} · {timeUs} μs ·{" "}
                  {String(observation.status ?? "unknown")}
                </button>
              );
            })}
          </nav>
        )}
        {selected === undefined ? (
          <p>
            {selectedItemId === null
              ? "Select an observation from this exact revision."
              : "The requested observation is not present in this revision. No other observation was selected."}
          </p>
        ) : (
          <pre aria-label="Selected observation data">
            {JSON.stringify(selected, null, 2)}
          </pre>
        )}
      </section>
      {failedRuns.length > 0 ? (
        <section aria-label="Failed observation attempts">
          <h3>Failed and partial attempts</h3>
          <ul>
            {failedRuns.map((run) => (
              <li key={run.run_id}>
                {run.run_id} · {run.status} · inputs{" "}
                {run.input_revision_ids.join(", ") || "none"}
                {run.failure?.message ? ` · ${run.failure.message}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}

function findObservation(
  stage: PipelineWorkspaceStage,
  selectedItemId: string | null,
): {
  id: string;
  observedAtMs: number | null;
  status: string | null;
  cardCount: number;
  capabilities: string;
} | null {
  if (selectedItemId === null) return null;
  for (const run of stage.runs) {
    const items = Array.isArray(run.state.items) ? run.state.items : [];
    for (const item of items) {
      const record = asRecord(item);
      if (record?.item_id !== selectedItemId) continue;
      const result = asRecord(record.result);
      if (result === null) return null;
      const capabilities = Array.isArray(result.capabilities)
        ? result.capabilities.filter(isString).join(", ")
        : "";
      return {
        id: selectedItemId,
        observedAtMs:
          typeof result.observed_at_ms === "number"
            ? result.observed_at_ms
            : null,
        status: typeof result.status === "string" ? result.status : null,
        cardCount: Array.isArray(result.cards) ? result.cards.length : 0,
        capabilities,
      };
    }
  }
  return null;
}

function asRecord(value: unknown): RawRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as RawRecord)
    : null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatTime(timeMs: number | null): string {
  if (timeMs === null) return "Unavailable";
  return `${(timeMs / 1_000).toFixed(2)} s`;
}
