import {
  ApiError,
  type PipelineRun,
  type PipelineRunResponse,
  type PipelineRunStartRequest,
} from "../api/client";

export const TERMINAL_RUN_STATES = new Set(["complete", "partial", "failed"]);

export type RunFacts = {
  run_id: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
  input_revision_ids: string[];
};

export function buildObservationRequest(
  runId: string,
  inputRevisionIds: string[],
  latestRun: PipelineRun | null,
): PipelineRunStartRequest {
  return {
    request: {
      run_id: runId,
      input_revision_ids: inputRevisionIds,
      implementation: latestRun?.implementation ?? {
        name: "observation-assembler",
        version: "v1",
      },
      model: latestRun?.model ?? null,
      configuration: latestRun?.configuration ?? {},
      extraction_policy: latestRun?.extraction_policy ?? {
        policy_id: "exact-event/v1",
      },
      crop_policy: latestRun?.crop_policy ?? null,
    },
  };
}

export function toRunFacts(
  run: PipelineRun | PipelineRunResponse | null,
): RunFacts | null {
  if (run === null) {
    return null;
  }
  return {
    run_id: run.run_id,
    status: run.status,
    attempt: run.attempt,
    request: run.request,
    state: run.state,
    input_revision_ids:
      "input_revision_ids" in run && Array.isArray(run.input_revision_ids)
        ? run.input_revision_ids
        : readStringArray(run.request.input_revision_ids),
  };
}

export function runStatusMessage(status: string): string {
  return status === "complete"
    ? "Observation assembly completed and retained its output revision."
    : status === "partial"
      ? "Observation assembly returned a partial result. Review it or retry the same frozen request."
      : status === "failed"
        ? "Observation assembly failed. Retry keeps the run ID and exact frozen inputs."
        : status === "queued"
          ? "Observation assembly is queued."
          : "Observation assembly is running.";
}

export function describePipelineError(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return "The pipeline request could not reach the backend.";
  }
  const body = readObject(reason.body);
  const detail = readObject(body?.detail);
  const message = readString(detail?.message) ?? readString(body?.message);
  if (reason.status === 422) {
    return message === null
      ? "The selected pipeline input or round context is incompatible."
      : `The selected pipeline input or round context is incompatible: ${message}`;
  }
  return message ?? `The backend returned HTTP ${reason.status}.`;
}

export function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export type RunActivity = {
  phase: string | null;
  message: string | null;
  step: number | null;
  steps: number | null;
  logs: Array<{ at: string | null; message: string }>;
};

export function readRunActivity(
  state: Record<string, unknown> | null | undefined,
): RunActivity | null {
  const metrics = readObject(state?.metrics);
  const activity = readObject(metrics?.activity);
  const rawLogs = Array.isArray(metrics?.logs) ? metrics.logs : [];
  const logs = rawLogs.flatMap((entry) => {
    const log = readObject(entry);
    const message = readString(log?.message);
    return message === null ? [] : [{ at: readString(log?.at), message }];
  });
  if (activity === null && logs.length === 0) return null;
  return {
    phase: readString(activity?.phase),
    message: readString(activity?.message),
    step: readNumber(activity?.step),
    steps: readNumber(activity?.steps),
    logs,
  };
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : [];
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}
