import { RecordingDetailView, RecordingListView } from "./recordings";

export function App() {
  const recordingId = readRecordingId(window.location.pathname);
  const selectedAnalysisId = readSelectedAnalysisId(window.location.search);
  return recordingId === null ? (
    <RecordingListView />
  ) : (
    <RecordingDetailView
      key={`${recordingId}:${selectedAnalysisId ?? ""}`}
      recordingId={recordingId}
      selectedAnalysisId={selectedAnalysisId}
    />
  );
}

function readRecordingId(pathname: string): string | null {
  const match = pathname.match(/^\/recordings\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}

function readSelectedAnalysisId(search: string): string | null {
  const analysisId = new URLSearchParams(search).get("analysis");
  return analysisId === null || analysisId === "" ? null : analysisId;
}
