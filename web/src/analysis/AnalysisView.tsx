import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  repositoryBundleVideoPath,
  type RoundAnalysisStatus,
  type RoundAnalysisTimeline,
} from "../api/client";
import styles from "../App.module.css";
import {
  CARD_IDENTITIES,
  CounterfactualComparison,
  CounterfactualRunControls,
  CounterfactualWorkbench,
  counterfactualReferenceKey,
  type CounterfactualController,
} from "./CounterfactualWorkbench";

export type TimelineAction =
  RoundAnalysisTimeline["hypotheses"][number]["actions"][number];
export type TimelineHypothesis = RoundAnalysisTimeline["hypotheses"][number];
export type TimelineEvidenceRow = RoundAnalysisTimeline["rows"][number];
export type TimelineInferredPlay =
  RoundAnalysisTimeline["inferred_plays"][number];
type TimelineObservation = TimelineEvidenceRow["table_observation"];
export type TimelineCard = NonNullable<TimelineObservation["cards"]>[number];
export type TimelineCandidate = TimelineCard["identity_candidates"][number];
type GameplayPlay = { player: string; card: string };
type CounterfactualObservedCard = {
  observation_id: string;
  observed_card_id: string;
};
type ExpandedEvidence = TimelineEvidenceRow;
type DisplayRow =
  | { kind: "evidence"; id: string; row: TimelineEvidenceRow }
  | { kind: "inferred"; id: string; play: TimelineInferredPlay };

function describeError(reason: unknown): string {
  return reason instanceof ApiError
    ? `The backend returned HTTP ${reason.status}.`
    : "The backend could not be reached.";
}

