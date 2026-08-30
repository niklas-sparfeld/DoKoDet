import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type RoundCounterfactualCreateRequest,
  type RoundCounterfactualResponse,
  type RoundAnalysisStatus,
  type RoundAnalysisTimeline,
} from "./api/client";
import styles from "./App.module.css";

type TimelineAction =
  RoundAnalysisTimeline["hypotheses"][number]["actions"][number];
type TimelineHypothesis = RoundAnalysisTimeline["hypotheses"][number];
type TimelineEvidenceRow = RoundAnalysisTimeline["rows"][number];
type TimelineInferredPlay = RoundAnalysisTimeline["inferred_plays"][number];
type GameplayPlay = { player: string; card: string };
type TimelineObservation = TimelineEvidenceRow["table_observation"];
type TimelineCard = NonNullable<TimelineObservation["cards"]>[number];
type TimelineCandidate = TimelineCard["identity_candidates"][number];
type CounterfactualObservedCard = NonNullable<
  RoundCounterfactualCreateRequest["excluded_observed_cards"]
>[number];
type CounterfactualOverride = NonNullable<
  RoundCounterfactualCreateRequest["candidate_probability_overrides"]
>[number];

type CounterfactualSnapshot = {
  status: "resolved" | "ambiguous" | "incomplete" | "impossible";
  search: Record<string, unknown>;
  hypotheses: TimelineHypothesis[];
  focused_decisions: Record<string, unknown>[];
  diagnostics: Record<string, unknown>;
};

type GameplayChange = {
  playIndex: number;
  kind: "Inserted" | "Removed" | "Changed";
  baseline: GameplayPlay | null;
  derived: GameplayPlay | null;
};

type ActionChange = {
  key: string;
  baseline: TimelineAction | null;
  derived: TimelineAction | null;
};

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
                <span aria-hidden="true">!</span>{" "}
                <span className={styles.warningCode}>
                  {formatIdentifier(warning.code)}:
                </span>{" "}
                {warning.message}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <AnalysisExplanation
        timeline={timeline}
        selectedHypothesis={selectedHypothesis}
        selectedRow={selectedRow}
        onSelectRow={selectRow}
        onSelectHypothesis={selectHypothesis}
      />

      <CounterfactualWorkbench timeline={timeline}>
        {(counterfactual) => (
          <>
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
                  counterfactual={counterfactual}
                  onSelect={() => selectRow(row.id)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) {
                      return;
                    }
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
              <p className={styles.emptyState}>
                No evidence rows are available.
              </p>
            ) : null}
            <p className={styles.keyboardHint}>
              Select a row, then use ↑ and ↓ to move through the timeline.
            </p>
            <span className={styles.visuallyHidden} aria-live="polite">
              {selectedRow === undefined
                ? "No row selected"
                : `Selected ${selectedRow.id}`}
            </span>

            <CounterfactualRunControls counterfactual={counterfactual} />
            {counterfactual.response !== null ? (
              <CounterfactualComparison
                response={counterfactual.response}
                timeline={timeline}
              />
            ) : null}
          </>
        )}
      </CounterfactualWorkbench>
    </div>
  );
}

function counterfactualReferenceKey(
  reference: Pick<
    CounterfactualObservedCard,
    "observation_id" | "observed_card_id"
  >,
): string {
  return `${reference.observation_id}:${reference.observed_card_id}`;
}

function findCandidate(
  timeline: RoundAnalysisTimeline,
  override: CounterfactualOverride,
): TimelineCandidate | null {
  for (const row of timeline.rows) {
    if (row.observation_id !== override.observation_id) {
      continue;
    }
    for (const card of row.table_observation.cards ?? []) {
      if (card.observed_card_id !== override.observed_card_id) {
        continue;
      }
      return (
        card.identity_candidates.find(
          (candidate) => candidate.card === override.card,
        ) ?? null
      );
    }
  }
  return null;
}

function snapshotFromTimeline(
  timeline: RoundAnalysisTimeline,
): CounterfactualSnapshot {
  return {
    status: timeline.reconstruction_status,
    search: timeline.search,
    hypotheses: timeline.hypotheses,
    focused_decisions: timeline.focused_decisions,
    diagnostics: timeline.diagnostics,
  };
}

function parseCounterfactualSnapshot(
  value: Record<string, unknown>,
): CounterfactualSnapshot | null {
  const status = value.status;
  const hypotheses = value.hypotheses;
  const focusedDecisions = value.focused_decisions;
  if (
    (status !== "resolved" &&
      status !== "ambiguous" &&
      status !== "incomplete" &&
      status !== "impossible") ||
    !Array.isArray(hypotheses) ||
    !hypotheses.every(isRecord) ||
    !Array.isArray(focusedDecisions) ||
    !focusedDecisions.every(isRecord)
  ) {
    return null;
  }
  return {
    status,
    search: isRecord(value.search) ? value.search : {},
    hypotheses: hypotheses as TimelineHypothesis[],
    focused_decisions: focusedDecisions,
    diagnostics: isRecord(value.diagnostics) ? value.diagnostics : {},
  };
}

