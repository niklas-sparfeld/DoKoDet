import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/transport";
import type { DokoDetectorClient } from "../api/clientTypes";
import type { PipelineWorkspace } from "../api/pipelineContracts";
import type { PipelineNavigationStepKey } from "./recordingPipelineUrl";
import {
  decodeLineageSelection,
  validateLineageSelection,
} from "./pipelineLineageSelection";
import type { PipelineLineageGraph } from "./pipelineLineageSelection";
import { PIPELINE_STAGE_KEYS } from "./recordingWorkspacePresentation";

type WorkspaceClient = Pick<
  DokoDetectorClient,
  "getRecordingPipeline" | "getFrameReviewPage" | "updateFrameReviewWorkflow"
>;

export function useRecordingPipelineData(
  recordingId: string,
  stageKey: PipelineNavigationStepKey | null,
  lineage: string | null,
  client: WorkspaceClient,
) {
  const [workspace, setWorkspace] = useState<PipelineWorkspace | null>(null);
  const [loadedStageKey, setLoadedStageKey] =
    useState<PipelineNavigationStepKey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lineageValidation, setLineageValidation] = useState<{
    lineage: string;
    notice: string | null;
  } | null>(null);
  const [lineageGraph, setLineageGraph] = useState<PipelineLineageGraph | null>(
    null,
  );
  const [lineageGraphError, setLineageGraphError] = useState<string | null>(
    null,
  );
  const [lineageRefresh, setLineageRefresh] = useState(0);
  const workspaceLoadIdentityRef = useRef<string | null>(null);
  const workspaceRequestRef = useRef(0);

  const loadWorkspace = useCallback(
    async (signal?: AbortSignal) => {
      const requestId = ++workspaceRequestRef.current;
      try {
        const backendStageKey = stageKey === "virtual_scenes" ? null : stageKey;
        const response = await client.getRecordingPipeline(
          recordingId,
          { signal },
          backendStageKey ?? "events",
        );
        if (signal?.aborted || requestId !== workspaceRequestRef.current)
          return;
        if (isPipelineWorkspace(response, recordingId)) {
          setWorkspace(response);
          setLoadedStageKey(stageKey ?? "events");
          setError(null);
        } else {
          setWorkspace(null);
          if (stageKey !== null) {
            setError(
              "The backend returned an invalid recording pipeline workspace.",
            );
          }
        }
      } catch (reason: unknown) {
        if (!signal?.aborted && requestId === workspaceRequestRef.current) {
          setError(describePipelineError(reason));
        }
      } finally {
        if (!signal?.aborted && requestId === workspaceRequestRef.current) {
          setLoading(false);
        }
      }
    },
    [client, recordingId, stageKey],
  );

  useEffect(() => {
    if (
      workspace?.recording_id === recordingId &&
      loadedStageKey === (stageKey ?? "events")
    )
      return;
    const loadIdentity = `${recordingId}:${stageKey ?? "events"}`;
    if (workspaceLoadIdentityRef.current === loadIdentity) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      if (workspaceLoadIdentityRef.current === loadIdentity) return;
      workspaceLoadIdentityRef.current = loadIdentity;
      void loadWorkspace(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [loadWorkspace, loadedStageKey, recordingId, stageKey, workspace]);

  useEffect(() => {
    const selection = lineage === null ? null : decodeLineageSelection(lineage);
    const controller = new AbortController();
    void fetch(
      `/api/recordings/${encodeURIComponent(recordingId)}/pipeline/lineage`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error("Lineage data could not be loaded.");
        const graph: unknown = await response.json();
        if (!isPipelineLineageGraph(graph)) {
          throw new Error("The backend returned invalid lineage data.");
        }
        return graph;
      })
      .then((graph) => {
        if (controller.signal.aborted) return;
        setLineageGraph(graph);
        setLineageGraphError(null);
        if (selection === null || lineage === null) {
          setLineageValidation(null);
        } else {
          const missing = validateLineageSelection(selection, graph);
          setLineageValidation({
            lineage,
            notice:
              missing.length === 0
                ? null
                : "The saved lineage selection is unavailable. No other revision was selected.",
          });
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setLineageGraph(null);
        setLineageGraphError("Lineage data could not be loaded.");
        if (lineage !== null) {
          setLineageValidation({
            lineage,
            notice:
              "Lineage data could not be loaded. The saved selection was not changed.",
          });
        }
      });
    return () => controller.abort();
  }, [lineageRefresh, recordingId, lineage]);

  const refreshLineage = useCallback(
    () => setLineageRefresh((value) => value + 1),
    [],
  );
  return {
    workspace,
    setWorkspace,
    loadedStageKey,
    loading,
    error,
    setError,
    loadWorkspace,
    lineageValidation,
    lineageGraph,
    lineageGraphError,
    refreshLineage,
  };
}

function isPipelineWorkspace(
  value: unknown,
  recordingId: string,
): value is PipelineWorkspace {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "pipeline-workspace/v1" &&
    "recording_id" in value &&
    value.recording_id === recordingId &&
    "video" in value &&
    typeof value.video === "object" &&
    value.video !== null &&
    "stages" in value &&
    Array.isArray(value.stages) &&
    value.stages.length === PIPELINE_STAGE_KEYS.length
  );
}

function isPipelineLineageGraph(value: unknown): value is PipelineLineageGraph {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    value.schema_version === "pipeline-lineage-graph/v1" &&
    "nodes" in value &&
    Array.isArray(value.nodes) &&
    "revisions" in value &&
    Array.isArray(value.revisions) &&
    "runs" in value &&
    Array.isArray(value.runs) &&
    "artifacts" in value &&
    Array.isArray(value.artifacts) &&
    "edges" in value &&
    Array.isArray(value.edges)
  );
}

export function describePipelineError(reason: unknown): string {
  if (!(reason instanceof ApiError)) return "The backend could not be reached.";
  const body =
    typeof reason.body === "object" && reason.body !== null
      ? (reason.body as Record<string, unknown>)
      : null;
  const detail =
    typeof body?.detail === "object" && body.detail !== null
      ? (body.detail as Record<string, unknown>)
      : null;
  const message =
    typeof detail?.message === "string"
      ? detail.message
      : typeof body?.message === "string"
        ? body.message
        : null;
  if (
    message?.toLowerCase().includes("video") ||
    message?.toLowerCase().includes("recording")
  ) {
    return `The accepted recording video is unavailable: ${message}`;
  }
  if (reason.status === 422) {
    return message === null
      ? "The selected pipeline input is incompatible with this stage."
      : `The selected pipeline input is incompatible with this stage: ${message}`;
  }
  return message ?? `The backend returned HTTP ${reason.status}.`;
}
