import type { EditableFrame, PendingCommand } from "./PipelineVisibleCardTypes";

export function formatFrameTime(frame: EditableFrame): string {
  return formatMicroseconds(
    frame.outcome.frame_identity?.requested_time_us ?? 0,
  );
}

export function formatFrameState(frame: EditableFrame): string {
  return `${formatIdentifier(frame.outcome.status)} · ${formatIdentifier(frame.reviewState)}`;
}

export function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)} s`;
}

export function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

export function describeCommand(command: PendingCommand | undefined): string {
  return command === undefined
    ? "none"
    : `${formatIdentifier(command.operation.operation)} ${command.operation.item_id ?? "frame"}`;
}