function bestHypothesis(
  hypotheses: TimelineHypothesis[],
): TimelineHypothesis | undefined {
  return (
    hypotheses.find((hypothesis) => hypothesis.rank === 1) ?? hypotheses[0]
  );
}

function compareGameplay(
  baseline: TimelineHypothesis | undefined,
  derived: TimelineHypothesis | undefined,
): GameplayChange[] {
  const baselinePlays = Array.isArray(baseline?.gameplay["plays"])
    ? baseline.gameplay["plays"]
    : [];
  const derivedPlays = Array.isArray(derived?.gameplay["plays"])
    ? derived.gameplay["plays"]
    : [];
  const playCount = Math.max(baselinePlays.length, derivedPlays.length);
  const changes: GameplayChange[] = [];
  for (let index = 1; index <= playCount; index += 1) {
    const baselinePlay = gameplayPlayAt(baseline, index);
    const derivedPlay = gameplayPlayAt(derived, index);
    if (baselinePlay === null && derivedPlay !== null) {
      changes.push({
        playIndex: index,
        kind: "Inserted",
        baseline: null,
        derived: derivedPlay,
      });
    } else if (baselinePlay !== null && derivedPlay === null) {
      changes.push({
        playIndex: index,
        kind: "Removed",
        baseline: baselinePlay,
        derived: null,
      });
    } else if (
      baselinePlay !== null &&
      derivedPlay !== null &&
      (baselinePlay.player !== derivedPlay.player ||
        baselinePlay.card !== derivedPlay.card)
    ) {
      changes.push({
        playIndex: index,
        kind: "Changed",
        baseline: baselinePlay,
        derived: derivedPlay,
      });
    }
  }
  return changes;
}

function compareActions(
  baseline: TimelineHypothesis | undefined,
  derived: TimelineHypothesis | undefined,
): ActionChange[] {
  const actions = new Map<
    string,
    { baseline: TimelineAction | null; derived: TimelineAction | null }
  >();
  for (const action of baseline?.actions ?? []) {
    const key = sourceActionKey(action);
    if (key !== null) {
      actions.set(key, { baseline: action, derived: null });
    }
  }
  for (const action of derived?.actions ?? []) {
    const key = sourceActionKey(action);
    if (key === null) {
      continue;
    }
    const current = actions.get(key);
    actions.set(key, {
      baseline: current?.baseline ?? null,
      derived: action,
    });
  }
  return Array.from(actions, ([key, change]) => ({ key, ...change })).filter(
    (change) =>
      actionSignature(change.baseline) !== actionSignature(change.derived),
  );
}

function sourceActionKey(action: TimelineAction | null): string | null {
  const observationId = actionString(action, "observation_id");
  const observedCardId = actionString(action, "observed_card_id");
  return observationId === null || observedCardId === null
    ? null
    : `${observationId}:${observedCardId}`;
}

function actionSignature(action: TimelineAction | null): string {
  if (action === null) {
    return "missing";
  }
  return JSON.stringify({
    kind: actionString(action, "kind"),
    card: actionString(action, "card"),
    player: actionString(action, "player"),
    play_index: actionNumber(action, "play_index"),
    score_contribution: actionNumber(action, "score_contribution"),
  });
}

function formatActionReference(key: string): string {
  const separator = key.indexOf(":");
  if (separator < 0) {
    return key;
  }
  return key.slice(0, separator) + " · " + key.slice(separator + 1);
}

function formatActionState(action: TimelineAction | null): string {
  if (action === null) {
    return "No source action";
  }
  const kind = actionString(action, "kind");
  const card = actionString(action, "card");
  return (
    (kind === null ? "Unknown" : formatIdentifier(kind)) +
    (card === null ? "" : " · " + formatCardIdentity(card))
  );
}

function formatActionScore(action: TimelineAction | null): string {
  const score = actionNumber(action, "score_contribution");
  return score === null ? "None" : formatScore(score);
}

function formatGameplayPlay(play: GameplayPlay | null): string {
  return play === null
    ? "None"
    : `${formatIdentifier(play.player)} · ${formatCardIdentity(play.card)}`;
}

function formatHypothesisScore(
  hypotheses: TimelineHypothesis[],
  rank: number,
): string {
  const hypothesis = hypotheses.find((candidate) => candidate.rank === rank);
  return hypothesis === undefined ? "—" : formatScore(hypothesis.total_score);
}

type CounterfactualDraft = {
  excludedObservationIds: string[];
  excludedObservedCards: CounterfactualObservedCard[];
  overrides: CounterfactualOverride[];
};

