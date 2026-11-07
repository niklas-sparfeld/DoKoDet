import { createPortal } from "react-dom";
import { useEffect, useState, type ReactNode } from "react";

import { type RoundCounterfactualCreateRequest } from "../api/analysisContracts";
import {
  type RoundCounterfactualResponse,
  type RoundAnalysisTimeline,
} from "../api/analysisContracts";
import styles from "../App.module.css";
import { JobStartActions, type JobStartAction } from "../jobs/JobStartActions";
import {
  AcceptedJobReceipt,
  useManagedJobSubmission,
} from "../jobs/useJobSubmission";
import {
  actionNumber,
  actionString,
  formatCardIdentity,
  formatDiagnosticValue,
  formatIdentifier,
  formatScore,
  gameplayPlayAt,
  isRecord,
  type TimelineAction,
  type TimelineCandidate,
  type TimelineCard,
  type TimelineHypothesis,
} from "./analysisFormatting";

type GameplayPlay = { player: string; card: string };
type CounterfactualCardIdentityOverride = NonNullable<
  RoundCounterfactualCreateRequest["card_identity_overrides"]
>[number];
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

export const CARD_IDENTITIES = [
  "CLUBS_NINE",
  "CLUBS_JACK",
  "CLUBS_QUEEN",
  "CLUBS_KING",
  "CLUBS_TEN",
  "CLUBS_ACE",
  "SPADES_NINE",
  "SPADES_JACK",
  "SPADES_QUEEN",
  "SPADES_KING",
  "SPADES_TEN",
  "SPADES_ACE",
  "HEARTS_NINE",
  "HEARTS_JACK",
  "HEARTS_QUEEN",
  "HEARTS_KING",
  "HEARTS_TEN",
  "HEARTS_ACE",
  "DIAMONDS_NINE",
  "DIAMONDS_JACK",
  "DIAMONDS_QUEEN",
  "DIAMONDS_KING",
  "DIAMONDS_TEN",
  "DIAMONDS_ACE",
] as const;

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
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

export function counterfactualReferenceKey(
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
  const card = findObservedCard(timeline, override);
  return (
    card?.identity_candidates.find(
      (candidate) => candidate.card === override.card,
    ) ?? null
  );
}

function findObservedCard(
  timeline: RoundAnalysisTimeline,
  reference: Pick<
    CounterfactualObservedCard,
    "observation_id" | "observed_card_id"
  >,
): TimelineCard | null {
  const row = timeline.rows.find(
    (candidate) => candidate.observation_id === reference.observation_id,
  );
  return (
    row?.table_observation.cards?.find(
      (card) => card.observed_card_id === reference.observed_card_id,
    ) ?? null
  );
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
  cardIdentityOverrides: CounterfactualCardIdentityOverride[];
  overrides: CounterfactualOverride[];
};

export type CounterfactualController = {
  draft: CounterfactualDraft;
  excludedObservations: ReadonlySet<string>;
  excludedCards: ReadonlySet<string>;
  submitting: boolean;
  uncertain: boolean;
  response: RoundCounterfactualResponse | null;
  jobId: string | null;
  error: string | null;
  effectiveCardIdentityOverrides: CounterfactualCardIdentityOverride[];
  effectiveOverrides: CounterfactualOverride[];
  hasInvalidOverride: boolean;
  changeCount: number;
  allObservationsExcluded: boolean;
  toggleObservation: (observationId: string) => void;
  toggleObservedCard: (reference: CounterfactualObservedCard) => void;
  setCardIdentity: (
    observationId: string,
    observedCardId: string,
    card: string,
  ) => void;
  setCandidateProbability: (
    observationId: string,
    observedCardId: string,
    candidate: TimelineCandidate,
    value: string,
  ) => void;
  restoreBaseline: () => void;
};

const EMPTY_COUNTERFACTUAL_DRAFT: CounterfactualDraft = {
  excludedObservationIds: [],
  excludedObservedCards: [],
  cardIdentityOverrides: [],
  overrides: [],
};

