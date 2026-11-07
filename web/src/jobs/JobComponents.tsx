import type { JobDetail } from "../api/jobsContracts";
import { useJobState } from "./JobState";

export function JobStatus({ job }: { job: JobDetail }) {
  return (
    <span className={`jobStatus jobStatus-${job.state}`} role="status">
      {job.state}
    </span>
  );
}

export function JobActions({
  job,
  onChanged,
}: {
  job: JobDetail;
  onChanged?: (job: JobDetail) => void;
}) {
  const { client, refresh } = useJobState();
  return (
    <span className="jobActions">
      {job.capabilities.cancel.allowed && (
        <button
          onClick={async () => {
            onChanged?.(await client.cancelJob(job.id));
            await refresh();
          }}
        >
          Cancel
        </button>
      )}
      {job.capabilities.retry.allowed && (
        <button
          onClick={async () => {
            const next = await client.retryJob(job.id, crypto.randomUUID());
            onChanged?.(next);
            await refresh();
          }}
        >
          Retry
        </button>
      )}
    </span>
  );
}

export function validatedJobResultHref(
  job: JobDetail,
  value: unknown,
): string | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const path = record.path;
  if (
    typeof path !== "string" ||
    !(path.startsWith("/api/") || path.startsWith("/v1/round-analyses/"))
  )
    return null;
  try {
    const parsed = new URL(path, window.location.origin);
    if (
      parsed.origin !== window.location.origin ||
      parsed.username ||
      parsed.password ||
      parsed.pathname.includes("..")
    )
      return null;
    const expectedJob = encodeURIComponent(job.id);
    const isJobResult = parsed.pathname.startsWith(`/api/jobs/${expectedJob}/`);
    const isCounterfactual = parsed.pathname.match(
      /^\/v1\/round-analyses\/([^/]+)\/counterfactuals\/([^/]+)$/,
    );
    const resultId = typeof record.id === "string" ? record.id : null;
    const analysisId =
      typeof job.context.analysis_id === "string"
        ? job.context.analysis_id
        : null;
    return isJobResult ||
      (isCounterfactual &&
        analysisId === decodeURIComponent(isCounterfactual[1]) &&
        resultId === decodeURIComponent(isCounterfactual[2]))
      ? path
      : null;
  } catch {
    return null;
  }
}
