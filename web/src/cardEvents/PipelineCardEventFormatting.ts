import type { PipelineCardEventType } from "./PipelineCardEventTypes";

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

export function eventTypeGuidance(type: PipelineCardEventType): string {
  return {
    card_state_changed:
      "A persistent card-related table-state change that justifies another table observation.",
    card_played: "A card reaches its final position in the trick area.",
    trick_cleared: "The cards from the completed trick leave the play area.",
    card_moved: "An existing card changes position without being played.",
    card_removed: "A card leaves the visible play area for another reason.",
    card_returned: "A card returns to a hand or another known area.",
    multiple_cards_dropped: "Several cards enter the play area together.",
    anomalous_state_change:
      "A visible state change does not match the other types.",
  }[type];
}
