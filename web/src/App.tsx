import { useEffect, useState } from "react";

import { RecordingDetailView, RecordingListView } from "./recordings";
import { FrameReviewQueueView } from "./frameReview/FrameReviewQueueView";
import { RecordingEventSetPage } from "./pipeline/RecordingEventSetPage";
import { readRecordingPipelineRoute } from "./pipeline/recordingPipelineUrl";
import { JobStateProvider } from "./jobs/JobState";
import { JobDetailView } from "./jobs/JobDetailView";
import { JobListView } from "./jobs/JobListView";
import { JobsDrawer } from "./jobs/JobsDrawer";
import "./jobs/jobs.css";

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
  const eventSetRoute = location.pathname.match(
    /^\/recordings\/([^/]+)\/event-sets\/?$/,
  );
  let page: React.ReactNode;
  if (jobRoute) {
    page = (
      <JobDetailView
        key={jobRoute[1]}
        jobId={decodeURIComponent(jobRoute[1])}
      />
    );
  } else if (location.pathname === "/jobs" || location.pathname === "/jobs/") {
    page = <JobListView />;
  } else if (location.pathname === "/frame-reviews/0096-M4") {
    page = <FrameReviewQueueView />;
  } else if (eventSetRoute) {
    page = (
      <RecordingEventSetPage
        recordingId={decodeURIComponent(eventSetRoute[1])}
      />
    );
  } else {
    const pipelineRoute = readRecordingPipelineRoute(location.pathname);
    const recordingId =
      pipelineRoute?.recordingId ?? readRecordingId(location.pathname);
    page =
      recordingId === null ? (
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
  return (
    <>
      <JobsDrawer />
      <div className="jobsAppContent">{page}</div>
    </>
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
