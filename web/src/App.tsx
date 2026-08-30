import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type RoundAnalysisStatus,
  type RoundAnalysisTimeline,
} from "./api/client";
import styles from "./App.module.css";

type TimelineAction =
  RoundAnalysisTimeline["hypotheses"][number]["actions"][number];
type TimelineEvidenceRow = RoundAnalysisTimeline["rows"][number];
type TimelineInferredPlay = RoundAnalysisTimeline["inferred_plays"][number];

type DisplayRow =
  | { kind: "evidence"; id: string; row: TimelineEvidenceRow }
  | { kind: "inferred"; id: string; play: TimelineInferredPlay };

export function App() {
  const analysisId = readAnalysisId(window.location.pathname);

  if (analysisId === null) {
    return (
      <main className={styles.shell}>
        <p className={styles.eyebrow}>DokoDetector</p>
        <h1>Round analysis timeline</h1>
        <p className={styles.description}>
          Open an analysis with its ID to inspect the immutable analysis
          timeline.
        </p>
      </main>
    );
  }

  return <AnalysisSmokeView key={analysisId} analysisId={analysisId} />;
}

function AnalysisSmokeView({ analysisId }: { analysisId: string }) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [status, setStatus] = useState<RoundAnalysisStatus | null>(null);
  const [timeline, setTimeline] = useState<RoundAnalysisTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    void client
      .getRoundAnalysisStatus(analysisId, { signal: controller.signal })
      .then((nextStatus) => {
        if (controller.signal.aborted) {
          return;
        }
        setStatus(nextStatus);
        if (nextStatus.state !== "complete") {
          return;
        }
        return client
          .getRoundAnalysisTimeline(analysisId, { signal: controller.signal })
          .then((nextTimeline) => {
            if (!controller.signal.aborted) {
              setTimeline(nextTimeline);
            }
          });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(reason));
        }
      });

    return () => controller.abort();
  }, [analysisId, client]);

  return (
    <main className={styles.shell}>
      {error !== null ? (
        <section className={styles.panel} aria-live="polite">
          <p className={styles.statusLabel}>Unable to load analysis</p>
          <p>{error}</p>
        </section>
      ) : status === null ? (
        <p className={styles.loading} aria-live="polite">
          Loading analysis…
        </p>
      ) : (
        <AnalysisStatus status={status} timeline={timeline} />
      )}
    </main>
  );
}

function AnalysisStatus({
  status,
  timeline,
}: {
  status: RoundAnalysisStatus;
  timeline: RoundAnalysisTimeline | null;
}) {
  if (timeline === null) {
    return (
      <section className={styles.panel} aria-live="polite">
        <div className={styles.statusHeading}>
          <div>
            <p className={styles.eyebrow}>DokoDetector · Round analysis</p>
            <h1>Analysis status</h1>
          </div>
          <StatusBadge value={status.state} />
        </div>
        <dl className={styles.stats}>
          <Stat label="Round" value={status.round_id} />
          <Stat
            label="Evidence packages"
            value={`${status.completed_evidence_packages}/${status.total_evidence_packages}`}
          />
        </dl>
        <p className={styles.description}>The timeline is not available yet.</p>
      </section>
    );
  }

  return <ResolvedTimeline timeline={timeline} />;
}

