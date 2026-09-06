import { useEffect, useMemo, useRef, useState, type RefObject } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  pipelineDerivedFramePath,
  pipelineIdentityCropPath,
  repositoryBundleVideoPath,
  type PipelineComparisonRequest,
  type PipelineComparisonResponse,
  type PipelineRun,
  type PipelineStageKey,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import type { PipelineUrlState } from "./RecordingPipelineWorkspace";

type ComparisonContentType = PipelineComparisonRequest["content_type"];
type ComparisonItem = PipelineComparisonResponse["items"][number];
type ComparisonPolicy = PipelineComparisonRequest["matching_policy"];

const OUTCOME_TEXT: Record<ComparisonItem["outcome"], string> = {
  match: "Matched",
  miss: "Miss: reference item was not found",
  extra: "Extra: run item has no reference match",
  disagreement: "Disagreement: run result differs from the reference",
  failure: "Processor failure",
  empty: "Empty source frame",
  not_reviewed: "Not reviewed",
  unpaired_input: "Unpaired input",
};

const POLICIES: Record<ComparisonContentType, ComparisonPolicy> = {
  events: {
    policy_id: "event-timing/v1",
    kind: "event_timing",
    anchor: "start_us",
    tolerance_us: 50_000,
  },
  visible_cards: {
    policy_id: "visible-card-geometry/v1",
    kind: "visible_card_geometry",
    iou_threshold: 0.5,
    derived_box_policy: "bounding_box",
  },
  visual_identities: {
    policy_id: "visual-identity-geometry/v1",
    kind: "visual_identity_geometry",
    iou_threshold: 0.5,
    derived_box_policy: "bounding_box",
  },
};

