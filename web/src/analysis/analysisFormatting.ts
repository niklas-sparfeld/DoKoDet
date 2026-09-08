import { ApiError, type RoundAnalysisTimeline } from "../api/client";

export type TimelineAction =
  RoundAnalysisTimeline["hypotheses"][number]["actions"][number];
export type TimelineHypothesis = RoundAnalysisTimeline["hypotheses"][number];
export type TimelineEvidenceRow = RoundAnalysisTimeline["rows"][number];
export type TimelineInferredPlay =
  RoundAnalysisTimeline["inferred_plays"][number];
type TimelineObservation = TimelineEvidenceRow["table_observation"];
export type TimelineCard = NonNullable<TimelineObservation["cards"]>[number];
export type TimelineCandidate = TimelineCard["identity_candidates"][number];
export type DisplayRow =
  | { kind: "evidence"; id: string; row: TimelineEvidenceRow }
  | { kind: "inferred"; id: string; play: TimelineInferredPlay };

export type GameplayPlay = { player: string; card: string };

export function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}

export function buildDisplayRows(
  rows: TimelineEvidenceRow[],
  inferredPlays: TimelineInferredPlay[],
): DisplayRow[] {
  const before = inferredPlays
    .filter((play) => play.position === "before")
    .sort(compareInferredPlays)
    .map((play) => ({
      kind: "inferred" as const,
      id: inferredRowId(play),
      play,
    }));
  const between = new Map<string, TimelineInferredPlay[]>();
  const after = inferredPlays
    .filter((play) => play.position === "after")
    .sort(compareInferredPlays);

  for (const play of inferredPlays) {
    if (
      play.position === "between" &&
      typeof play.before_observation_id === "string"
    ) {
      const plays = between.get(play.before_observation_id) ?? [];
      plays.push(play);
      between.set(play.before_observation_id, plays);
    }
  }

  return [
    ...before,
    ...rows.flatMap((row) => [
      { kind: "evidence" as const, id: row.observation_id, row },
      ...(between.get(row.observation_id) ?? [])
        .sort(compareInferredPlays)
        .map((play) => ({
          kind: "inferred" as const,
          id: inferredRowId(play),
          play,
        })),
    ]),
    ...after.map((play) => ({
      kind: "inferred" as const,
      id: inferredRowId(play),
      play,
    })),
  ];
}

export function actionsForObservation(
  hypothesis: TimelineHypothesis | undefined,
  observationId: string,
): TimelineAction[] {
  return (
    hypothesis?.actions.filter(
      (action) =>
        actionString(action, "observation_id") === observationId &&
        actionString(action, "kind") !== "inferred",
    ) ?? []
  );
}

export function actionsForInferredPlay(
  hypothesis: TimelineHypothesis | undefined,
  playIndex: number,
): TimelineAction[] {
  return (
    hypothesis?.actions.filter(
      (action) =>
        actionString(action, "kind") === "inferred" &&
        actionNumber(action, "play_index") === playIndex,
    ) ?? []
  );
}

export function actionKey(action: TimelineAction): string {
  return [
    actionString(action, "kind"),
    actionString(action, "observation_id"),
    actionString(action, "observed_card_id"),
    actionNumber(action, "play_index"),
  ]
    .filter((value) => value !== null)
    .join("-");
}

export function actionString(
  action: TimelineAction | null | undefined,
  key: string,
): string | null {
  const value = action?.[key];
  return typeof value === "string" ? value : null;
}

export function actionNumber(
  action: TimelineAction | null | undefined,
  key: string,
): number | null {
  const value = action?.[key];
  return typeof value === "number" ? value : null;
}

export function actionCounts(hypothesis: TimelineHypothesis): {
  selected: number;
  ignored: number;
  inferred: number;
} {
  type ActionCounts = { selected: number; ignored: number; inferred: number };
  return hypothesis.actions.reduce<ActionCounts>(
    (counts, action) => {
      const kind = actionString(action, "kind");
      if (kind === "selected") {
        counts.selected += 1;
      } else if (kind === "ignored") {
        counts.ignored += 1;
      } else if (kind === "inferred") {
        counts.inferred += 1;
      }
      return counts;
    },
    { selected: 0, ignored: 0, inferred: 0 },
  );
}

function inferredRowId(play: TimelineInferredPlay): string {
  return `inferred-${play.play_index}`;
}

function compareInferredPlays(
  left: TimelineInferredPlay,
  right: TimelineInferredPlay,
): number {
  return left.play_index - right.play_index;
}

export function actionDescription(action: TimelineAction): string {
  const kind = actionString(action, "kind");
  const playIndex = actionNumber(action, "play_index");
  const card = actionString(action, "card");
  const prefix = playIndex === null ? "Action" : `Play ${playIndex}`;
  if (kind === "ignored") {
    return `${prefix}: observed card ignored`;
  }
  if (kind === "inferred") {
    return `${prefix}: engine-inferred ${card === null ? "card play" : formatCardIdentity(card)}`;
  }
  return `${prefix}: ${card === null ? "selected card" : formatCardIdentity(card)}`;
}

