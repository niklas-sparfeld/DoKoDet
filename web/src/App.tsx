import { RecordingDetailView, RecordingListView } from "./recordings";
import { VisibleCardReviewPage } from "./visibleCardReview";

export function App() {
  const visibleCardBatchId = readVisibleCardBatchId(window.location.pathname);
  const recordingId = readRecordingId(window.location.pathname);
  const selectedAnalysisId = readSelectedAnalysisId(window.location.search);
  if (visibleCardBatchId !== null) {
    return (
      <VisibleCardReviewPage
        batchId={visibleCardBatchId}
        selectedItemId={readSelectedVisibleCardItem(window.location.search)}
      />
    );
  }
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

function readVisibleCardBatchId(pathname: string): string | null {
  const match = pathname.match(/^\/visible-card-reviews\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}

function readRecordingId(pathname: string): string | null {
  const match = pathname.match(/^\/recordings\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}

function readSelectedAnalysisId(search: string): string | null {
  const analysisId = new URLSearchParams(search).get("analysis");
  return analysisId === null || analysisId === "" ? null : analysisId;
}

function readSelectedVisibleCardItem(search: string): string | null {
  const itemId = new URLSearchParams(search).get("item");
  return itemId === null || itemId === "" ? null : itemId;
}