export function ComparisonView({
  recordingId,
  stage,
  durationUs,
  urlState,
  onNavigate,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  durationUs: number;
  urlState: PipelineUrlState;
  onNavigate: (path: string, replace?: boolean) => void;
}) {
  const contentType = comparisonContentType(stage.key);
  const client = useMemo(() => createDokoDetectorClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [comparison, setComparison] =
    useState<PipelineComparisonResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  const runs = useMemo(() => comparableRuns(stage), [stage]);
  const referenceOptions = useMemo(
    () =>
      stage.input_options.filter(
        (option) => option.origin === "manual" || option.origin === "corrected",
      ),
    [stage.input_options],
  );
  const defaults = useMemo(
    () => defaultComparisonSelection(runs, referenceOptions, stage),
    [referenceOptions, runs, stage],
  );
  const selection = useMemo(
    () => ({
      left:
        urlState.left !== null &&
        runs.some((run) => run.run_id === urlState.left)
          ? urlState.left
          : defaults.left,
      right:
        urlState.right !== null &&
        runs.some((run) => run.run_id === urlState.right)
          ? urlState.right
          : defaults.right,
      reference:
        urlState.reference !== null &&
        referenceOptions.some(
          (option) => option.revision_id === urlState.reference,
        )
          ? urlState.reference
          : defaults.reference,
    }),
    [
      defaults,
      referenceOptions,
      runs,
      urlState.left,
      urlState.reference,
      urlState.right,
    ],
  );
  const selectionKey = `${selection.left ?? ""}:${selection.right ?? ""}:${selection.reference ?? ""}`;
  const activeComparison =
    comparison !== null &&
    comparison.left.run_id === selection.left &&
    comparison.right.run_id === selection.right &&
    comparison.reference.revision_id === selection.reference
      ? comparison
      : null;
  const activeError = errorKey === selectionKey ? error : null;
  const selectionReady =
    contentType !== null &&
    selection.left !== null &&
    selection.right !== null &&
    selection.reference !== null;
  const loading =
    selectionReady && activeComparison === null && activeError === null;
  const selectionError =
    selection.left !== null &&
    selection.right !== null &&
    selection.left === selection.right
      ? "Choose two different terminal runs."
      : null;

  useEffect(() => {
    if (
      contentType === null ||
      selection.left === null ||
      selection.right === null ||
      selection.reference === null
    ) {
      return;
    }
    const nextPath = comparisonPath(recordingId, stage.key, {
      ...urlState,
      left: selection.left,
      right: selection.right,
      reference: selection.reference,
    });
    const currentPath = `${window.location.pathname}${window.location.search}`;
    if (nextPath !== currentPath) {
      onNavigate(nextPath, true);
    }
  }, [
    contentType,
    onNavigate,
    recordingId,
    selection.left,
    selection.reference,
    selection.right,
    stage.key,
    urlState,
  ]);

  useEffect(() => {
    if (
      contentType === null ||
      selection.left === null ||
      selection.right === null ||
      selection.reference === null ||
      selection.left === selection.right
    ) {
      return;
    }
    const controller = new AbortController();
    void client
      .comparePipelineRuns(
        recordingId,
        {
          schema_version: "pipeline-comparison-request/v1",
          recording_id: recordingId,
          content_type: contentType,
          left_run_id: selection.left,
          right_run_id: selection.right,
          reference_revision_id: selection.reference,
          matching_policy: POLICIES[contentType],
        },
        { signal: controller.signal },
      )
      .then((response) => {
        if (!controller.signal.aborted) {
          setComparison(response);
          setError(null);
          setErrorKey(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeComparisonError(reason));
          setErrorKey(selectionKey);
        }
      });
    return () => controller.abort();
  }, [
    client,
    contentType,
    recordingId,
    selection.left,
    selection.reference,
    selection.right,
    selectionKey,
  ]);

  const selectedItem =
    activeComparison?.items.find((item) => item.item_id === urlState.item) ??
    null;
  const selectedTimeUs = selectedItem?.source_time_us ?? urlState.tUs;

  useEffect(() => {
    const video = videoRef.current;
    if (
      video === null ||
      selectedTimeUs === null ||
      selectedTimeUs === undefined
    ) {
      return;
    }
    if (video.readyState >= 1) {
      video.currentTime = clampTime(selectedTimeUs, durationUs) / 1_000_000;
    }
  }, [durationUs, selectedTimeUs]);

  if (contentType === null) {
    return (
      <p className={styles.detailEmptyState} role="status">
        This stage does not support run comparison.
      </p>
    );
  }

  if (runs.length < 2 || referenceOptions.length === 0) {
    return (
      <section
        className={styles.comparisonWorkspace}
        aria-labelledby="comparison-heading"
      >
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Comparison</p>
            <h3 id="comparison-heading">Comparison workspace</h3>
          </div>
        </div>
        <p className={styles.detailEmptyState}>
          Select two terminal runs and one completed reference before comparing.
        </p>
      </section>
    );
  }

  function selectValue(
    field: "left" | "right" | "reference",
    value: string,
  ): void {
    const nextState: PipelineUrlState = {
      ...urlState,
      left: field === "left" ? value : selection.left,
      right: field === "right" ? value : selection.right,
      reference: field === "reference" ? value : selection.reference,
      item: null,
      tUs: null,
    };
    onNavigate(comparisonPath(recordingId, stage.key, nextState));
  }

  function selectItem(item: ComparisonItem): void {
    onNavigate(
      comparisonPath(recordingId, stage.key, {
        ...urlState,
        left: selection.left,
        right: selection.right,
        reference: selection.reference,
        item: item.item_id,
        tUs: item.source_time_us,
      }),
    );
  }

  return (
    <section
      className={styles.comparisonWorkspace}
      aria-labelledby="comparison-heading"
    >
      <div className={styles.comparisonWorkspaceHeading}>
        <div>
          <p className={styles.statusLabel}>Comparison</p>
          <h3 id="comparison-heading">Comparison workspace</h3>
          <p className={styles.comparisonMode}>
            {activeComparison === null
              ? "Preparing the newest compatible pair…"
              : formatIdentifier(activeComparison.mode)}
          </p>
        </div>
        {activeComparison !== null ? (
          <span className={styles.status} data-state="complete">
            {activeComparison.items.length} outcome
            {activeComparison.items.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      <div className={styles.comparisonSelectors}>
        <label className={styles.pipelineSelector}>
          <span>Left terminal run</span>
          <select
            aria-label="Left terminal run"
            value={selection.left ?? ""}
            onChange={(event) => selectValue("left", event.target.value)}
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {runLabel(run)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.pipelineSelector}>
          <span>Right terminal run</span>
          <select
            aria-label="Right terminal run"
            value={selection.right ?? ""}
            onChange={(event) => selectValue("right", event.target.value)}
          >
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {runLabel(run)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.pipelineSelector}>
          <span>Completed reference</span>
          <select
            aria-label="Completed reference"
            value={selection.reference ?? ""}
            onChange={(event) => selectValue("reference", event.target.value)}
          >
            {referenceOptions.map((option) => (
              <option key={option.revision_id} value={option.revision_id}>
                {option.display_label} · {option.revision_id}
              </option>
            ))}
          </select>
        </label>
      </div>

      {activeError !== null || selectionError !== null ? (
        <p className={styles.errorMessage} role="alert">
          {activeError ?? selectionError}
        </p>
      ) : loading ? (
        <p className={styles.loading} role="status">
          Loading comparison…
        </p>
      ) : activeComparison === null ? null : (
        <>
          <ComparisonFacts comparison={activeComparison} />
          <div className={styles.comparisonInspectionGrid}>
            <div className={styles.comparisonOutcomePanel}>
              <h4>Source-ordered outcomes</h4>
              {activeComparison.items.length === 0 ? (
                <p className={styles.detailEmptyState}>
                  No outcomes in the reviewed scope.
                </p>
              ) : (
                <ol className={styles.comparisonOutcomeList}>
                  {activeComparison.items.map((item) => (
                    <li
                      key={item.item_id}
                      data-selected={selectedItem?.item_id === item.item_id}
                    >
                      <button
                        type="button"
                        className={styles.comparisonOutcomeButton}
                        aria-label={`Inspect ${item.item_id}`}
                        onClick={() => selectItem(item)}
                      >
                        <span>
                          {item.source_time_us === null
                            ? "No source time"
                            : formatMicroseconds(item.source_time_us)}
                        </span>
                        <strong>{OUTCOME_TEXT[item.outcome]}</strong>
                        <small>
                          {formatIdentifier(item.side)} ·{" "}
                          {formatIdentifier(item.event_type)}
                        </small>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <ComparisonSourcePanel
              recordingId={recordingId}
              comparison={activeComparison}
              contentType={contentType}
              item={selectedItem}
              videoRef={videoRef}
              durationUs={durationUs}
              onLoadedMetadata={() => {
                const video = videoRef.current;
                if (
                  video !== null &&
                  selectedTimeUs !== null &&
                  selectedTimeUs !== undefined
                ) {
                  video.currentTime =
                    clampTime(selectedTimeUs, durationUs) / 1_000_000;
                }
              }}
            />
          </div>
        </>
      )}
    </section>
  );
}

function ComparisonFacts({
  comparison,
}: {
  comparison: PipelineComparisonResponse;
}) {
  const leftCounts = comparison.counts.left;
  const rightCounts = comparison.counts.right;
  return (
    <div className={styles.comparisonFacts}>
      <section>
        <h4>Exact inputs</h4>
        <dl className={styles.comparisonFactsList}>
          <div>
            <dt>Left</dt>
            <dd>
              {comparison.left.run_id} · {comparison.left.revision_id}
              <br />
              inputs: {comparison.left.input_revision_ids.join(", ") || "none"}
            </dd>
          </div>
          <div>
            <dt>Right</dt>
            <dd>
              {comparison.right.run_id} · {comparison.right.revision_id}
              <br />
              inputs: {comparison.right.input_revision_ids.join(", ") || "none"}
            </dd>
          </div>
          <div>
            <dt>Reference</dt>
            <dd>
              {comparison.reference.revision_id} ·{" "}
              {formatIdentifier(comparison.reference.origin)}
              <br />
              inputs:{" "}
              {comparison.reference.input_revision_ids.join(", ") || "none"}
            </dd>
          </div>
        </dl>
      </section>
      <section>
        <h4>Matching policy</h4>
        <dl className={styles.comparisonFactsList}>
          <div>
            <dt>Policy</dt>
            <dd>{comparison.matching_policy.policy_id}</dd>
          </div>
          <div>
            <dt>Kind</dt>
            <dd>
              {formatIdentifier(
                comparison.matching_policy.kind ?? "unspecified",
              )}
            </dd>
          </div>
          {comparison.matching_policy.anchor !== undefined &&
          comparison.matching_policy.anchor !== null ? (
            <div>
              <dt>Anchor</dt>
              <dd>{comparison.matching_policy.anchor}</dd>
            </div>
          ) : null}
          {comparison.matching_policy.tolerance_us !== undefined &&
          comparison.matching_policy.tolerance_us !== null ? (
            <div>
              <dt>Tolerance</dt>
              <dd>
                {formatMicroseconds(comparison.matching_policy.tolerance_us)}
              </dd>
            </div>
          ) : null}
          {comparison.matching_policy.iou_threshold !== undefined &&
          comparison.matching_policy.iou_threshold !== null ? (
            <div>
              <dt>IoU threshold</dt>
              <dd>{comparison.matching_policy.iou_threshold}</dd>
            </div>
          ) : null}
          {comparison.matching_policy.derived_box_policy !== undefined &&
          comparison.matching_policy.derived_box_policy !== null ? (
            <div>
              <dt>Box policy</dt>
              <dd>
                {formatIdentifier(
                  comparison.matching_policy.derived_box_policy,
                )}
              </dd>
            </div>
          ) : null}
        </dl>
      </section>
      <section>
        <h4>Reviewed scope</h4>
        <dl className={styles.comparisonFactsList}>
          <div>
            <dt>Reviewed intervals</dt>
            <dd>
              {formatIntervals(comparison.scope.reviewed)} ·{" "}
              {comparison.scope.reviewed_frame_identities.length} frame
              identities
            </dd>
          </div>
          <div>
            <dt>Common coverage</dt>
            <dd>
              {formatIntervals(comparison.scope.common_covered)} ·{" "}
              {comparison.scope.common_frame_identities.length} frame identities
            </dd>
          </div>
          <div>
            <dt>Side-only coverage</dt>
            <dd>
              Left {formatIntervals(comparison.scope.left_only)} · Right{" "}
              {formatIntervals(comparison.scope.right_only)}
            </dd>
          </div>
        </dl>
      </section>
      <section>
        <h4>Summary</h4>
        <dl className={styles.comparisonFactsList}>
          <div>
            <dt>Left</dt>
            <dd>{countSummary(leftCounts)}</dd>
          </div>
          <div>
            <dt>Right</dt>
            <dd>{countSummary(rightCounts)}</dd>
          </div>
          {comparison.paired_delta !== null ? (
            <div>
              <dt>Paired quality delta</dt>
              <dd>{metricSummary(comparison.paired_delta)}</dd>
            </div>
          ) : comparison.mode === "upstream_experiment" ? (
            <div>
              <dt>Quality claim</dt>
              <dd>No paired quality claim for an upstream experiment.</dd>
            </div>
          ) : (
            <div>
              <dt>Paired quality delta</dt>
              <dd>Not available for this comparison.</dd>
            </div>
          )}
        </dl>
      </section>
    </div>
  );
}

function ComparisonSourcePanel({
  recordingId,
  comparison,
  contentType,
  item,
  videoRef,
  durationUs,
  onLoadedMetadata,
}: {
  recordingId: string;
  comparison: PipelineComparisonResponse;
  contentType: ComparisonContentType;
  item: ComparisonItem | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  durationUs: number;
  onLoadedMetadata: () => void;
}) {
  if (item === null) {
    return (
      <aside
        className={styles.comparisonSourcePanel}
        aria-label="Comparison source"
      >
        <h4>Source context</h4>
        <p className={styles.detailEmptyState}>
          Select an outcome to inspect its source.
        </p>
      </aside>
    );
  }
  const run = item.side === "left" ? comparison.left : comparison.right;
  const derivedHref =
    item.source_links.derived_view ??
    (item.source_time_us === null
      ? null
      : pipelineDerivedFramePath(recordingId, item.source_time_us));
  const cropId = item.run_card_id ?? item.item_id;
  const cropHref =
    contentType === "visual_identities"
      ? pipelineIdentityCropPath(recordingId, run.revision_id, cropId)
      : null;
  return (
    <aside
      className={styles.comparisonSourcePanel}
      aria-label="Comparison source"
    >
      <div className={styles.comparisonSourceHeading}>
        <div>
          <p className={styles.statusLabel}>Selected outcome</p>
          <h4>{OUTCOME_TEXT[item.outcome]}</h4>
        </div>
        <span
          className={styles.status}
          data-state={item.outcome === "failure" ? "failed" : "complete"}
        >
          {formatIdentifier(item.outcome)}
        </span>
      </div>
      <video
        ref={videoRef}
        className={styles.comparisonVideo}
        src={repositoryBundleVideoPath(recordingId)}
        controls
        preload="metadata"
        aria-label={`Comparison source video ${recordingId}`}
        onLoadedMetadata={onLoadedMetadata}
      />
      <p className={styles.comparisonSourceMeta}>
        {item.source_time_us === null
          ? "This outcome has no exact source time."
          : `Source position ${formatMicroseconds(clampTime(item.source_time_us, durationUs))}.`}
      </p>
      <div className={styles.comparisonSourceLinks}>
        {derivedHref !== null ? (
          <a href={derivedHref} target="_blank" rel="noreferrer">
            Open derived frame
          </a>
        ) : null}
        {cropHref !== null ? (
          <a href={cropHref} target="_blank" rel="noreferrer">
            Open identity crop
          </a>
        ) : null}
        {derivedHref === null && cropHref === null ? (
          <span>No derived source is available.</span>
        ) : null}
      </div>
      <dl className={styles.comparisonSelectedFacts}>
        <div>
          <dt>Item</dt>
          <dd>{item.item_id}</dd>
        </div>
        <div>
          <dt>Run side</dt>
          <dd>
            {formatIdentifier(item.side)} · {run.run_id}
          </dd>
        </div>
        {item.reference_identity !== null || item.run_identity !== null ? (
          <div>
            <dt>Identity</dt>
            <dd>
              Reference {item.reference_identity ?? "none"} · Run{" "}
              {item.run_identity ?? "none"}
            </dd>
          </div>
        ) : null}
        {item.iou !== null ? (
          <div>
            <dt>IoU</dt>
            <dd>{item.iou}</dd>
          </div>
        ) : null}
      </dl>
    </aside>
  );
}

function comparisonContentType(
  stageKey: PipelineStageKey,
): ComparisonContentType | null {
  return stageKey === "events" ||
    stageKey === "visible_cards" ||
    stageKey === "visual_identities"
    ? stageKey
    : null;
}

function comparableRuns(stage: PipelineWorkspaceStage): PipelineRun[] {
  const comparable = new Set(stage.comparable_run_ids);
  return stage.runs
    .filter(
      (run) =>
        comparable.has(run.run_id) &&
        (run.status === "complete" || run.status === "partial"),
    )
    .sort(
      (left, right) =>
        right.created_at.localeCompare(left.created_at) ||
        right.run_id.localeCompare(left.run_id),
    );
}

function defaultComparisonSelection(
  runs: PipelineRun[],
  references: PipelineWorkspaceStage["input_options"],
  stage: PipelineWorkspaceStage,
): { left: string | null; right: string | null; reference: string | null } {
  const pair = newestCompatiblePair(runs);
  const selectedReference =
    stage.selected_completed_reference_revision_id ??
    stage.reference?.selected_completion ??
    null;
  return {
    left: pair?.left.run_id ?? null,
    right: pair?.right.run_id ?? null,
    reference: references.some(
      (option) => option.revision_id === selectedReference,
    )
      ? selectedReference
      : (references[0]?.revision_id ?? null),
  };
}

function newestCompatiblePair(
  runs: PipelineRun[],
): { left: PipelineRun; right: PipelineRun } | null {
  for (let leftIndex = 0; leftIndex < runs.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < runs.length;
      rightIndex += 1
    ) {
      if (
        sameInputs(
          runs[leftIndex].input_revision_ids,
          runs[rightIndex].input_revision_ids,
        )
      ) {
        return { left: runs[leftIndex], right: runs[rightIndex] };
      }
    }
  }
  return runs.length < 2 ? null : { left: runs[0], right: runs[1] };
}

function sameInputs(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function runLabel(run: PipelineRun): string {
  return `${run.run_id} · ${formatIdentifier(run.status)} · ${run.implementation.name} ${run.implementation.version}`;
}

function comparisonPath(
  recordingId: string,
  stage: PipelineStageKey,
  state: PipelineUrlState,
): string {
  const params = new URLSearchParams();
  if (state.view !== null) params.set("view", state.view);
  if (state.revision !== null) params.set("revision", state.revision);
  if (state.item !== null) params.set("item", state.item);
  if (state.tUs !== null) params.set("t_us", String(state.tUs));
  if (state.left !== null) params.set("left", state.left);
  if (state.right !== null) params.set("right", state.right);
  if (state.reference !== null) params.set("reference", state.reference);
  const query = params.toString();
  return `/recordings/${encodeURIComponent(recordingId)}/pipeline/${stage}/compare${query === "" ? "" : `?${query}`}`;
}

function countSummary(
  counts: PipelineComparisonResponse["counts"]["left"],
): string {
  return `${counts.matches} matches · ${counts.misses} misses · ${counts.extras} extras · ${counts.failures} failures · ${counts.not_reviewed} not reviewed`;
}

function metricSummary(
  metrics: PipelineComparisonResponse["paired_delta"],
): string {
  if (metrics === null) return "none";
  return `precision ${formatMetric(metrics.precision)} · recall ${formatMetric(metrics.recall)} · F1 ${formatMetric(metrics.f1)}`;
}

function formatMetric(value: number | null): string {
  return value === null ? "n/a" : value.toFixed(3);
}

function formatIntervals(
  intervals: Array<{ start_us: number; end_us: number }>,
): string {
  if (intervals.length === 0) return "none";
  return intervals
    .map(
      (interval) =>
        `${formatMicroseconds(interval.start_us)}–${formatMicroseconds(interval.end_us)}`,
    )
    .join(", ");
}

function clampTime(value: number, durationUs: number): number {
  return Math.min(Math.max(value, 0), Math.max(durationUs, 0));
}

function formatIdentifier(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (character) => character.toUpperCase());
}

function formatMicroseconds(value: number): string {
  return `${(value / 1_000_000).toFixed(3)}s`;
}

function describeComparisonError(reason: unknown): string {
  if (!(reason instanceof ApiError))
    return "The comparison backend could not be reached.";
  const body =
    typeof reason.body === "object" && reason.body !== null
      ? (reason.body as Record<string, unknown>)
      : null;
  const detail =
    typeof body?.detail === "object" && body.detail !== null
      ? (body.detail as Record<string, unknown>)
      : null;
  const message =
    typeof detail?.message === "string"
      ? detail.message
      : typeof body?.message === "string"
        ? body.message
        : null;
  return message ?? `The backend returned HTTP ${reason.status}.`;
}
