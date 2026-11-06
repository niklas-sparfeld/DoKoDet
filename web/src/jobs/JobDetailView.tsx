import { useEffect, useState } from "react";
import type { JobDetail as Job } from "../api/client";
import { useJobState } from "./JobState";
import { JobActions, JobStatus, validatedJobResultHref } from "./JobComponents";
import { usePageVisibility } from "../pipeline/usePageVisibility";

export function JobDetailView({ jobId }: { jobId: string }) {
  const { getJob, client } = useJobState();
  const pageVisible = usePageVisibility();
  const [job, setJob] = useState<Job | null>(null);
  const [logs, setLogs] = useState<Awaited<
    ReturnType<typeof client.getJobLogs>
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const jobRevision = job?.revision;
  const jobState = job?.state;
  const active =
    jobState !== undefined &&
    ["queued", "running", "waiting", "cancelling"].includes(jobState);
  useEffect(() => {
    let alive = true;
    let timer = 0;
    let controller: AbortController | undefined;
    const load = async () => {
      controller = new AbortController();
      try {
        const found = await getJob(jobId, controller.signal);
        if (alive) {
          setJob((old) => (old && old.revision > found.revision ? old : found));
          setError(null);
        }
        if (alive && pageVisible && active)
          timer = window.setTimeout(load, 2000);
      } catch {
        if (alive && !controller.signal.aborted) {
          setError(
            "Unable to load this job. Retry after the connection returns.",
          );
          if (active || jobState === undefined)
            timer = window.setTimeout(load, 2000);
        }
      }
    };
    if (pageVisible) void load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      controller?.abort();
    };
  }, [jobId, getJob, active, pageVisible, jobState]);
  useEffect(() => {
    if (jobRevision === undefined) return;
    const controller = new AbortController();
    void client
      .getJobLogs(jobId, { limit: 100, signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) setLogs(page);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [client, jobId, jobRevision]);
  if (!job)
    return (
      <main>
        <h1>Job</h1>
        <p role="status">{error ?? "Loading job…"}</p>
        <a href="/">Back to recordings</a>
      </main>
    );
  return (
    <main className="jobDetail">
      <a href="/">Recordings</a>
      <h1>{job.label}</h1>
      <JobStatus job={job} />
      <JobActions job={job} onChanged={setJob} />
      {error && (
        <p role="alert">
          {error}{" "}
          <button
            onClick={() =>
              void getJob(jobId)
                .then(setJob)
                .catch(() => {})
            }
          >
            Retry
          </button>
        </p>
      )}
      <dl>
        <dt>Type</dt>
        <dd>{job.type}</dd>
        <dt>Created</dt>
        <dd>{job.created_at}</dd>
        <dt>Phase</dt>
        <dd>{job.phase ?? "—"}</dd>
        <dt>Waiting reason</dt>
        <dd>{job.waiting_reason ?? "—"}</dd>
      </dl>
      <h2>Steps</h2>
      <ol>
        {job.steps.map((step) => (
          <li key={step.id}>
            {step.label}: {step.state}
            {step.completed != null && step.total != null
              ? ` (${step.completed} of ${step.total})`
              : ""}
          </li>
        ))}
      </ol>
      {job.results.map((result, index) => {
        const href = validatedJobResultHref(job, result);
        return href ? (
          <p key={index}>
            <a href={href}>Open exact result</a>
          </p>
        ) : null;
      })}
      <h2>Logs</h2>
      <ol aria-label="Job logs">
        {logs?.entries.map((entry) => (
          <li key={entry.sequence}>
            {entry.timestamp} {entry.level}: {entry.message}
          </li>
        ))}
      </ol>
      {logs && logs.next_after > 0 && (
        <button
          onClick={async () => {
            const newer = await client.getJobLogs(job.id, {
              after: logs.next_after,
              limit: 100,
            });
            setLogs((current) =>
              current
                ? { ...newer, entries: [...current.entries, ...newer.entries] }
                : newer,
            );
          }}
        >
          Load newer logs
        </button>
      )}
    </main>
  );
}