export function statusExplanation(
  status: RoundAnalysisTimeline["reconstruction_status"],
): string {
  switch (status) {
    case "ambiguous":
      return "This result is ambiguous. Each retained hypothesis is one possible legal sequence; none is treated as truth.";
    case "incomplete":
      return "This result is incomplete. The available evidence does not provide enough card proposals for a complete legal sequence.";
    case "impossible":
      return "This result is impossible under the selected ruleset. No legal complete hypothesis survived replay.";
    default:
      return "This result contains a retained legal sequence. A hypothesis is an interpretation of the evidence, not ground truth.";
  }
}

export function gameplayPlayAt(
  hypothesis: TimelineHypothesis | undefined,
  playIndex: number,
): GameplayPlay | null {
  const plays = hypothesis?.gameplay["plays"];
  if (!Array.isArray(plays)) {
    return null;
  }
  const play = plays[playIndex - 1];
  if (!isRecord(play)) {
    return null;
  }
  const player = recordString(play, "player");
  const card = recordString(play, "card");
  return player === null || card === null ? null : { player, card };
}

export function formatAlternative(value: string): string {
  const separator = value.indexOf(":");
  return separator < 0
    ? formatIdentifier(value)
    : `${formatIdentifier(value.slice(0, separator))} · ${formatCardIdentity(value.slice(separator + 1))}`;
}

export function recordString(
  value: Record<string, unknown>,
  key: string,
): string | null {
  const item = value[key];
  return typeof item === "string" ? item : null;
}

export function recordNumber(
  value: Record<string, unknown>,
  key: string,
): number | null {
  const item = value[key];
  return typeof item === "number" ? item : null;
}

export function recordStringArray(
  value: Record<string, unknown>,
  key: string,
): string[] {
  const item = value[key];
  return Array.isArray(item) && item.every((entry) => typeof entry === "string")
    ? item
    : [];
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function formatDiagnosticValue(value: unknown): string {
  if (value === null) {
    return "None";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return formatJson(value).replaceAll("\n", " ");
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

export function reconstructionResultSnapshot(
  timeline: RoundAnalysisTimeline,
): Record<string, unknown> {
  return {
    schema_version: "round-reconstruction-result/v2",
    status: timeline.reconstruction_status,
    search: timeline.search,
    hypotheses: timeline.hypotheses,
    focused_decisions: timeline.focused_decisions,
    diagnostics: timeline.diagnostics,
  };
}

export function readInitialRowId(rows: DisplayRow[], fallback: string): string {
  const row = new URLSearchParams(window.location.search).get("row");
  return row !== null && rows.some((candidate) => candidate.id === row)
    ? row
    : fallback;
}

export function readInitialHypothesisRank(ranks: number[]): number | null {
  const requested = Number(
    new URLSearchParams(window.location.search).get("hypothesis"),
  );
  return Number.isInteger(requested) && ranks.includes(requested)
    ? requested
    : (ranks[0] ?? null);
}

export function writeSelection(rowId: string, hypothesisRank: number | null) {
  const params = new URLSearchParams(window.location.search);
  params.delete("row");
  params.delete("hypothesis");
  if (hypothesisRank !== null) {
    params.set("hypothesis", String(hypothesisRank));
  }
  if (rowId !== "") {
    params.set("row", rowId);
  }
  const query = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query === "" ? "" : `?${query}`}${window.location.hash}`,
  );
}

export function formatTrickProgress(
  hypothesis: TimelineHypothesis | undefined,
  row: DisplayRow | undefined,
): string {
  if (hypothesis === undefined) {
    return "—";
  }
  const plays = hypothesis.gameplay["plays"];
  const playCount = Array.isArray(plays) ? plays.length : 0;
  const currentPlay =
    row?.kind === "inferred"
      ? row.play.play_index
      : row?.kind === "evidence"
        ? Math.max(
            ...actionsForObservation(hypothesis, row.row.observation_id).map(
              (action) => actionNumber(action, "play_index") ?? 0,
            ),
            0,
          )
        : 0;
  const currentTrick = currentPlay === 0 ? 0 : Math.ceil(currentPlay / 4);
  const tricks = hypothesis.gameplay["tricks"];
  const trickCount = Math.max(
    Array.isArray(tricks) ? tricks.length : 0,
    Math.ceil(playCount / 4),
  );
  return currentTrick === 0
    ? `${trickCount} tricks · no play selected`
    : `Trick ${currentTrick} of ${trickCount} · play ${currentPlay} of ${playCount}`;
}

export function formatCardIdentity(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

export function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

export function formatMilliseconds(value: number): string {
  return `${(value / 1000).toFixed(3)} s`;
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatScore(value: number): string {
  return value.toFixed(3);
}
