import { useCallback, useRef, useState } from "react";
import type { EnqueueJobBody, JobDetail } from "../api/jobsContracts";
import { useJobState } from "./JobState";

export type JobEnqueue = (
  payload: EnqueueJobBody,
  idempotencyKey: string,
) => Promise<JobDetail>;

/** One submission owner. A retry after an uncertain response reuses its exact key and payload. */
export function useJobSubmission(
  enqueue: JobEnqueue,
  onAccepted?: (job: JobDetail) => void,
) {
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  const inFlight = useRef(false);

  const submit = useCallback(
    async (payload: EnqueueJobBody) => {
      if (inFlight.current) return null;
      const fingerprint = JSON.stringify(payload);
      const current = pending.current;
      const idempotencyKey =
        current?.fingerprint === fingerprint
          ? current.key
          : crypto.randomUUID();
      pending.current = { fingerprint, key: idempotencyKey };
      inFlight.current = true;
      setSubmitting(true);
      setError(null);
      try {
        const accepted = await enqueue(payload, idempotencyKey);
        pending.current = null;
        setJob(accepted);
        onAccepted?.(accepted);
        return accepted;
      } catch (cause) {
        const status =
          cause && typeof cause === "object" && "status" in cause
            ? Number((cause as { status: unknown }).status)
            : null;
        if (status !== null && status >= 400 && status < 500)
          pending.current = null;
        setError(
          status !== null && status >= 400 && status < 500
            ? "The request was rejected. Correct the inputs and try again."
            : "Acceptance is uncertain. Retry to reconcile the same request.",
        );
        return null;
      } finally {
        inFlight.current = false;
        setSubmitting(false);
      }
    },
    [enqueue, onAccepted],
  );

  const clear = useCallback(() => {
    if (inFlight.current) return;
    pending.current = null;
    setJob(null);
    setError(null);
  }, []);

  return { submit, submitting, job, error, clear };
}

export function AcceptedJobReceipt({ job }: { job: JobDetail }) {
  return (
    <p role="status">
      Accepted job: <a href={`/jobs/${encodeURIComponent(job.id)}`}>{job.id}</a>
    </p>
  );
}

/** Connects launch acceptance to the app-owned Jobs state and polling provider. */
export function useManagedJobSubmission() {
  const { client, refresh } = useJobState();
  const enqueue = useCallback(
    (payload: EnqueueJobBody, key: string) => client.enqueueJob(payload, key),
    [client],
  );
  const onAccepted = useCallback(() => {
    void refresh();
  }, [refresh]);
  return useJobSubmission(enqueue, onAccepted);
}
