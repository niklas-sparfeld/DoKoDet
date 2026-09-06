import {
  repositoryBundleVideoPath,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";

type RawRecord = Record<string, unknown>;

export function PipelineObservationWorkbench({
  recordingId,
  stage,
  selectedItemId,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  selectedItemId: string | null;
}) {
  const observation = findObservation(stage, selectedItemId);

  return (
    <div className={styles.observationWorkbenchSurface}>
      <video
        className={styles.cardEventSourceVideo}
        data-recording-source-video={recordingId}
        src={repositoryBundleVideoPath(recordingId)}
        controls
        preload="metadata"
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

function formatTime(timeMs: number | null): string {
  if (timeMs === null) return "Unavailable";
  return `${(timeMs / 1_000).toFixed(2)} s`;
}
