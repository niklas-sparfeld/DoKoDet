import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  createDokoDetectorClient,
  type JobDetail,
  type JobListResponse,
} from "../api/client";

type JobStateValue = {
  jobs: JobDetail[];
  nextCursor: string | null;
  loading: boolean;
  error: string | null;
  refresh: (signal?: AbortSignal) => Promise<void>;
  loadMore: (signal?: AbortSignal) => Promise<void>;
  getJob: (id: string, signal?: AbortSignal) => Promise<JobDetail>;
  client: ReturnType<typeof createDokoDetectorClient>;
};
const JobState = createContext<JobStateValue | null>(null);

export function JobStateProvider({ children }: { children: React.ReactNode }) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [page, setPage] = useState<JobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latestRequest = useRef(0);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const requestId = ++latestRequest.current;
      try {
        const result = await client.listJobs({
          scope: "active",
          limit: 50,
          signal,
        });
        if (!signal?.aborted && requestId === latestRequest.current) {
          setPage(result);
          setError(null);
        }
      } catch {
        if (!signal?.aborted && requestId === latestRequest.current)
          setError("Unable to load jobs. Check the connection and try again.");
      } finally {
        if (!signal?.aborted && requestId === latestRequest.current)
          setLoading(false);
      }
    },
    [client],
  );
  const loadMore = useCallback(
    async (signal?: AbortSignal) => {
      if (!page?.next_cursor) return;
      const result = await client.listJobs({
        scope: "active",
        cursor: page.next_cursor,
        limit: 50,
        signal,
      });
      if (!signal?.aborted)
        setPage((current) =>
          current
            ? { ...result, items: [...current.items, ...result.items] }
            : result,
        );
    },
    [client, page],
  );
  const getJob = useCallback(
    (id: string, signal?: AbortSignal) => client.getJob(id, { signal }),
    [client],
  );
  useEffect(() => {
    let timer = 0;
    let disposed = false;
    let controller: AbortController | undefined;
    const poll = async () => {
      if (disposed || document.visibilityState !== "visible") return;
      controller = new AbortController();
      await refresh(controller.signal);
      controller = undefined;
      if (!disposed && document.visibilityState === "visible")
        timer = window.setTimeout(poll, 2000);
    };
    const visible = () => {
      if (document.visibilityState === "visible") {
        window.clearTimeout(timer);
        void poll();
      } else {
        window.clearTimeout(timer);
        controller?.abort();
      }
    };
    void poll();
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);
  const value = useMemo(
    () => ({
      jobs: page?.items ?? [],
      nextCursor: page?.next_cursor ?? null,
      loading,
      error,
      refresh,
      loadMore,
      getJob,
      client,
    }),
    [page, loading, error, refresh, loadMore, getJob, client],
  );
  return <JobState.Provider value={value}>{children}</JobState.Provider>;
}

export function useJobState() {
  const value = useContext(JobState);
  if (!value) throw new Error("JobStateProvider is required.");
  return value;
}

export function isActiveJob(state: JobDetail["state"]) {
  return ["queued", "running", "waiting", "cancelling"].includes(state);
}
