import { useEffect, useState } from "react";

import { RecordingDetailView, RecordingListView } from "./recordings";
import { FrameReviewQueueView } from "./frameReview/FrameReviewQueueView";
import { readRecordingPipelineRoute } from "./pipeline/recordingPipelineUrl";
import { JobStateProvider } from "./jobs/JobState";
import { JobDetailView } from "./jobs/JobDetailView";
import { JobListView } from "./jobs/JobListView";

export function App() {
  return (
    <JobStateProvider>
      <AppRoutes />
    </JobStateProvider>
  );
}

function AppRoutes() {
  const location = useAppLocation();
  const jobRoute = location.pathname.match(/^\/jobs\/([^/]+)\/?$/);
  if (jobRoute)
    return (
      <JobDetailView
        key={jobRoute[1]}
        jobId={decodeURIComponent(jobRoute[1])}
      />
    );
  if (location.pathname === "/jobs" || location.pathname === "/jobs/")
    return <JobListView />;
  if (location.pathname === "/frame-reviews/0096-M4") {
    return <FrameReviewQueueView />;
  }
  const pipelineRoute = readRecordingPipelineRoute(location.pathname);
  const recordingId =
    pipelineRoute?.recordingId ?? readRecordingId(location.pathname);
  return recordingId === null ? (
    <RecordingListView />
  ) : (
    <RecordingDetailView
      key={`${recordingId}:${pipelineRoute?.compare ? "compare" : ""}`}
      recordingId={recordingId}
      pipelineStage={pipelineRoute?.stage ?? null}
      pipelineCompare={pipelineRoute?.compare ?? false}
    />
  );
}

function useAppLocation() {
  const [location, setLocation] = useState(() => ({
    pathname: window.location.pathname,
    search: window.location.search,
  }));

  useEffect(() => {
    const update = () =>
      setLocation({
        pathname: window.location.pathname,
        search: window.location.search,
      });
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  return location;
}

function readRecordingId(pathname: string): string | null {
  const match = pathname.match(/^\/recordings\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}