type CounterfactualController = {
  draft: CounterfactualDraft;
  excludedObservations: ReadonlySet<string>;
  excludedCards: ReadonlySet<string>;
  submitting: boolean;
  response: RoundCounterfactualResponse | null;
  error: string | null;
  effectiveOverrides: CounterfactualOverride[];
  hasInvalidOverride: boolean;
  changeCount: number;
  allObservationsExcluded: boolean;
  toggleObservation: (observationId: string) => void;
  toggleObservedCard: (reference: CounterfactualObservedCard) => void;
  setCandidateProbability: (
    observationId: string,
    observedCardId: string,
    candidate: TimelineCandidate,
    value: string,
  ) => void;
  runCounterfactual: () => Promise<void>;
  restoreBaseline: () => void;
};

const EMPTY_COUNTERFACTUAL_DRAFT: CounterfactualDraft = {
  excludedObservationIds: [],
  excludedObservedCards: [],
  overrides: [],
};

function CounterfactualWorkbench({
  timeline,
  children,
}: {
  timeline: RoundAnalysisTimeline;
  children: (counterfactual: CounterfactualController) => ReactNode;
}) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const [draft, setDraft] = useState<CounterfactualDraft>(
    EMPTY_COUNTERFACTUAL_DRAFT,
  );
  const [response, setResponse] = useState<RoundCounterfactualResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const excludedObservations = new Set(draft.excludedObservationIds);
  const excludedCards = new Set(
    draft.excludedObservedCards.map(counterfactualReferenceKey),
  );
  const effectiveOverrides = draft.overrides.filter((override) => {
    const baseline = findCandidate(timeline, override);
    return baseline !== null && baseline.probability !== override.probability;
  });
  const hasInvalidOverride = draft.overrides.some(
    (override) =>
      !Number.isFinite(override.probability) ||
      override.probability <= 0 ||
      override.probability > 1,
  );
  const changeCount =
    excludedObservations.size + excludedCards.size + effectiveOverrides.length;
  const allObservationsExcluded =
    timeline.rows.length > 0 &&
    timeline.rows.every((row) => excludedObservations.has(row.observation_id));

  function toggleObservation(observationId: string) {
    setDraft((current) => {
      const excluding = !current.excludedObservationIds.includes(observationId);
      return {
        ...current,
        excludedObservationIds: excluding
          ? [...current.excludedObservationIds, observationId]
          : current.excludedObservationIds.filter((id) => id !== observationId),
        excludedObservedCards: excluding
          ? current.excludedObservedCards.filter(
              (reference) => reference.observation_id !== observationId,
            )
          : current.excludedObservedCards,
        overrides: excluding
          ? current.overrides.filter(
              (override) => override.observation_id !== observationId,
            )
          : current.overrides,
      };
    });
  }

  function toggleObservedCard(reference: CounterfactualObservedCard) {
    const key = counterfactualReferenceKey(reference);
    setDraft((current) => ({
      ...current,
      excludedObservedCards: current.excludedObservedCards.some(
        (candidate) => counterfactualReferenceKey(candidate) === key,
      )
        ? current.excludedObservedCards.filter(
            (candidate) => counterfactualReferenceKey(candidate) !== key,
          )
        : [...current.excludedObservedCards, reference],
      overrides: current.overrides.filter(
        (override) => counterfactualReferenceKey(override) !== key,
      ),
    }));
  }

  function setCandidateProbability(
    observationId: string,
    observedCardId: string,
    candidate: TimelineCandidate,
    value: string,
  ) {
    const key = `${observationId}:${observedCardId}:${candidate.card}`;
    const probability = Number(value);
    setDraft((current) => {
      const withoutCurrent = current.overrides.filter(
        (override) =>
          `${override.observation_id}:${override.observed_card_id}:${override.card}` !==
          key,
      );
      if (value.trim() === "" || !Number.isFinite(probability)) {
        return { ...current, overrides: withoutCurrent };
      }
      return {
        ...current,
        overrides: [
          ...withoutCurrent,
          {
            observation_id: observationId,
            observed_card_id: observedCardId,
            card: candidate.card,
            probability,
          },
        ],
      };
    });
  }

  async function runCounterfactual() {
    if (changeCount === 0 || hasInvalidOverride || allObservationsExcluded) {
      return;
    }
    const payload: RoundCounterfactualCreateRequest = {
      schema_version: "round-analysis-counterfactual/v1",
      counterfactual_id: createCounterfactualId(),
      source_analysis_id: timeline.analysis_id,
      source_input_sha256: timeline.artifact_hashes.input_sha256,
      source_result_sha256: timeline.artifact_hashes.result_sha256,
      excluded_observation_ids: draft.excludedObservationIds,
      excluded_observed_cards: draft.excludedObservedCards,
      candidate_probability_overrides: effectiveOverrides,
    };
    setSubmitting(true);
    setError(null);
    try {
      const nextResponse = await client.createRoundCounterfactual(
        timeline.analysis_id,
        payload,
      );
      setResponse(nextResponse);
    } catch (reason: unknown) {
      setResponse(null);
      setError(describeError(reason));
    } finally {
      setSubmitting(false);
    }
  }

  function restoreBaseline() {
    setDraft(EMPTY_COUNTERFACTUAL_DRAFT);
    setResponse(null);
    setError(null);
  }

  return children({
    draft,
    excludedObservations,
    excludedCards,
    submitting,
    response,
    error,
    effectiveOverrides,
    hasInvalidOverride,
    changeCount,
    allObservationsExcluded,
    toggleObservation,
    toggleObservedCard,
    setCandidateProbability,
    runCounterfactual,
    restoreBaseline,
  });
}