export function RecordingAnalysisView({
  analysisId,
  recordingId,
}: {
  analysisId: string;
  recordingId: string;
}) {
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
    <div className={styles.nestedAnalysis} id="selected-analysis">
      <div className={styles.nestedAnalysisHeader}>
        <div>
          <p className={styles.statusLabel}>Selected analysis</p>
          <p className={styles.analysisId} title={analysisId}>
            {analysisId}
          </p>
        </div>
        <a
          className={styles.recordingLink}
          href={`/recordings/${encodeURIComponent(recordingId)}`}
        >
          Clear selection
        </a>
      </div>
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
    </div>
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
  const recordingUrl = repositoryBundleVideoPath(timeline.recording_id);
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
  const [expandedEvidence, setExpandedEvidence] =
    useState<ExpandedEvidence | null>(null);
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

  const closeExpandedEvidence = useCallback(() => {
    setExpandedEvidence(null);
  }, []);

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

            <div className={styles.timelineWorkspace}>
              <div className={styles.timelineContent}>
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
                      onOpenDetails={setExpandedEvidence}
                      onSelect={() => selectRow(row.id)}
                      onKeyDown={(event) => {
                        if (event.target !== event.currentTarget) {
                          return;
                        }
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          selectRow(row.id);
                        } else if (event.key === "ArrowDown") {
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
              </div>
              <SelectedRecordingVideo
                row={selectedRow}
                recordingUrl={recordingUrl}
                onOpenDetails={setExpandedEvidence}
              />
            </div>
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
      <EvidenceDetailOverlay
        evidence={expandedEvidence}
        recordingUrl={recordingUrl}
        onClose={closeExpandedEvidence}
      />
    </div>
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
  onOpenDetails,
  onSelect,
  onKeyDown,
}: {
  row: DisplayRow;
  index: number;
  selected: boolean;
  hypothesis: RoundAnalysisTimeline["hypotheses"][number] | undefined;
  counterfactual: CounterfactualController;
  onOpenDetails: (row: TimelineEvidenceRow) => void;
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
          <EvidenceCell row={row.row} onOpenDetails={onOpenDetails} />
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

function EvidenceCell({
  row,
  onOpenDetails,
}: {
  row: TimelineEvidenceRow;
  onOpenDetails: (row: TimelineEvidenceRow) => void;
}) {
  const frame = row.central_frame;

  return (
    <div className={styles.cell}>
      <div className={styles.cellEyebrow}>
        Event {row.event_sequence} · {formatMilliseconds(row.event_time_ms)}
      </div>
      {frame === null ? (
        <div className={styles.missingFrame}>No central frame available</div>
      ) : (
        <button
          type="button"
          className={styles.frameButton}
          aria-label={`Open event details for event ${row.event_sequence}`}
          onClick={() => onOpenDetails(row)}
        >
          <img
            className={styles.frame}
            src={frame.url}
            alt={`Evidence frame for event ${row.event_sequence}`}
            loading="lazy"
          />
        </button>
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

function SelectedRecordingVideo({
  row,
  recordingUrl,
  onOpenDetails,
}: {
  row: DisplayRow | undefined;
  recordingUrl: string;
  onOpenDetails: (row: TimelineEvidenceRow) => void;
}) {
  if (row === undefined) {
    return null;
  }
  if (row.kind === "inferred") {
    return (
      <aside className={styles.videoPanel} aria-label="Selected event media">
        <h2>Full recording</h2>
        <SeekableVideo
          className={styles.recordingVideo}
          src={recordingUrl}
          ariaLabel="Full recording"
        />
        <p className={styles.videoUnavailable}>
          An inferred card play has no exact recording time.
        </p>
      </aside>
    );
  }

  return (
    <aside className={styles.videoPanel} aria-label="Selected event media">
      <div className={styles.videoHeading}>
        <h2>Full recording</h2>
        <span>
          Event {row.row.event_sequence} ·{" "}
          {formatMilliseconds(row.row.event_time_ms)}
        </span>
      </div>
      <SeekableVideo
        className={styles.recordingVideo}
        src={recordingUrl}
        seekSeconds={row.row.event_time_ms / 1000}
        ariaLabel={`Full recording for event ${row.row.event_sequence}`}
      />
      <button
        type="button"
        className={styles.detailButton}
        onClick={() => onOpenDetails(row.row)}
      >
        Open event details
      </button>
    </aside>
  );
}

function SeekableVideo({
  src,
  seekSeconds,
  className,
  ariaLabel,
}: {
  src: string;
  seekSeconds?: number;
  className: string;
  ariaLabel: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (video !== null && seekSeconds !== undefined && video.readyState >= 1) {
      video.currentTime = seekSeconds;
    }
  }, [seekSeconds, src]);

  return (
    <video
      ref={videoRef}
      className={className}
      src={src}
      controls
      preload="metadata"
      aria-label={ariaLabel}
      onLoadedMetadata={(event) => {
        if (seekSeconds !== undefined) {
          event.currentTarget.currentTime = seekSeconds;
        }
      }}
    />
  );
}

function EvidenceDetailOverlay({
  evidence,
  recordingUrl,
  onClose,
}: {
  evidence: ExpandedEvidence | null;
  recordingUrl: string;
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (evidence === null) {
      return;
    }
    const previousActiveElement = document.activeElement as HTMLElement | null;
    const previousBodyOverflow = document.body.style.overflow;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      previousActiveElement?.focus();
    };
  }, [evidence, onClose]);

  if (evidence === null) {
    return null;
  }

  const titleId = `event-detail-${evidence.event_sequence}-title`;
  const snippet = evidence.video_snippet;
  const snippetSeekSeconds =
    snippet === null
      ? undefined
      : Math.min(
          Math.max(-snippet.start_offset_ms / 1000, 0),
          snippet.duration_ms / 1000,
        );
  const cards = evidence.table_observation.cards ?? [];
  return (
    <div
      className={styles.frameOverlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={onClose}
    >
      <div
        className={styles.frameDialog}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.frameDialogHeader}>
          <div>
            <p className={styles.statusLabel}>Event details</p>
            <h2 id={titleId}>
              Event {evidence.event_sequence} ·{" "}
              {formatMilliseconds(evidence.event_time_ms)}
            </h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.frameDialogClose}
            aria-label="Close event details"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <section className={styles.detailRecordingSection}>
          <h3>Full recording</h3>
          <SeekableVideo
            className={styles.detailRecordingVideo}
            src={recordingUrl}
            seekSeconds={evidence.event_time_ms / 1000}
            ariaLabel={`Full recording for event ${evidence.event_sequence} in detail view`}
          />
        </section>
        <div className={styles.detailEvidenceGrid}>
          <section>
            <h3>Central frame</h3>
            {evidence.central_frame === null ? (
              <p className={styles.videoUnavailable}>
                No central frame is available.
              </p>
            ) : (
              <img
                className={styles.frameDialogImage}
                src={evidence.central_frame.url}
                alt={`Enlarged evidence frame for event ${evidence.event_sequence}`}
              />
            )}
          </section>
          <section>
            <h3>Evidence video</h3>
            {snippet === null ? (
              <p className={styles.videoUnavailable}>
                No evidence video is available.
              </p>
            ) : (
              <SeekableVideo
                className={styles.detailEvidenceVideo}
                src={snippet.url}
                seekSeconds={snippetSeekSeconds}
                ariaLabel={`Evidence video snippet for event ${evidence.event_sequence}`}
              />
            )}
          </section>
        </div>
        <section className={styles.detailFacts}>
          <h3>Observed cards</h3>
          <p className={styles.frameDialogMeta}>
            Observation <span>{evidence.observation_id}</span> · Package{" "}
            <span>{evidence.package_id}</span>
          </p>
          {cards.length === 0 ? (
            <p className={styles.videoUnavailable}>No observed cards.</p>
          ) : (
            <div className={styles.detailCardGrid}>
              {cards.map((card) => (
                <div
                  className={styles.observedCard}
                  key={card.observed_card_id}
                >
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
                        aria-label={`${formatCardIdentity(candidate.card)} detail confidence`}
                      />
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
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
        const identityOverride =
          counterfactual.draft.cardIdentityOverrides.find(
            (override) =>
              counterfactualReferenceKey(override) ===
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
            <label className={styles.identityOverrideControl}>
              <span>Correct classification</span>
              <select
                value={identityOverride?.card ?? ""}
                disabled={observationExcluded || cardExcluded}
                onChange={(event) =>
                  counterfactual.setCardIdentity(
                    row.observation_id,
                    card.observed_card_id,
                    event.target.value,
                  )
                }
                aria-label={`Correct classification for ${card.observed_card_id}`}
              >
                <option value="">No correction</option>
                {CARD_IDENTITIES.map((identity) => (
                  <option key={identity} value={identity}>
                    {formatCardIdentity(identity)}
                  </option>
                ))}
              </select>
            </label>
            {identityOverride === undefined ? null : (
              <p className={styles.identityOverrideNote}>
                Derived input uses {formatCardIdentity(identityOverride.card)}
                as the only identity.
              </p>
            )}
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
                        card.identity_candidates.length < 2 ||
                        identityOverride !== undefined
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

export function gameplayPlayAt(
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

function formatMilliseconds(value: number): string {
  return `${(value / 1000).toFixed(3)} s`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatScore(value: number): string {
  return value.toFixed(3);
}
