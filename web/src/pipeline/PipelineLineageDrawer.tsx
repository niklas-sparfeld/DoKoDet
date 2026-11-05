import { useState } from "react";
import type {
  LineageStageKey,
  PipelineLineageGraph,
  PipelineLineageSelection,
} from "./pipelineLineageSelection";
import styles from "./RecordingWorkspaceShell.module.css";

const COLUMNS: Array<{
  key: LineageStageKey | "round_analyses";
  label: string;
  contentType: string | string[] | null;
}> = [
  { key: "events", label: "Events", contentType: "events" },
  {
    key: "visible_cards",
    label: "Visible cards",
    contentType: "visible_cards",
  },
  {
    key: "virtual_scenes",
    label: "Virtual scenes",
    contentType: ["card_scene_proposals", "virtual_scenes"],
  },
  {
    key: "visual_identities",
    label: "Visual identities",
    contentType: "visual_identities",
  },
  {
    key: "table_observations",
    label: "Table observations",
    contentType: "table_observations",
  },
  { key: "round_analyses", label: "Round analysis", contentType: null },
];

type Props = {
  id: string;
  graph: PipelineLineageGraph | null;
  graphError: string | null;
  selection: PipelineLineageSelection | null;
  onSelect: (selection: PipelineLineageSelection) => void;
  onCopy: (
    column: LineageStageKey,
    nodeId: string,
    revisionId: string,
  ) => Promise<void>;
  selectedAnalysisId?: string | null;
  onSelectAnalysis?: (analysisId: string) => void;
};

export function PipelineLineageDrawer({
  id,
  graph,
  graphError,
  selection,
  onSelect,
  onCopy,
  selectedAnalysisId = null,
  onSelectAnalysis,
}: Props) {
  const revisionsByNode = new Map<string, PipelineLineageGraph["revisions"]>();
  for (const revision of graph?.revisions ?? []) {
    revisionsByNode.set(revision.node_id, [
      ...(revisionsByNode.get(revision.node_id) ?? []),
      revision,
    ]);
  }
  for (const revisions of revisionsByNode.values()) {
    revisions.sort((left, right) =>
      left.created_at.localeCompare(right.created_at),
    );
  }

  return (
    <section
      aria-label="Pipeline lineage"
      className={styles.lineageDrawer}
      id={id}
    >
      <div className={styles.lineageHeading}>
        <div>
          <h2>Data lineage</h2>
          <p>Select a saved revision to inspect that branch.</p>
        </div>
        {graph === null ? (
          <span role="status">{graphError ?? "Loading lineage…"}</span>
        ) : null}
      </div>
      {graph === null ? null : (
        <div className={styles.lineageColumns}>
          {COLUMNS.map((column) => {
            const nodes =
              column.contentType === null
                ? []
                : graph.nodes.filter((node) =>
                    Array.isArray(column.contentType)
                      ? column.contentType.includes(node.content_type)
                      : node.content_type === column.contentType,
                  );
            const analysisRuns =
              column.key === "round_analyses"
                ? graph.runs.filter((run) => run.run_kind === "analysis")
                : [];
            return (
              <section
                aria-label={`${column.label} lineage`}
                className={styles.lineageColumn}
                key={column.key}
              >
                <h3>{column.label}</h3>
                {column.key === "round_analyses" ? (
                  analysisRuns.length === 0 ? (
                    <p className={styles.lineageEmpty}>No analysis runs</p>
                  ) : (
                    analysisRuns.map((run) => (
                      <AnalysisRunCard
                        key={run.run_id}
                        graph={graph}
                        runId={run.run_id}
                        status={run.status ?? "Status unavailable"}
                        selected={selectedAnalysisId === run.run_id}
                        onSelect={onSelectAnalysis}
                      />
                    ))
                  )
                ) : nodes.length === 0 ? (
                  <p className={styles.lineageEmpty}>No data sets</p>
                ) : (
                  nodes.map((node) => {
                    const revisions = revisionsByNode.get(node.node_id) ?? [];
                    const selected =
                      column.key === "round_analyses"
                        ? undefined
                        : selection?.selected[column.key];
                    const selectedRevision =
                      selected?.node_id === node.node_id
                        ? selected.revision_id
                        : null;
                    const head = revisions.find(
                      (revision) =>
                        revision.revision_id === node.head_revision_id,
                    );
                    const visibleRevision =
                      revisions.find(
                        (revision) => revision.revision_id === selectedRevision,
                      ) ?? head;
                    return (
                      <article
                        className={`${styles.lineageNode} ${
                          selectedRevision === visibleRevision?.revision_id
                            ? styles.lineageNodeSelected
                            : ""
                        }`}
                        key={node.node_id}
                      >
                        <strong title={node.name}>{node.name}</strong>
                        {visibleRevision === undefined ? (
                          <p>No saved revisions</p>
                        ) : (
                          <RevisionChoice
                            active={
                              selectedRevision === visibleRevision.revision_id
                            }
                            column={column.key}
                            revisionId={visibleRevision.revision_id}
                            nodeId={node.node_id}
                            onSelect={onSelect}
                            selection={selection}
                          />
                        )}
                        {visibleRevision !== undefined ? (
                          <small>
                            Saved {formatDate(visibleRevision.created_at)} · sha
                            {visibleRevision.content_sha256.slice(0, 8)}
                          </small>
                        ) : null}
                        <RevisionSources
                          graph={graph}
                          nodeId={node.node_id}
                          revisionId={visibleRevision?.revision_id ?? null}
                        />
                        {visibleRevision !== undefined &&
                        column.key !== "round_analyses" ? (
                          <CopyNodeAction
                            column={column.key}
                            nodeId={node.node_id}
                            revisionId={visibleRevision.revision_id}
                            onCopy={onCopy}
                          />
                        ) : null}
                        {revisions.length > 1 ? (
                          <details className={styles.lineageHistory}>
                            <summary>History ({revisions.length})</summary>
                            {revisions.map((revision) => (
                              <div key={revision.revision_id}>
                                <RevisionChoice
                                  active={
                                    selectedRevision === revision.revision_id
                                  }
                                  column={column.key}
                                  revisionId={revision.revision_id}
                                  nodeId={node.node_id}
                                  onSelect={onSelect}
                                  selection={selection}
                                />
                                {revision.revision_id ===
                                node.head_revision_id ? (
                                  <small>Current head</small>
                                ) : null}
                                <RevisionSources
                                  graph={graph}
                                  nodeId={node.node_id}
                                  revisionId={revision.revision_id}
                                />
                              </div>
                            ))}
                          </details>
                        ) : null}
                      </article>
                    );
                  })
                )}
              </section>
            );
          })}
        </div>
      )}
      {graph !== null ? (
        <p className={styles.lineageHint}>
          Copy relationships and processor inputs are labeled on each revision.
          Selection is saved in this recording’s URL.
        </p>
      ) : null}
    </section>
  );
}

