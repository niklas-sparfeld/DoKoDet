export function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

export function formatPipelineStageState(state: string): string {
  switch (state) {
    case "video-only":
    case "empty":
      return "No processor output";
    case "active-run":
      return "Processor running";
    case "data-available":
      return "Data available";
    case "complete":
      return "Complete";
    case "partial":
      return "Partial output";
    case "failed":
      return "Processor failed";
    default:
      return formatIdentifier(state);
  }
}

export function formatDuration(durationUs: number): string {
  const totalSeconds = Math.floor(durationUs / 1_000_000);
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, "0")}`;
}

export function formatByteLength(value: number): string {
  if (value < 1_000) return `${value} B`;
  if (value < 1_000_000) return `${(value / 1_000).toFixed(1)} kB`;
  if (value < 1_000_000_000) return `${(value / 1_000_000).toFixed(1)} MB`;
  return `${(value / 1_000_000_000).toFixed(1)} GB`;
}

export function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)}s`;
}