function CounterfactualRunControls({
  counterfactual,
}: {
  counterfactual: CounterfactualController;
}) {
  return (
    <section
      className={styles.counterfactualPanel}
      aria-label="Counterfactual analysis"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Counterfactual analysis</p>
          <h2>Counterfactual run</h2>
        </div>
        <span className={styles.countLabel}>
          {counterfactual.changeCount} change
          {counterfactual.changeCount === 1 ? "" : "s"} drafted
        </span>
      </div>
      <p className={styles.explanationText}>
        Adjust an observation above, then run a comparison against the immutable
        baseline.
      </p>
      <div className={styles.counterfactualActions}>
        <button
          type="button"
          className={styles.primaryButton}
          onClick={() => void counterfactual.runCounterfactual()}
          disabled={
            counterfactual.submitting ||
            counterfactual.changeCount === 0 ||
            counterfactual.hasInvalidOverride ||
            counterfactual.allObservationsExcluded
          }
        >
          {counterfactual.submitting ? "Running…" : "Run counterfactual"}
        </button>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={counterfactual.restoreBaseline}
          disabled={counterfactual.submitting}
        >
          Restore baseline
        </button>
      </div>
      {counterfactual.error !== null ? (
        <p className={styles.errorMessage} role="alert">
          {counterfactual.error}
        </p>
      ) : null}
    </section>
  );
}