function AnalysisRunCard({
  graph,
  runId,
  status,
  selected,
  onSelect,
}: {
  graph: PipelineLineageGraph;
  runId: string;
  status: string;
  selected: boolean;
  onSelect?: (analysisId: string) => void;
}) {
  const inputs = graph.edges.filter(
    (edge) =>
      edge.kind === "used" &&
      JSON.stringify(edge.to) === JSON.stringify(["run", runId]),
  );
  return (
    <article className={styles.lineageNode}>
      {onSelect === undefined ? (
        <strong>Analysis {runId}</strong>
      ) : (
        <button
          type="button"
          aria-pressed={selected}
          onClick={() => onSelect(runId)}
        >
          Analysis {runId}
        </button>
      )}
      <small>Status: {status}</small>
      {inputs.length === 0 ? (
        <small>No recorded inputs</small>
      ) : (
        <ul
          aria-label={`Inputs for analysis ${runId}`}
          className={styles.lineageSources}
        >
          {inputs.map((input, index) => (
            <li key={`${input.from.join("-")}-${index}`}>
              <span>Analysis input</span>
              <small>{input.role ?? "input"}</small>
              <code>{input.from.slice(1).join(" / ")}</code>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function CopyNodeAction({
  column,
  nodeId,
  revisionId,
  onCopy,
}: {
  column: LineageStageKey;
  nodeId: string;
  revisionId: string;
  onCopy: (
    column: LineageStageKey,
    nodeId: string,
    revisionId: string,
  ) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          void onCopy(column, nodeId, revisionId)
            .catch((reason: unknown) =>
              setError(
                reason instanceof Error ? reason.message : "Copy failed.",
              ),
            )
            .finally(() => setBusy(false));
        }}
        type="button"
      >
        {busy ? "Creating copy…" : "Create copy"}
      </button>
      {error !== null ? <small role="alert">{error}</small> : null}
    </>
  );
}

function RevisionChoice({
  active,
  column,
  nodeId,
  revisionId,
  onSelect,
  selection,
}: {
  active: boolean;
  column: LineageStageKey | "round_analyses";
  nodeId: string;
  revisionId: string;
  onSelect: (selection: PipelineLineageSelection) => void;
  selection: PipelineLineageSelection | null;
}) {
  if (column === "round_analyses") return null;
  const reference = { node_id: nodeId, revision_id: revisionId };
  return (
    <button
      aria-pressed={active}
      className={styles.lineageRevision}
      onClick={() => {
        const next: PipelineLineageSelection = {
          schema_version: "pipeline-lineage-selection/v1",
          selected: { ...(selection?.selected ?? {}), [column]: reference },
        };
        onSelect(next);
      }}
      title={`${nodeId} / ${reference.revision_id}`}
      type="button"
    >
      r {revisionId}
    </button>
  );
}

function RevisionSources({
  graph,
  nodeId,
  revisionId,
}: {
  graph: PipelineLineageGraph;
  nodeId: string;
  revisionId: string | null;
}) {
  if (revisionId === null) return null;
  const target = JSON.stringify(["revision", nodeId, revisionId]);
  const direct = graph.edges.filter(
    (edge) =>
      JSON.stringify(edge.to) === target &&
      ["copied", "revised", "restored"].includes(edge.kind),
  );
  const producer = graph.edges.find(
    (edge) => edge.kind === "produced" && JSON.stringify(edge.to) === target,
  );
  const processorInputs =
    producer === undefined
      ? []
      : graph.edges.filter(
          (edge) =>
            edge.kind === "used" &&
            JSON.stringify(edge.to) === JSON.stringify(producer.from),
        );
  const sources = [
    ...direct.map((edge) => ({
      kind:
        edge.kind === "copied"
          ? "Copy source"
          : edge.kind === "restored"
            ? "Restore source"
            : "Revision source",
      ref: edge.from,
      role: "",
    })),
    ...processorInputs.map((edge) => ({
      kind: "Processor input",
      ref: edge.from,
      role: edge.role ?? "input",
    })),
  ];
  if (sources.length === 0) return <small>Source: recording input</small>;
  return (
    <ul
      className={styles.lineageSources}
      aria-label={`Sources for ${revisionId}`}
    >
      {sources.map((source, index) => (
        <li key={`${source.kind}-${source.ref.join("-")}-${index}`}>
          <span>{source.kind}</span>
          {source.role ? <small>{source.role}</small> : null}
          <code>{source.ref.slice(1).join(" / ")}</code>
        </li>
      ))}
    </ul>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}
