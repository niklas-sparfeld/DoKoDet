export function analysisPath(recordingId: string, analysisId: string): string {
  return `/recordings/${encodeURIComponent(recordingId)}/pipeline/round_analyses?analysis=${encodeURIComponent(analysisId)}`;
}
