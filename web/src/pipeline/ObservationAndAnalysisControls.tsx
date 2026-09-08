import { RecordingAnalysisView } from "../analysis/AnalysisView";
import {
  ObservationRunControls,
  type ObservationRunControlsProps,
} from "./ObservationRunControls";
import {
  RoundAnalysisControls,
  type RoundAnalysisControlsProps,
} from "./RoundAnalysisControls";
import { analysisPath } from "./roundAnalysisUrl";

export { ObservationRunControls, RoundAnalysisControls, analysisPath };
export type { ObservationRunControlsProps, RoundAnalysisControlsProps };

export function SelectedAnalysisTimeline({
  analysisId,
  recordingId,
}: {
  analysisId: string | null;
  recordingId: string;
}) {
  return analysisId === null ? null : (
    <RecordingAnalysisView analysisId={analysisId} recordingId={recordingId} />
  );
}