export function CounterfactualWorkbench({
  timeline,
  children,
}: {
  timeline: RoundAnalysisTimeline;
  children: (counterfactual: CounterfactualController) => ReactNode;
}) {
  const submission = useManagedJobSubmission();
  const [actionsTarget, setActionsTarget] = useState<HTMLElement | null>(null);
  const [frozenRequest, setFrozenRequest] = useState<{
    fingerprint: string;
    payload: RoundCounterfactualCreateRequest;
  } | null>(null);
  const [draft, setDraft] = useState<CounterfactualDraft>(
    EMPTY_COUNTERFACTUAL_DRAFT,
  );
  const [response, setResponse] = useState<RoundCounterfactualResponse | null>(
    null,
  );
  const submitting = submission.submitting;
  const jobId = submission.job?.id ?? null;
  const error = submission.error;
  const uncertain = error?.startsWith("Acceptance is uncertain") ?? false;

  useEffect(() => {
    const findTarget = () =>
      setActionsTarget(
        document.querySelector<HTMLElement>(
          '[data-analysis-inspector-slot="action"]',
        ),
      );
    findTarget();
    const observer = new MutationObserver(findTarget);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  const excludedObservations = new Set(draft.excludedObservationIds);
  const excludedCards = new Set(
    draft.excludedObservedCards.map(counterfactualReferenceKey),
  );
  const effectiveCardIdentityOverrides = draft.cardIdentityOverrides.filter(
    (override) => {
      const baseline = findObservedCard(timeline, override);
      return !(
        baseline?.identity_candidates.length === 1 &&
        baseline.identity_candidates[0]?.card === override.card
      );
    },
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
    excludedObservations.size +
    excludedCards.size +
    effectiveCardIdentityOverrides.length +
    effectiveOverrides.length;
  const allObservationsExcluded =
    timeline.rows.length > 0 &&
    timeline.rows.every((row) => excludedObservations.has(row.observation_id));

  function updateDraft(
    updater: (current: CounterfactualDraft) => CounterfactualDraft,
  ) {
    if (uncertain || submitting) return;
    setDraft(updater);
    setResponse(null);
    if (frozenRequest !== null) setFrozenRequest(null);
  }

  function toggleObservation(observationId: string) {
    updateDraft((current) => {
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
        cardIdentityOverrides: excluding
          ? current.cardIdentityOverrides.filter(
              (override) => override.observation_id !== observationId,
            )
          : current.cardIdentityOverrides,
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
    updateDraft((current) => ({
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
      cardIdentityOverrides: current.cardIdentityOverrides.filter(
        (override) => counterfactualReferenceKey(override) !== key,
      ),
    }));
  }

  function setCardIdentity(
    observationId: string,
    observedCardId: string,
    card: string,
  ) {
    const key = `${observationId}:${observedCardId}`;
    updateDraft((current) => ({
      ...current,
      cardIdentityOverrides:
        card.trim() === ""
          ? current.cardIdentityOverrides.filter(
              (override) => counterfactualReferenceKey(override) !== key,
            )
          : [
              ...current.cardIdentityOverrides.filter(
                (override) => counterfactualReferenceKey(override) !== key,
              ),
              {
                observation_id: observationId,
                observed_card_id: observedCardId,
                card,
              },
            ],
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
    updateDraft((current) => {
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

  function buildRequest(): RoundCounterfactualCreateRequest {
    return {
      schema_version: "round-analysis-counterfactual/v1",
      counterfactual_id: createCounterfactualId(),
      source_analysis_id: timeline.analysis_id,
      source_input_sha256: timeline.artifact_hashes.input_sha256,
      source_result_sha256: timeline.artifact_hashes.result_sha256,
      excluded_observation_ids: draft.excludedObservationIds,
      excluded_observed_cards: draft.excludedObservedCards,
      card_identity_overrides: effectiveCardIdentityOverrides,
      candidate_probability_overrides: effectiveOverrides,
    };
  }

  async function startCounterfactual() {
    if (changeCount === 0 || hasInvalidOverride || allObservationsExcluded)
      return false;
    const currentFingerprint = JSON.stringify({
      analysisId: timeline.analysis_id,
      inputHash: timeline.artifact_hashes.input_sha256,
      resultHash: timeline.artifact_hashes.result_sha256,
      excludedObservationIds: draft.excludedObservationIds,
      excludedObservedCards: draft.excludedObservedCards,
      cardIdentityOverrides: effectiveCardIdentityOverrides,
      candidateProbabilityOverrides: effectiveOverrides,
    });
    let pending = frozenRequest;
    if (pending === null || pending.fingerprint !== currentFingerprint) {
      pending = {
        fingerprint: currentFingerprint,
        payload: buildRequest(),
      };
      setFrozenRequest(pending);
    }
    const accepted = await submission.submit({
      type: "counterfactual",
      context: { analysis_id: timeline.analysis_id },
      request: pending.payload as unknown as Record<string, unknown>,
    });
    if (accepted === null) return false;
    setFrozenRequest(null);
    return true;
  }

  function restoreBaseline() {
    if (uncertain || submitting) return;
    setDraft(EMPTY_COUNTERFACTUAL_DRAFT);
    setResponse(null);
    setFrozenRequest(null);
  }

  const counterfactualState: CounterfactualController = {
    draft,
    excludedObservations,
    excludedCards,
    submitting,
    uncertain,
    response,
    jobId,
    error,
    effectiveCardIdentityOverrides,
    effectiveOverrides,
    hasInvalidOverride,
    changeCount,
    allObservationsExcluded,
    toggleObservation,
    toggleObservedCard,
    setCardIdentity,
    setCandidateProbability,
    restoreBaseline,
  };

  return (
    <div
      className={`${styles.counterfactualWorkbench} ${
        changeCount > 0 && response === null
          ? styles.hasPendingCounterfactual
          : ""
      }`}
    >
      <CounterfactualStatusBar counterfactual={counterfactualState} />
      {actionsTarget !== null
        ? createPortal(
            <>
              <JobStartActions
                actions={[
                  buildCounterfactualAction(
                    timeline,
                    draft,
                    effectiveCardIdentityOverrides,
                    effectiveOverrides,
                    changeCount,
                  ),
                ]}
                submitting={submitting}
                validationErrors={counterfactualErrors(
                  changeCount,
                  hasInvalidOverride,
                  allObservationsExcluded,
                  error,
                )}
                canSubmit={
                  changeCount > 0 &&
                  !hasInvalidOverride &&
                  !allObservationsExcluded
                }
                onStart={startCounterfactual}
              />
              {submission.job ? (
                <AcceptedJobReceipt job={submission.job} />
              ) : null}
            </>,
            actionsTarget,
          )
        : null}
      {children(counterfactualState)}
    </div>
  );
}

function CounterfactualStatusBar({
  counterfactual,
}: {
  counterfactual: CounterfactualController;
}) {
  if (counterfactual.changeCount === 0 || counterfactual.response !== null) {
    return null;
  }

  return (
    <section
      className={styles.counterfactualStatusBar}
      role="status"
      aria-label="Counterfactual status"
      aria-live="polite"
    >
      <div>
        <p className={styles.statusLabel}>Counterfactual status</p>
        <strong>
          {counterfactual.changeCount} unapplied counterfactual change
          {counterfactual.changeCount === 1 ? "" : "s"}
        </strong>
      </div>
      <span>Start a calculation from the workspace Actions group.</span>
    </section>
  );
}

function buildCounterfactualAction(
  timeline: RoundAnalysisTimeline,
  draft: CounterfactualDraft,
  effectiveCardIdentityOverrides: CounterfactualCardIdentityOverride[],
  effectiveOverrides: CounterfactualOverride[],
  changeCount: number,
): JobStartAction {
  const constraints = {
    excluded_observation_ids: draft.excludedObservationIds,
    excluded_observed_cards: draft.excludedObservedCards,
    card_identity_overrides: effectiveCardIdentityOverrides,
    candidate_probability_overrides: effectiveOverrides,
  };
  return {
    id: "counterfactual",
    label: "Calculate counterfactual",
    description:
      "Calculate an immutable comparison from this exact analysis and its current correction constraints. Starting the calculation does not approve the corrections or change the selected analysis.",
    expectedOutput:
      "One counterfactual job linked through Jobs, with a result that can be reviewed against the baseline.",
    sections: [
      {
        title: "Exact analysis result",
        content: (
          <dl>
            <div>
              <dt>Analysis ID</dt>
              <dd>{timeline.analysis_id}</dd>
            </div>
            <div>
              <dt>Input SHA-256</dt>
              <dd>{timeline.artifact_hashes.input_sha256}</dd>
            </div>
            <div>
              <dt>Result SHA-256</dt>
              <dd>{timeline.artifact_hashes.result_sha256}</dd>
            </div>
          </dl>
        ),
      },
      {
        title: `Correction constraints (${changeCount} changes)`,
        content: <pre>{JSON.stringify(constraints, null, 2)}</pre>,
      },
      {
        title: "Calculation settings",
        content: (
          <>
            <p>
              The calculation uses the settings frozen in the source analysis.
            </p>
            <pre>{JSON.stringify(timeline.search, null, 2)}</pre>
          </>
        ),
      },
    ],
  };
}

function counterfactualErrors(
  changeCount: number,
  hasInvalidOverride: boolean,
  allObservationsExcluded: boolean,
  submissionError: string | null,
): string[] {
  return [
    ...(changeCount === 0 ? ["Add at least one correction constraint."] : []),
    ...(hasInvalidOverride
      ? ["Candidate probabilities must be greater than 0 and at most 1."]
      : []),
    ...(allObservationsExcluded
      ? ["Keep at least one observation in the analysis."]
      : []),
    ...(submissionError ? [submissionError] : []),
  ];
}

export function CounterfactualRunControls({
  counterfactual,
}: {
  counterfactual: CounterfactualController;
}) {
  return (
    <section
      className={styles.counterfactualPanel}
      aria-label="Counterfactual draft"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.statusLabel}>Counterfactual draft</p>
          <h2>Correction constraints</h2>
        </div>
        <span className={styles.countLabel}>
          {counterfactual.changeCount} change
          {counterfactual.changeCount === 1 ? "" : "s"} drafted
        </span>
      </div>
      <p className={styles.explanationText}>
        Edit the correction constraints here. Start their calculation from the
        workspace Actions group.
      </p>
      <div className={styles.counterfactualActions}>
        {counterfactual.jobId !== null ? (
          <p>
            Counterfactual processing was accepted.{" "}
            <a href={`/jobs/${encodeURIComponent(counterfactual.jobId)}`}>
              View job
            </a>
          </p>
        ) : null}
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={counterfactual.restoreBaseline}
          disabled={counterfactual.submitting || counterfactual.uncertain}
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

export function CounterfactualComparison({
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

function createCounterfactualId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function")
    return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function")
    globalThis.crypto.getRandomValues(bytes);
  else
    bytes.forEach((_, index) => {
      bytes[index] = Math.floor(Math.random() * 256);
    });
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
