import type { PendingCommand } from "./PipelineVisualIdentityTypes";

export function formatIdentifier(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

export function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)} s`;
}

export function formatScore(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function describeCommand(command: PendingCommand): string {
  return `${command.operation.operation}${command.operation.item_id === undefined ? "" : ` (${command.operation.item_id})`}`;
}
