import { useEffect, useState } from "react";
import type { JobDetail } from "../api/client";
import { useJobState } from "./JobState";
import { JobStatus } from "./JobComponents";

export function JobListView() {
  const { client, jobs, loading, error, refresh } = useJobState();
  const [scope, setScope] = useState<"active" | "history">("active");
  const [historyPage, setHistoryPage] = useState<{
    items: JobDetail[];
    cursor: string | null;
  } | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    void client
      .listJobs({ scope, limit: 50, signal: controller.signal })
      .then((page) => {
        if (alive) {
          setHistoryPage({ items: page.items, cursor: page.next_cursor });
          setListError(null);
        }
      })
      .catch(() => {
        if (alive) setListError("Unable to load job history.");
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [client, scope]);
  const shown = scope === "active" ? jobs : (historyPage?.items ?? []);
  return (
    <main>
      <a href="/">Recordings</a>
      <h1>Jobs</h1>
      <button
        aria-pressed={scope === "active"}
        onClick={() => setScope("active")}
      >
        Active
      </button>
      <button
        aria-pressed={scope === "history"}
        onClick={() => setScope("history")}
      >
        History
      </button>
      {(error || listError) && (
        <p role="alert">
          {error ?? listError}{" "}
          <button onClick={() => void refresh()}>Retry</button>
        </p>
      )}
      {loading && scope === "active" && shown.length === 0 ? (
        <p role="status">Loading jobs…</p>
      ) : null}
      <ul>
        {shown.map((job) => (
          <li key={job.id}>
            <a href={`/jobs/${encodeURIComponent(job.id)}`}>{job.label}</a>{" "}
            <JobStatus job={job} />
          </li>
        ))}
      </ul>
      {scope === "history" && historyPage?.cursor && (
        <button
          onClick={async () => {
            const nextCursor = historyPage.cursor;
            if (!nextCursor) return;
            const page = await client.listJobs({
              scope,
              cursor: nextCursor,
              limit: 50,
            });
            setHistoryPage((current) =>
              current
                ? {
                    items: [...current.items, ...page.items],
                    cursor: page.next_cursor,
                  }
                : { items: page.items, cursor: page.next_cursor },
            );
          }}
        >
          Load more
        </button>
      )}
    </main>
  );
}
