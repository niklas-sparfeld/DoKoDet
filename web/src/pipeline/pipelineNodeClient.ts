export type PipelineNodeRevision = {
  node_id: string;
  name: string;
  content_type: string;
  head_revision_id: string;
  revision_id: string;
  parent_revision_id: string | null;
  content: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type PipelineNodeEditResult = {
  node_id: string;
  revision_id: string;
  copied: boolean;
  reason?: string;
  name?: string;
};

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    ...(body === undefined ? {} : { method: "POST" }),
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function getPipelineNodeRevision(nodeId: string, revisionId: string) {
  return request<PipelineNodeRevision>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}`,
  );
}

export function editPipelineNode(
  nodeId: string,
  payload: {
    expected_revision_id: string;
    idempotency_key: string;
    actor: { kind: "human"; id: string };
    content: Record<string, unknown>;
    base_pointers: Record<string, string>;
    pointers: Record<string, string>;
    operations: Array<{ kind: "replace"; before: string[]; after: string[] }>;
  },
) {
  return request<PipelineNodeEditResult>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/edit`,
    payload,
  );
}

export function reviewPipelineNodeItem(
  nodeId: string,
  payload: {
    review_id: string;
    revision_id: string;
    item_id: string;
    question: string;
    decision: string;
    reviewer: { kind: "human"; id: string };
    evidence: Record<string, unknown>;
  },
) {
  return request<Record<string, unknown>>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/reviews/item`,
    payload,
  );
}

export function reviewPipelineNodeCoverage(
  nodeId: string,
  payload: {
    review_id: string;
    revision_id: string;
    question: string;
    coverage: Record<string, unknown>;
    reviewer: { kind: "human"; id: string };
    evidence: Record<string, unknown>;
  },
) {
  return request<Record<string, unknown>>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/reviews/coverage`,
    payload,
  );
}

export function reviewPipelineNodeOverall(
  nodeId: string,
  payload: {
    review_id: string;
    revision_id: string;
    question: string;
    decision: string;
    reviewer: { kind: "human"; id: string };
    evidence: Record<string, unknown>;
  },
) {
  return request<Record<string, unknown>>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/reviews/overall`,
    payload,
  );
}

export function listPipelineNodeReviews(nodeId: string, revisionId: string) {
  return request<Array<Record<string, unknown>>>(
    `/api/pipeline/nodes/${encodeURIComponent(nodeId)}/revisions/${encodeURIComponent(revisionId)}/reviews`,
  );
}
