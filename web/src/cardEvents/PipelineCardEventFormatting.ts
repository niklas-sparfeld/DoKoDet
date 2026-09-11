export function formatMicroseconds(value: number): string {
  const seconds = value / 1_000_000;
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(6).padStart(9, "0")}`;
}

export function formatDuration(value: number): string {
  const seconds = Math.floor(value / 1_000_000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}