function ResolvedTimeline({ timeline }: { timeline: RoundAnalysisTimeline }) {
  const displayRows = useMemo(
    () => buildDisplayRows(timeline.rows, timeline.inferred_plays),
    [timeline.inferred_plays, timeline.rows],
  );
  const hypothesisRanks = timeline.hypotheses.map(
    (hypothesis) => hypothesis.rank,
  );
  const firstRowId = displayRows[0]?.id ?? "";
  const [selectedRowId, setSelectedRowId] = useState(() =>
    readInitialRowId(displayRows, firstRowId),
  );
  const [selectedHypothesisRank, setSelectedHypothesisRank] = useState(() =>
    readInitialHypothesisRank(hypothesisRanks),
  );
  const selectedHypothesis =
    timeline.hypotheses.find(
      (hypothesis) => hypothesis.rank === selectedHypothesisRank,
    ) ?? timeline.hypotheses[0];
  const requestedRowIndex = displayRows.findIndex(
    (row) => row.id === selectedRowId,
  );
  const selectedRowIndex = requestedRowIndex < 0 ? 0 : requestedRowIndex;
  const selectedRow = displayRows[selectedRowIndex];

  function selectRow(rowId: string) {
    setSelectedRowId(rowId);
    writeSelection(rowId, selectedHypothesis?.rank ?? null);
  }

  function selectHypothesis(rank: number) {
    setSelectedHypothesisRank(rank);
    writeSelection(selectedRow?.id ?? firstRowId, rank);
  }

  function moveRow(nextIndex: number) {
    const boundedIndex = Math.min(
      Math.max(nextIndex, 0),
      Math.max(displayRows.length - 1, 0),
    );
    const nextRow = displayRows[boundedIndex];
    if (nextRow !== undefined) {
      selectRow(nextRow.id);
    }
  }

  return (
    <div className={styles.analysisPage}>
      <header className={styles.analysisHeader}>
        <div>
          <p className={styles.eyebrow}>DokoDetector · Round analysis</p>
          <h1>Round analysis timeline</h1>
          <p className={styles.analysisId}>
            <span>Analysis ID</span> {timeline.analysis_id}
          </p>
          <p className={styles.analysisContext}>
            Round {timeline.round_id} · Recording {timeline.recording_id}
          </p>
        </div>
        <div className={styles.hypothesisControl}>
          <label htmlFor="hypothesis-select">Hypothesis</label>
          <select
            id="hypothesis-select"
            value={selectedHypothesis?.rank ?? ""}
            onChange={(event) => selectHypothesis(Number(event.target.value))}
            disabled={timeline.hypotheses.length === 0}
          >
            {timeline.hypotheses.length === 0 ? (
              <option value="">No retained hypotheses</option>
            ) : (
              timeline.hypotheses.map((hypothesis) => (
                <option key={hypothesis.rank} value={hypothesis.rank}>
                  Rank {hypothesis.rank} · {formatScore(hypothesis.total_score)}
                </option>
              ))
            )}
          </select>
        </div>
      </header>

      <section className={styles.summary} aria-label="Analysis summary">
        <div className={styles.summaryStatus}>
          <span className={styles.statusLabel}>Reconstruction status</span>
          <StatusBadge value={timeline.reconstruction_status} />
        </div>
        <dl className={styles.summaryStats}>
          <Stat
            label="Selected hypothesis"
            value={
              selectedHypothesis === undefined
                ? "None retained"
                : `Rank ${selectedHypothesis.rank}`
            }
          />
          <Stat
            label="Score"
            value={
              selectedHypothesis === undefined
                ? "—"
                : formatScore(selectedHypothesis.total_score)
            }
          />
          <Stat
            label="Trick progress"
            value={formatTrickProgress(selectedHypothesis, selectedRow)}
          />
          <Stat label="Rows" value={String(displayRows.length)} />
        </dl>
        {timeline.warnings.length > 0 ? (
          <ul className={styles.warningList} aria-label="Analysis warnings">
            {timeline.warnings.map((warning) => (
              <li key={warning.code}>
                <span aria-hidden="true">!</span> {warning.message}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <div className={styles.rowControls} aria-label="Row navigation">
        <button
          type="button"
          onClick={() => moveRow(selectedRowIndex - 1)}
          disabled={selectedRowIndex <= 0}
        >
          ← Previous row
        </button>
        <span>
          Row {displayRows.length === 0 ? 0 : selectedRowIndex + 1} of{" "}
          {displayRows.length}
        </span>
        <button
          type="button"
          onClick={() => moveRow(selectedRowIndex + 1)}
          disabled={selectedRowIndex >= displayRows.length - 1}
        >
          Next row →
        </button>
      </div>

      <div className={styles.timelineHeader}>
        <h2>Evidence</h2>
        <h2>Table observation</h2>
        <h2>Reconstruction hypothesis</h2>
      </div>
      <ol
        className={styles.timeline}
        aria-label="Synchronized round timeline"
        role="listbox"
      >
        {displayRows.map((row, index) => (
          <TimelineRowView
            key={row.id}
            row={row}
            index={index}
            selected={row.id === selectedRow?.id}
            hypothesis={selectedHypothesis}
            onSelect={() => selectRow(row.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                moveRow(index + 1);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                moveRow(index - 1);
              } else if (event.key === "Home") {
                event.preventDefault();
                moveRow(0);
              } else if (event.key === "End") {
                event.preventDefault();
                moveRow(displayRows.length - 1);
              }
            }}
          />
        ))}
      </ol>
      {displayRows.length === 0 ? (
        <p className={styles.emptyState}>No evidence rows are available.</p>
      ) : null}
      <p className={styles.keyboardHint}>
        Select a row, then use ↑ and ↓ to move through the timeline.
      </p>
      <span className={styles.visuallyHidden} aria-live="polite">
        {selectedRow === undefined
          ? "No row selected"
          : `Selected ${selectedRow.id}`}
      </span>
    </div>
  );
}

function TimelineRowView({
  row,
  index,
  selected,
  hypothesis,
  onSelect,
  onKeyDown,
}: {
  row: DisplayRow;
  index: number;
  selected: boolean;
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined;
  onSelect: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <li>
      <button
        type="button"
        className={`${styles.timelineRow} ${selected ? styles.selectedRow : ""}`}
        aria-label={`${row.id} timeline row`}
        aria-selected={selected}
        role="option"
        tabIndex={selected ? 0 : -1}
        onClick={onSelect}
        onKeyDown={onKeyDown}
      >
        {row.kind === "evidence" ? (
          <EvidenceCell row={row.row} />
        ) : (
          <InferenceEvidenceCell play={row.play} />
        )}
        {row.kind === "evidence" ? (
          <ObservationCell observation={row.row.table_observation} />
        ) : (
          <InferenceObservationCell />
        )}
        {row.kind === "evidence" ? (
          <InterpretationCell
            actions={actionsForObservation(hypothesis, row.row.observation_id)}
          />
        ) : (
          <InterpretationCell
            actions={actionsForInferredPlay(hypothesis, row.play.play_index)}
          />
        )}
      </button>
      <span className={styles.visuallyHidden}>
        Timeline position {index + 1}
      </span>
    </li>
  );
}

function EvidenceCell({ row }: { row: TimelineEvidenceRow }) {
  return (
    <div className={styles.cell}>
      <div className={styles.cellEyebrow}>
        Event {row.event_sequence} · {formatMilliseconds(row.event_time_ms)}
      </div>
      {row.central_frame === null ? (
        <div className={styles.missingFrame}>No central frame available</div>
      ) : (
        <img
          className={styles.frame}
          src={row.central_frame.url}
          alt={`Evidence frame for event ${row.event_sequence}`}
          loading="lazy"
        />
      )}
      <dl className={styles.cellMeta}>
        <div>
          <dt>Observation</dt>
          <dd>{row.observation_id}</dd>
        </div>
        <div>
          <dt>Package</dt>
          <dd>{row.package_id}</dd>
        </div>
      </dl>
    </div>
  );
}

function InferenceEvidenceCell({ play }: { play: TimelineInferredPlay }) {
  return (
    <div className={`${styles.cell} ${styles.inferredCell}`}>
      <span className={styles.actionBadge} data-kind="inferred">
        Inferred
      </span>
      <strong>Engine inference</strong>
      <p>No source evidence for play {play.play_index}.</p>
    </div>
  );
}

function ObservationCell({
  observation,
}: {
  observation: TimelineEvidenceRow["table_observation"];
}) {
  const cards = observation.cards ?? [];

  return (
    <div className={styles.cell}>
      <div className={styles.observationStatus}>
        <span className={styles.actionBadge} data-kind={observation.status}>
          {observation.status === "observed"
            ? "Observed"
            : "Insufficient evidence"}
        </span>
        <span>
          {observation.analyzer.name} · {observation.analyzer.version}
        </span>
      </div>
      <p className={styles.observationMeta}>
        {formatIdentifier(observation.calibration)} calibration ·{" "}
        {observation.capabilities.length} capability
        {observation.capabilities.length === 1 ? "" : "ies"}
      </p>
      {cards.length === 0 ? (
        <p className={styles.emptyState}>No observed cards.</p>
      ) : (
        <div className={styles.cardList}>
          {cards.map((card) => (
            <div className={styles.observedCard} key={card.observed_card_id}>
              <span className={styles.cardId}>{card.observed_card_id}</span>
              {card.identity_candidates.map((candidate) => (
                <div className={styles.confidence} key={candidate.card}>
                  <div className={styles.confidenceHeading}>
                    <span>{formatCardIdentity(candidate.card)}</span>
                    <span>{formatPercent(candidate.probability)}</span>
                  </div>
                  <progress
                    value={candidate.probability}
                    max={1}
                    aria-label={`${formatCardIdentity(candidate.card)} confidence`}
                  />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InferenceObservationCell() {
  return (
    <div className={`${styles.cell} ${styles.inferredCell}`}>
      <span className={styles.mutedLabel}>No table observation</span>
      <p>This row is supplied by the game engine between evidence rows.</p>
    </div>
  );
}

function InterpretationCell({ actions }: { actions: TimelineAction[] }) {
  return (
    <div className={styles.cell}>
      {actions.length === 0 ? (
        <p className={styles.emptyState}>No hypothesis action for this row.</p>
      ) : (
        <div className={styles.actionList}>
          {actions.map((action, index) => (
            <ActionView key={`${actionKey(action)}-${index}`} action={action} />
          ))}
        </div>
      )}
    </div>
  );
}

function ActionView({ action }: { action: TimelineAction }) {
  const kind = actionString(action, "kind");
  const card = actionString(action, "card");
  const player = actionString(action, "player");
  const playIndex = actionNumber(action, "play_index");
  const scoreContribution = actionNumber(action, "score_contribution");
  const probability = actionNumber(action, "candidate_probability");

  return (
    <div className={styles.action}>
      <div className={styles.actionHeading}>
        <span className={styles.actionBadge} data-kind={kind ?? "unknown"}>
          {kind ?? "Unknown"}
        </span>
        {playIndex === null ? null : <span>Play {playIndex}</span>}
      </div>
      {card === null ? (
        <strong>Observed card ignored</strong>
      ) : (
        <strong>
          {formatCardIdentity(card)} ·{" "}
          {player === null ? "Unknown player" : formatIdentifier(player)}
        </strong>
      )}
      <div className={styles.actionMeta}>
        {probability === null ? null : (
          <span>{formatPercent(probability)} candidate</span>
        )}
        {scoreContribution === null ? null : (
          <span>{formatScore(scoreContribution)} score contribution</span>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}

function buildDisplayRows(
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

function actionsForObservation(
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined,
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

function actionsForInferredPlay(
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined,
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

function actionKey(action: TimelineAction): string {
  return [
    actionString(action, "kind"),
    actionString(action, "observation_id"),
    actionString(action, "observed_card_id"),
    actionNumber(action, "play_index"),
  ]
    .filter((value) => value !== null)
    .join("-");
}

function actionString(action: TimelineAction, key: string): string | null {
  const value = action[key];
  return typeof value === "string" ? value : null;
}

function actionNumber(action: TimelineAction, key: string): number | null {
  const value = action[key];
  return typeof value === "number" ? value : null;
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

function readInitialRowId(rows: DisplayRow[], fallback: string): string {
  const row = new URLSearchParams(window.location.search).get("row");
  return row !== null && rows.some((candidate) => candidate.id === row)
    ? row
    : fallback;
}

function readInitialHypothesisRank(ranks: number[]): number | null {
  const requested = Number(
    new URLSearchParams(window.location.search).get("hypothesis"),
  );
  return Number.isInteger(requested) && ranks.includes(requested)
    ? requested
    : (ranks[0] ?? null);
}

function writeSelection(rowId: string, hypothesisRank: number | null) {
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

function formatTrickProgress(
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined,
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

function formatCardIdentity(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function formatMilliseconds(value: number): string {
  return `${(value / 1000).toFixed(3)} s`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatScore(value: number): string {
  return value.toFixed(3);
}

function readAnalysisId(pathname: string): string | null {
  const match = pathname.match(/^\/round-analyses\/([^/]+)\/?$/);
  return match === null ? null : decodeURIComponent(match[1]);
}

function describeError(reason: unknown): string {
  if (reason instanceof ApiError) {
    return `The backend returned HTTP ${reason.status}.`;
  }
  return "The backend could not be reached.";
}
