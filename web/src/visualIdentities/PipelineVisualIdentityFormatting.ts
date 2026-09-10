import type { PendingCommand } from "./PipelineVisualIdentityTypes";

export function formatIdentifier(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

const CARD_IDENTITIES: Record<string, string> = {
  CLUBS_ACE: "♣ Ass",
  CLUBS_NINE: "♣ Neun",
  CLUBS_TEN: "♣ Zehn",
  CLUBS_JACK: "♣ Bube",
  CLUBS_QUEEN: "♣ Dame",
  CLUBS_KING: "♣ König",
  DIAMONDS_ACE: "♦ Ass",
  DIAMONDS_NINE: "♦ Neun",
  DIAMONDS_TEN: "♦ Zehn",
  DIAMONDS_JACK: "♦ Bube",
  DIAMONDS_QUEEN: "♦ Dame",
  DIAMONDS_KING: "♦ König",
  HEARTS_ACE: "♥ Ass",
  HEARTS_NINE: "♥ Neun",
  HEARTS_TEN: "♥ Zehn",
  HEARTS_JACK: "♥ Bube",
  HEARTS_QUEEN: "♥ Dame",
  HEARTS_KING: "♥ König",
  SPADES_ACE: "♠ Ass",
  SPADES_NINE: "♠ Neun",
  SPADES_TEN: "♠ Zehn",
  SPADES_JACK: "♠ Bube",
  SPADES_QUEEN: "♠ Dame",
  SPADES_KING: "♠ König",
};

export function formatCardIdentity(value: string): string {
  return CARD_IDENTITIES[value] ?? formatIdentifier(value);
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
