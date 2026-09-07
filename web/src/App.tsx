import { useEffect, useState } from "react";

import { RecordingDetailView, RecordingListView } from "./recordings";
import { readRecordingPipelineRoute } from "./pipeline/recordingPipelineUrl";

export function App() {
  const location = useAppLocation();
  const pipelineRoute = readRecordingPipelineRoute(location.pathname);
  const recordingId =
    pipelineRoute?.recordingId ?? readRecordingId(location.pathname);
  return recordingId === null ? (
    <RecordingListView />
  ) : (
    <RecordingDetailView
      key={`${recordingId}:${pipelineRoute?.stage ?? ""}:${pipelineRoute?.compare ? "compare" : ""}`}
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