function CounterfactualComparison({
  response,
  timeline,
}: {
  response: RoundCounterfactualResponse;
  timeline: RoundAnalysisTimeline;
}) {
  const baseline = snapshotFromTimeline(timeline);
  const derived = parseCounterfactualSnapshot(response.result);
  if (derived === null) {
    return (
      <p className={styles.errorMessage}>
        The counterfactual result is invalid.
      </p>
    );
  }
  const baselineHypothesis = bestHypothesis(baseline.hypotheses);
  const derivedHypothesis = bestHypothesis(derived.hypotheses);
  const playChanges = compareGameplay(baselineHypothesis, derivedHypothesis);
  const actionChanges = compareActions(baselineHypothesis, derivedHypothesis);
  const decisionsChanged =
    JSON.stringify(baseline.focused_decisions) !==
    JSON.stringify(derived.focused_decisions);

  return (
    <div className={styles.comparison} aria-label="Counterfactual comparison">
      <div className={styles.comparisonHeading}>
        <div>
          <p className={styles.statusLabel}>Immutable result</p>
          <h3>Baseline versus counterfactual</h3>
        </div>
        <span className={styles.counterfactualId}>
          {response.counterfactual_id}
        </span>
      </div>
      <div className={styles.comparisonSummaries}>
        <ComparisonSummary title="Baseline" snapshot={baseline} />
        <ComparisonSummary title="Counterfactual" snapshot={derived} />
      </div>
      {baseline.diagnostics.truncated === true ||
      derived.diagnostics.truncated === true ? (
        <p className={styles.comparisonWarning} role="alert">
          Search truncation makes this comparison incomplete. The displayed
          hypotheses may not include every legal sequence.
        </p>
      ) : null}
      <div className={styles.comparisonDetails}>
        <ComparisonPlayChanges changes={playChanges} />
        <section className={styles.comparisonBlock}>
          <h4>Changed observations and cards</h4>
          {actionChanges.length === 0 ? (
            <p className={styles.emptyState}>
              No selected or ignored source actions changed.
            </p>
          ) : (
            <ul className={styles.changeList}>
              {actionChanges.map((change) => (
                <li key={change.key}>
                  <span className={styles.changeMarker}>Changed</span>{" "}
                  {formatActionReference(change.key)}
                  <span className={styles.changeDetail}>
                    Baseline: {formatActionState(change.baseline)} ·
                    Counterfactual: {formatActionState(change.derived)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className={styles.comparisonBlock}>
          <h4>Focused decisions</h4>
          <p
            className={
              decisionsChanged ? styles.changedText : styles.emptyState
            }
          >
            {decisionsChanged
              ? `${baseline.focused_decisions.length} baseline decision${baseline.focused_decisions.length === 1 ? "" : "s"} → ${derived.focused_decisions.length} counterfactual decision${derived.focused_decisions.length === 1 ? "" : "s"}`
              : "No focused decisions changed."}
          </p>
        </section>
        <ComparisonScoreChanges changes={actionChanges} />
        <ComparisonHypotheses baseline={baseline} derived={derived} />
        <ComparisonDiagnostics baseline={baseline} derived={derived} />
      </div>
    </div>
  );
}

function ComparisonSummary({
  title,
  snapshot,
}: {
  title: string;
  snapshot: CounterfactualSnapshot;
}) {
  const hypothesis = bestHypothesis(snapshot.hypotheses);
  return (
    <section className={styles.comparisonSummary}>
      <h4>{title}</h4>
      <StatusBadge value={snapshot.status} />
      <dl className={styles.comparisonStats}>
        <Stat
          label="Retained hypotheses"
          value={String(snapshot.hypotheses.length)}
        />
        <Stat
          label="Best score"
          value={
            hypothesis === undefined ? "—" : formatScore(hypothesis.total_score)
          }
        />
        <Stat
          label="Search truncated"
          value={snapshot.diagnostics.truncated === true ? "Yes" : "No"}
        />
      </dl>
    </section>
  );
}

function ComparisonPlayChanges({ changes }: { changes: GameplayChange[] }) {
  return (
    <section className={styles.comparisonBlock}>
      <h4>Changed card plays</h4>
      {changes.length === 0 ? (
        <p className={styles.emptyState}>No card-play changes.</p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.changeTable}>
            <caption className={styles.visuallyHidden}>
              Changed card plays
            </caption>
            <thead>
              <tr>
                <th scope="col">Play</th>
                <th scope="col">Change</th>
                <th scope="col">Baseline</th>
                <th scope="col">Counterfactual</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change) => (
                <tr key={change.playIndex}>
                  <th scope="row">{change.playIndex}</th>
                  <td>
                    <span className={styles.changeMarker}>{change.kind}</span>
                  </td>
                  <td>{formatGameplayPlay(change.baseline)}</td>
                  <td>{formatGameplayPlay(change.derived)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ComparisonScoreChanges({ changes }: { changes: ActionChange[] }) {
  const scoreChanges = changes.filter(
    (change) =>
      actionNumber(change.baseline, "score_contribution") !==
      actionNumber(change.derived, "score_contribution"),
  );
  return (
    <section className={styles.comparisonBlock}>
      <h4>Score contributions</h4>
      {scoreChanges.length === 0 ? (
        <p className={styles.emptyState}>
          No source-action score contributions changed.
        </p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.changeTable}>
            <caption className={styles.visuallyHidden}>
              Changed source-action score contributions
            </caption>
            <thead>
              <tr>
                <th scope="col">Observed card</th>
                <th scope="col">Baseline</th>
                <th scope="col">Counterfactual</th>
              </tr>
            </thead>
            <tbody>
              {scoreChanges.map((change) => (
                <tr key={change.key}>
                  <th scope="row">{formatActionReference(change.key)}</th>
                  <td>{formatActionScore(change.baseline)}</td>
                  <td>{formatActionScore(change.derived)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ComparisonHypotheses({
  baseline,
  derived,
}: {
  baseline: CounterfactualSnapshot;
  derived: CounterfactualSnapshot;
}) {
  const ranks = Array.from(
    new Set([
      ...baseline.hypotheses.map((hypothesis) => hypothesis.rank),
      ...derived.hypotheses.map((hypothesis) => hypothesis.rank),
    ]),
  ).sort((left, right) => left - right);
  return (
    <section className={styles.comparisonBlock}>
      <h4>Hypothesis scores</h4>
      {ranks.length === 0 ? (
        <p className={styles.emptyState}>
          No hypotheses retained in either result.
        </p>
      ) : (
        <div className={styles.tableScroller}>
          <table className={styles.changeTable}>
            <caption className={styles.visuallyHidden}>
              Baseline and counterfactual hypothesis scores
            </caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Baseline</th>
                <th scope="col">Counterfactual</th>
              </tr>
            </thead>
            <tbody>
              {ranks.map((rank) => (
                <tr key={rank}>
                  <th scope="row">{rank}</th>
                  <td>{formatHypothesisScore(baseline.hypotheses, rank)}</td>
                  <td>{formatHypothesisScore(derived.hypotheses, rank)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ComparisonDiagnostics({
  baseline,
  derived,
}: {
  baseline: CounterfactualSnapshot;
  derived: CounterfactualSnapshot;
}) {
  const keys = [
    "search_nodes",
    "complete_branches",
    "rejected_branches",
    "ignored_observations",
    "incomplete_observations",
    "truncated",
  ];
  return (
    <section className={styles.comparisonBlock}>
      <h4>Diagnostics</h4>
      <dl className={styles.diagnosticsComparison}>
        {keys.map((key) => (
          <div key={key}>
            <dt>{formatIdentifier(key)}</dt>
            <dd>
              <span>{formatDiagnosticValue(baseline.diagnostics[key])}</span>
              <span aria-hidden="true">→</span>
              <span>{formatDiagnosticValue(derived.diagnostics[key])}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function AnalysisExplanation({
  timeline,
  selectedHypothesis,
  selectedRow,
  onSelectRow,
  onSelectHypothesis,
}: {
  timeline: RoundAnalysisTimeline;
  selectedHypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined;
  selectedRow: DisplayRow | undefined;
  onSelectRow: (rowId: string) => void;
  onSelectHypothesis: (rank: number) => void;
}) {
  return (
    <section
      className={styles.explanationArea}
      aria-label="Analysis explanations"
    >
      <section className={styles.explanationPanel}>
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Interpretation guide</p>
            <h2>What the analysis says</h2>
          </div>
          <StatusBadge value={timeline.reconstruction_status} />
        </div>
        <p className={styles.explanationText}>
          {statusExplanation(timeline.reconstruction_status)}
        </p>
        {timeline.reconstruction_status === "incomplete" ||
        timeline.reconstruction_status === "impossible" ? (
          <FailureDetails timeline={timeline} />
        ) : null}
        <FocusedDecisionList
          decisions={timeline.focused_decisions}
          hypothesis={selectedHypothesis}
          onSelectRow={onSelectRow}
        />
      </section>

      <section className={styles.explanationPanel}>
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Retained possibilities</p>
            <h2>Hypothesis comparison</h2>
          </div>
          <span className={styles.countLabel}>
            {timeline.hypotheses.length} retained
          </span>
        </div>
        <HypothesisComparison
          hypotheses={timeline.hypotheses}
          selectedRank={selectedHypothesis?.rank ?? null}
          focusedDecisionCount={timeline.focused_decisions.length}
          onSelect={onSelectHypothesis}
        />
        {selectedHypothesis === undefined ? (
          <p className={styles.emptyState}>
            No retained hypotheses are available for comparison.
          </p>
        ) : (
          <ScoreDetails hypothesis={selectedHypothesis} />
        )}
      </section>

      <section className={styles.explanationPanel}>
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Runtime facts</p>
            <h2>Diagnostics and source data</h2>
          </div>
        </div>
        <DiagnosticsDetails diagnostics={timeline.diagnostics} />
        <RawDataDetails timeline={timeline} selectedRow={selectedRow} />
      </section>
    </section>
  );
}

function FocusedDecisionList({
  decisions,
  hypothesis,
  onSelectRow,
}: {
  decisions: RoundAnalysisTimeline["focused_decisions"];
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined;
  onSelectRow: (rowId: string) => void;
}) {
  if (decisions.length === 0) {
    return (
      <div className={styles.subsection}>
        <h3>Focused decisions</h3>
        <p className={styles.emptyState}>
          No focused decisions were retained for this result.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.subsection}>
      <h3>Focused decisions</h3>
      <ol className={styles.decisionList}>
        {decisions.map((decision, index) => {
          const playIndex = recordNumber(decision, "play_index");
          const actualPlay =
            playIndex === null ? null : gameplayPlayAt(hypothesis, playIndex);
          const sourceObservationIds = recordStringArray(
            decision,
            "source_observation_ids",
          );
          const alternatives = recordStringArray(decision, "alternatives");
          return (
            <li
              className={styles.decision}
              key={`${playIndex ?? index}-${index}`}
            >
              <strong>
                {playIndex === null
                  ? "Card-play decision"
                  : `Play ${playIndex}`}
                {recordString(decision, "player") === null
                  ? ""
                  : ` · ${formatIdentifier(recordString(decision, "player") ?? "")}`}
              </strong>
              <p>
                {recordString(decision, "description") ??
                  "Retained legal alternatives."}
              </p>
              <div
                className={styles.alternativeList}
                aria-label="Legal alternatives"
              >
                {alternatives.map((alternative) => (
                  <span className={styles.alternative} key={alternative}>
                    {formatAlternative(alternative)}
                  </span>
                ))}
              </div>
              <p className={styles.decisionOutcome}>
                Selected in this hypothesis:{" "}
                <strong>
                  {actualPlay === null
                    ? "No play available"
                    : `${formatCardIdentity(actualPlay.card)} · ${formatIdentifier(actualPlay.player)}`}
                </strong>
              </p>
              <div className={styles.sourceLinks}>
                <span className={styles.mutedLabel}>Source rows</span>
                {sourceObservationIds.length === 0 ? (
                  <span className={styles.emptyInline}>None</span>
                ) : (
                  sourceObservationIds.map((observationId) => (
                    <button
                      className={styles.sourceLink}
                      key={observationId}
                      type="button"
                      onClick={() => onSelectRow(observationId)}
                    >
                      Jump to {observationId}
                    </button>
                  ))
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function HypothesisComparison({
  hypotheses,
  selectedRank,
  focusedDecisionCount,
  onSelect,
}: {
  hypotheses: RoundAnalysisTimeline["hypotheses"];
  selectedRank: number | null;
  focusedDecisionCount: number;
  onSelect: (rank: number) => void;
}) {
  if (hypotheses.length === 0) {
    return <p className={styles.emptyState}>No retained hypotheses.</p>;
  }

  return (
    <div className={styles.tableScroller}>
      <table className={styles.comparisonTable}>
        <caption className={styles.visuallyHidden}>
          Retained reconstruction hypotheses
        </caption>
        <thead>
          <tr>
            <th scope="col">Rank</th>
            <th scope="col">Score</th>
            <th scope="col">Actions</th>
            <th scope="col">Focus</th>
          </tr>
        </thead>
        <tbody>
          {hypotheses.map((hypothesis) => {
            const selected = hypothesis.rank === selectedRank;
            const counts = actionCounts(hypothesis);
            return (
              <tr key={hypothesis.rank} data-selected={selected}>
                <th scope="row">
                  <button
                    className={styles.hypothesisButton}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onSelect(hypothesis.rank)}
                  >
                    Rank {hypothesis.rank}
                    {selected ? " · Selected" : ""}
                  </button>
                </th>
                <td>{formatScore(hypothesis.total_score)}</td>
                <td>{`${counts.selected} selected · ${counts.ignored} ignored · ${counts.inferred} inferred`}</td>
                <td>
                  {focusedDecisionCount > 0
                    ? `${focusedDecisionCount} decision${focusedDecisionCount === 1 ? "" : "s"}`
                    : "None"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ScoreDetails({
  hypothesis,
}: {
  hypothesis: RoundAnalysisTimeline["hypotheses"][number];
}) {
  return (
    <details className={styles.disclosure}>
      <summary>Score details for hypothesis rank {hypothesis.rank}</summary>
      <dl className={styles.breakdownList}>
        {Object.entries(hypothesis.score_breakdown).map(([key, value]) => (
          <div key={key}>
            <dt>{formatIdentifier(key)}</dt>
            <dd>{formatDiagnosticValue(value)}</dd>
          </div>
        ))}
      </dl>
      <h3>Action contributions</h3>
      <ol className={styles.contributionList}>
        {hypothesis.actions.map((action, index) => (
          <li key={`${actionKey(action)}-${index}`}>
            <span>{actionDescription(action)}</span>
            <strong>
              {formatScore(actionNumber(action, "score_contribution") ?? 0)}
            </strong>
          </li>
        ))}
      </ol>
    </details>
  );
}

function DiagnosticsDetails({
  diagnostics,
}: {
  diagnostics: Record<string, unknown>;
}) {
  return (
    <details className={styles.disclosure}>
      <summary>Engine diagnostics</summary>
      <dl className={styles.breakdownList}>
        {Object.entries(diagnostics).map(([key, value]) => (
          <div key={key}>
            <dt>{formatIdentifier(key)}</dt>
            <dd>{formatDiagnosticValue(value)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function RawDataDetails({
  timeline,
  selectedRow,
}: {
  timeline: RoundAnalysisTimeline;
  selectedRow: DisplayRow | undefined;
}) {
  const tableObservation =
    selectedRow?.kind === "evidence" ? selectedRow.row.table_observation : null;
  return (
    <div className={styles.rawDataList}>
      <details className={styles.disclosure}>
        <summary>Raw table-observation JSON</summary>
        {tableObservation === null ? (
          <p className={styles.emptyState}>
            Select an evidence row to inspect its observation.
          </p>
        ) : (
          <pre className={styles.rawJson}>{formatJson(tableObservation)}</pre>
        )}
      </details>
      <details className={styles.disclosure}>
        <summary>Raw reconstruction-result JSON</summary>
        <pre className={styles.rawJson}>
          {formatJson(reconstructionResultSnapshot(timeline))}
        </pre>
      </details>
    </div>
  );
}

function FailureDetails({ timeline }: { timeline: RoundAnalysisTimeline }) {
  const diagnostics = timeline.diagnostics;
  const incompleteObservations = recordStringArray(
    diagnostics,
    "incomplete_observations",
  );
  const rejectedBranches = recordStringArray(diagnostics, "rejected_branches");
  return (
    <div className={styles.failureDetails}>
      <strong>
        {timeline.reconstruction_status === "incomplete"
          ? "Incomplete input"
          : "Impossible input"}
      </strong>
      <p>
        {timeline.reconstruction_status === "incomplete"
          ? "The engine did not receive enough card proposals to build a complete legal sequence."
          : "No legal complete hypothesis survived replay under the selected ruleset."}
      </p>
      {incompleteObservations.length > 0 ? (
        <p>Incomplete observations: {incompleteObservations.join(", ")}.</p>
      ) : null}
      {rejectedBranches.length > 0 ? (
        <p>Rejected branches: {rejectedBranches.join("; ")}.</p>
      ) : null}
    </div>
  );
}

function TimelineRowView({
  row,
  index,
  selected,
  hypothesis,
  counterfactual,
  onSelect,
  onKeyDown,
}: {
  row: DisplayRow;
  index: number;
  selected: boolean;
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined;
  counterfactual: CounterfactualController;
  onSelect: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}) {
  return (
    <li>
      <div
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
          <ObservationCell row={row.row} counterfactual={counterfactual} />
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
      </div>
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
  row,
  counterfactual,
}: {
  row: TimelineEvidenceRow;
  counterfactual: CounterfactualController;
}) {
  const observation = row.table_observation;
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
      <CounterfactualObservationControls
        row={row}
        counterfactual={counterfactual}
      />
    </div>
  );
}

function CounterfactualObservationControls({
  row,
  counterfactual,
}: {
  row: TimelineEvidenceRow;
  counterfactual: CounterfactualController;
}) {
  const observation = row.table_observation;
  const observationExcluded = counterfactual.excludedObservations.has(
    row.observation_id,
  );

  return (
    <fieldset className={styles.counterfactualInline}>
      <legend>Counterfactual</legend>
      <label className={styles.checkboxLabel}>
        <input
          type="checkbox"
          checked={observationExcluded}
          onChange={() => counterfactual.toggleObservation(row.observation_id)}
          aria-label={`Exclude observation ${row.observation_id}`}
        />
        Exclude observation
      </label>
      {(observation.cards ?? []).map((card) => {
        const reference = {
          observation_id: row.observation_id,
          observed_card_id: card.observed_card_id,
        } satisfies CounterfactualObservedCard;
        const cardExcluded = counterfactual.excludedCards.has(
          counterfactualReferenceKey(reference),
        );
        return (
          <div
            className={styles.counterfactualCard}
            key={card.observed_card_id}
          >
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={cardExcluded}
                disabled={observationExcluded}
                onChange={() => counterfactual.toggleObservedCard(reference)}
                aria-label={`Exclude observed card ${card.observed_card_id}`}
              />
              Exclude card {card.observed_card_id}
            </label>
            {card.identity_candidates.length < 2 ? (
              <p className={styles.emptyInline}>
                A probability override needs at least two candidates.
              </p>
            ) : null}
            <div className={styles.overrideList}>
              {card.identity_candidates.map((candidate) => {
                const override = counterfactual.draft.overrides.find(
                  (current) =>
                    current.observation_id === row.observation_id &&
                    current.observed_card_id === card.observed_card_id &&
                    current.card === candidate.card,
                );
                return (
                  <label
                    className={styles.overrideControl}
                    key={candidate.card}
                  >
                    <span>{formatCardIdentity(candidate.card)}</span>
                    <input
                      type="number"
                      min="0.000001"
                      max="1"
                      step="0.001"
                      value={override?.probability ?? candidate.probability}
                      disabled={
                        observationExcluded ||
                        cardExcluded ||
                        card.identity_candidates.length < 2
                      }
                      onChange={(event) =>
                        counterfactual.setCandidateProbability(
                          row.observation_id,
                          card.observed_card_id,
                          candidate,
                          event.target.value,
                        )
                      }
                      aria-label={`Probability for ${formatCardIdentity(candidate.card)} in ${card.observed_card_id}`}
                    />
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </fieldset>
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

function statusExplanation(
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

function actionCounts(hypothesis: TimelineHypothesis): {
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

function actionDescription(action: TimelineAction): string {
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

function gameplayPlayAt(
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined,
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

function formatAlternative(value: string): string {
  const separator = value.indexOf(":");
  return separator < 0
    ? formatIdentifier(value)
    : `${formatIdentifier(value.slice(0, separator))} · ${formatCardIdentity(value.slice(separator + 1))}`;
}

function recordString(
  value: Record<string, unknown>,
  key: string,
): string | null {
  const item = value[key];
  return typeof item === "string" ? item : null;
}

function recordNumber(
  value: Record<string, unknown>,
  key: string,
): number | null {
  const item = value[key];
  return typeof item === "number" ? item : null;
}

function recordStringArray(
  value: Record<string, unknown>,
  key: string,
): string[] {
  const item = value[key];
  return Array.isArray(item) && item.every((entry) => typeof entry === "string")
    ? item
    : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatDiagnosticValue(value: unknown): string {
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

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

function reconstructionResultSnapshot(
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

function actionString(
  action: TimelineAction | null | undefined,
  key: string,
): string | null {
  const value = action?.[key];
  return typeof value === "string" ? value : null;
}

function actionNumber(
  action: TimelineAction | null | undefined,
  key: string,
): number | null {
  const value = action?.[key];
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

function createCounterfactualId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    bytes.forEach((_, index) => {
      bytes[index] = Math.floor(Math.random() * 256);
    });
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20)
  );
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
