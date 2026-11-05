import type { PipelineStageKey } from "../api/client";

export type LineageStageKey =
  Exclude<PipelineStageKey, "round_analyses"> | "virtual_scenes";

export type PipelineRevisionReference = {
  node_id: string;
  revision_id: string;
};

export type PipelineLineageSelection = {
  schema_version: "pipeline-lineage-selection/v1";
  selected: Partial<Record<LineageStageKey, PipelineRevisionReference>>;
};

export type PipelineLineageGraph = {
  schema_version: "pipeline-lineage-graph/v1";
  nodes: Array<{
    node_id: string;
    name: string;
    content_type: string;
    source: Record<string, unknown>;
    head_revision_id: string;
  }>;
  revisions: Array<{
    node_id: string;
    revision_id: string;
    content_sha256: string;
    created_at: string;
  }>;
  runs: Array<{ run_id: string }>;
  artifacts: Array<{ artifact_id: string; sha256: string }>;
  edges: Array<{
    kind: string;
    from: string[];
    to: string[];
    role?: string;
  }>;
};

export type LineageResolution =
  | { state: "empty"; candidates: [] }
  | { state: "unique"; candidates: [PipelineRevisionReference] }
  | { state: "ambiguous"; candidates: PipelineRevisionReference[] };

const CONTENT_TYPE_BY_STAGE: Record<LineageStageKey, string> = {
  events: "events",
  visible_cards: "visible_cards",
  virtual_scenes: "card_scene_proposals",
  visual_identities: "visual_identities",
  table_observations: "table_observations",
};

export function encodeLineageSelection(
  selection: PipelineLineageSelection,
): string {
  return JSON.stringify(selection);
}

export function decodeLineageSelection(
  value: string,
): PipelineLineageSelection | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!isSelection(parsed)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function validateLineageSelection(
  selection: PipelineLineageSelection,
  graph: PipelineLineageGraph,
): string[] {
  const nodeContentTypes = new Map(
    graph.nodes.map((node) => [node.node_id, node.content_type]),
  );
  const revisions = new Set(
    graph.revisions.map((revision) =>
      revisionKey(revision.node_id, revision.revision_id),
    ),
  );
  const missing: string[] = [];
  for (const [stage, reference] of Object.entries(selection.selected)) {
    if (reference === undefined) continue;
    if (
      nodeContentTypes.get(reference.node_id) !==
        CONTENT_TYPE_BY_STAGE[stage as LineageStageKey] ||
      !revisions.has(revisionKey(reference.node_id, reference.revision_id))
    ) {
      missing.push(`${stage}:${reference.node_id}:${reference.revision_id}`);
    }
  }
  return missing;
}

export function resolveLineageCandidates(
  graph: PipelineLineageGraph,
  anchor: PipelineRevisionReference,
  targetStage: LineageStageKey,
  direction: "ancestors" | "descendants",
): LineageResolution {
  const start = revisionKey(anchor.node_id, anchor.revision_id);
  const knownRevisions = new Set(
    graph.revisions.map((revision) =>
      revisionKey(revision.node_id, revision.revision_id),
    ),
  );
  if (!knownRevisions.has(start)) return { state: "empty", candidates: [] };

  const adjacency = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const from = key(edge.from);
    const to = key(edge.to);
    const source = direction === "descendants" ? from : to;
    const target = direction === "descendants" ? to : from;
    adjacency.set(source, [...(adjacency.get(source) ?? []), target]);
  }

  const visited = new Set<string>([start]);
  const queue = [start];
  while (queue.length > 0) {
    const current = queue.shift();
    if (current === undefined) continue;
    for (const next of adjacency.get(current) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      queue.push(next);
    }
  }

  const wantedType = CONTENT_TYPE_BY_STAGE[targetStage];
  const candidates = graph.revisions
    .filter(
      (revision) =>
        visited.has(revisionKey(revision.node_id, revision.revision_id)) &&
        graph.nodes.some(
          (node) =>
            node.node_id === revision.node_id &&
            node.content_type === wantedType,
        ),
    )
    .map(({ node_id, revision_id }) => ({ node_id, revision_id }))
    .filter(
      (candidate) =>
        candidate.node_id !== anchor.node_id ||
        candidate.revision_id !== anchor.revision_id,
    );
  if (candidates.length === 0) return { state: "empty", candidates: [] };
  if (candidates.length === 1)
    return { state: "unique", candidates: [candidates[0]] };
  return { state: "ambiguous", candidates };
}

function isSelection(value: unknown): value is PipelineLineageSelection {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (
    Object.keys(candidate).length !== 2 ||
    candidate.schema_version !== "pipeline-lineage-selection/v1" ||
    typeof candidate.selected !== "object" ||
    candidate.selected === null ||
    Array.isArray(candidate.selected)
  ) {
    return false;
  }
  return Object.entries(candidate.selected).every(
    ([stage, reference]) =>
      Object.hasOwn(CONTENT_TYPE_BY_STAGE, stage) &&
      typeof reference === "object" &&
      reference !== null &&
      Object.keys(reference).length === 2 &&
      typeof (reference as Record<string, unknown>).node_id === "string" &&
      (reference as Record<string, unknown>).node_id !== "" &&
      typeof (reference as Record<string, unknown>).revision_id === "string" &&
      (reference as Record<string, unknown>).revision_id !== "",
  );
}

function revisionKey(nodeId: string, revisionId: string): string {
  return JSON.stringify(["revision", nodeId, revisionId]);
}

function key(value: string[]): string {
  return JSON.stringify(value);
}
