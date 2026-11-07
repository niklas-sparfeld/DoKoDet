import { useEffect, useMemo, useRef, useState } from "react";
import type { JobDetail } from "../api/jobsContracts";
import { useJobState, isActiveJob } from "./JobState";
import { JobActions, JobStatus } from "./JobComponents";

export function JobsDrawer() {
  const { client, jobs, error, refresh } = useJobState();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"active" | "history">("active");
  const [history, setHistory] = useState<JobDetail[]>([]);
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [queue, setQueue] = useState<{
    groups: { group_id: string; child_job_ids: string[] }[];
    revision: number;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const activeCount = jobs.filter((job) => isActiveJob(job.state)).length;
  const historyCount = history.length;
  const visible = useMemo(
    () =>
      (tab === "active" ? jobs : history).filter((job) =>
        `${job.label} ${job.id} ${job.state}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
      ),
    [jobs, history, tab, filter],
  );

  async function showHistory() {
    setTab("history");
    try {
      setHistory(
        (await client.listJobs({ scope: "history", limit: 50 })).items,
      );
      setActionError(null);
    } catch {
      setActionError("Unable to load job history.");
    }
  }
  async function move(groupId: string, before: string | null) {
    if (!queue) return;
    try {
      const result = await client.moveJob(groupId, before, queue.revision);
      setQueue({ groups: result.groups, revision: result.revision });
      await refresh();
    } catch {
      setActionError("Queue changed. Refresh jobs before reordering.");
      setQueue(null);
    }
  }
  const groups = queue?.groups ?? [];
  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);
  return (
    <>
      <header className="jobsChrome">
        <a href="/" className="jobsBrand">
          DokoDetector
        </a>
        <button
          ref={toggleRef}
          aria-expanded={open}
          aria-controls="jobs-drawer"
          onClick={() => setOpen(!open)}
        >
          Jobs{" "}
          <span aria-label={`${activeCount} active jobs`}>{activeCount}</span>
        </button>
      </header>
      {open && (
        <button
          className="jobsScrim"
          aria-label="Close Jobs drawer"
          onClick={() => setOpen(false)}
        />
      )}
      <aside
        id="jobs-drawer"
        className="jobsDrawer"
        data-open={open}
        aria-label="Jobs"
        aria-hidden={!open}
      >
        <div className="jobsDrawerHeader">
          <h2>Jobs</h2>
          <button
            ref={closeRef}
            onClick={() => setOpen(false)}
            aria-label="Close Jobs drawer"
          >
            Close
          </button>
        </div>
        <p>
          {activeCount} active · {historyCount} recent
        </p>
        <nav aria-label="Job list">
          <button
            aria-pressed={tab === "active"}
            onClick={() => setTab("active")}
          >
            Active ({activeCount})
          </button>
          <button
            aria-pressed={tab === "history"}
            onClick={() => void showHistory()}
          >
            History
          </button>
        </nav>
        <label className="jobsFilter">
          Filter jobs
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </label>
        {(error || actionError) && (
          <p role="alert">
            {actionError ?? error}{" "}
            <button onClick={() => void refresh()}>Refresh</button>
          </p>
        )}
        {tab === "active" && jobs.length === 0 && !error && (
          <p role="status">No active jobs.</p>
        )}
        {tab === "history" && history.length === 0 && !actionError && (
          <p role="status">No recent jobs.</p>
        )}
        <ul className="jobsDrawerList">
          {visible.map((job) => {
            const children = jobs.filter(
              (candidate) => candidate.parent_id === job.id,
            );
            const groupIndex = groups.findIndex(
              (group) =>
                group.group_id === job.id ||
                group.child_job_ids.includes(job.id),
            );
            const groupId = groups[groupIndex]?.group_id;
            return (
              <li key={job.id}>
                {children.length > 0 && (
                  <button
                    aria-expanded={!!expanded[job.id]}
                    onClick={() =>
                      setExpanded({ ...expanded, [job.id]: !expanded[job.id] })
                    }
                  >
                    {expanded[job.id] ? "Hide" : "Show"} {children.length} child
                    jobs
                  </button>
                )}
                <a href={`/jobs/${encodeURIComponent(job.id)}`}>{job.label}</a>{" "}
                <JobStatus job={job} />
                <JobActions job={job} onChanged={() => void refresh()} />
                {tab === "active" && groupIndex >= 0 && groupId && (
                  <span>
                    <button
                      aria-label={`Move ${job.label} up`}
                      disabled={groupIndex === 0}
                      onClick={() =>
                        void move(
                          groupId,
                          groups[groupIndex - 1]?.group_id ?? null,
                        )
                      }
                    >
                      ↑
                    </button>
                    <button
                      aria-label={`Move ${job.label} down`}
                      disabled={groupIndex === groups.length - 1}
                      onClick={() =>
                        void move(
                          groupId,
                          groups[groupIndex + 2]?.group_id ?? null,
                        )
                      }
                    >
                      ↓
                    </button>
                  </span>
                )}
                {expanded[job.id] && (
                  <ul>
                    {children.map((child) => (
                      <li key={child.id}>
                        <a href={`/jobs/${encodeURIComponent(child.id)}`}>
                          {child.label}
                        </a>{" "}
                        <JobStatus job={child} />
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        {tab === "active" && jobs.length > 0 && !queue && (
          <button
            onClick={async () => {
              try {
                const data = await client.listJobs({
                  scope: "active",
                  limit: 100,
                });
                setQueue({
                  groups: data.groups,
                  revision: data.queue_revision,
                });
                setActionError(null);
              } catch {
                setActionError("Unable to load queue order.");
              }
            }}
          >
            Enable queue reordering
          </button>
        )}
      </aside>
    </>
  );
}
