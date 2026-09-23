import type { PipelineProposalRunResponse } from "../api/client";
import type { Point } from "./PipelineVisibleCardTypes";
import styles from "./CalibrationFitDiagnostics.module.css";

export type CalibrationFitDiagnosticOutline = {
  candidateId: string;
  points: Point[];
  status: "fit" | "held_out" | "discarded";
  reason: string | null;
  confidence: number | null;
  qualityScore: number | null;
  medianDistancePx: number | null;
  p90DistancePx: number | null;
  maximumDistancePx: number | null;
};

type DiagnosticEvidence = CalibrationFitDiagnosticOutline & {
  candidateId: string;
  sourceFrameId: string;
};

export type CalibrationFitDiagnostics = {
  failureMessage: string | null;
  failureAction: string | null;
  candidateAvailable: boolean;
  candidateDigest: string | null;
  sourceRevision: string | null;
  candidateYield: Record<string, number>;
  failedGates: string[];
  unavailableGates: string[];
  heldOutSummary: {
    count: number;
    medianDistancePx: number | null;
    p90DistancePx: number | null;
    worstDistancePx: number | null;
    p90DistanceOverShortSide: number | null;
  };
  absoluteSize: {
    status: string;
    shortSideBias: number | null;
    areaBias: number | null;
  };
  evidence: DiagnosticEvidence[];
  worstFrames: Array<{
    sourceFrameId: string;
    candidateId: string;
    maximumDistancePx: number | null;
  }>;
};

type JsonObject = Record<string, unknown>;

export function readCalibrationFitDiagnostics(
  run: PipelineProposalRunResponse | null,
): CalibrationFitDiagnostics | null {
  if (run?.status !== "failed") return null;
  const state = asObject(run.state);
  const runMetrics = asObject(state?.metrics);
  const storedCalibrationRun = asObject(runMetrics?.calibration_run);
  const calibration = asObject(storedCalibrationRun?.calibration_fit_candidate);
  const diagnostics = asObject(storedCalibrationRun?.diagnostics);
  if (storedCalibrationRun === null || diagnostics === null) return null;

  const validation = asObject(diagnostics.validation);
  const heldOut = asObject(validation?.held_out_summary);
  const absoluteSize = asObject(validation?.absolute_size);
  const candidateYieldRaw = asObject(diagnostics.candidate_yield);
  const candidateYield: Record<string, number> = {};
  for (const key of [
    "raw_count",
    "geometry_count",
    "quality_count",
    "accepted_count",
  ]) {
    const value = asNumber(candidateYieldRaw?.[key]);
    if (value !== null) candidateYield[key] = value;
  }

  const evidence = Array.isArray(diagnostics.candidate_evidence)
    ? diagnostics.candidate_evidence
        .map(readEvidence)
        .filter((item): item is DiagnosticEvidence => item !== null)
    : [];
  const fitIds = new Set(asStringArray(calibration?.fit_observation_ids));
  const heldOutIds = new Set(
    asStringArray(calibration?.held_out_observation_ids),
  );
  for (const item of evidence) {
    item.status = fitIds.has(item.candidateId)
      ? "fit"
      : heldOutIds.has(item.candidateId)
        ? "held_out"
        : "discarded";
  }
  const heldEvidence =
    calibration === null
      ? []
      : evidence.filter((item) => heldOutIds.has(item.candidateId));
  const worstFrames = [...heldEvidence]
    .filter((item) => item.sourceFrameId !== "")
    .sort(
      (left, right) =>
        (right.maximumDistancePx ?? -1) - (left.maximumDistancePx ?? -1) ||
        left.sourceFrameId.localeCompare(right.sourceFrameId) ||
        left.candidateId.localeCompare(right.candidateId),
    )
    .filter(
      (item, index, values) =>
        values.findIndex(
          (other) => other.sourceFrameId === item.sourceFrameId,
        ) === index,
    )
    .slice(0, 5)
    .map((item) => ({
      sourceFrameId: item.sourceFrameId,
      candidateId: item.candidateId,
      maximumDistancePx: item.maximumDistancePx,
    }));

  const failure = asObject(storedCalibrationRun.failure);
  return {
    failureMessage: asString(failure?.message),
    failureAction: asString(failure?.action),
    candidateAvailable: calibration !== null,
    candidateDigest: asString(calibration?.candidate_digest),
    sourceRevision: asString(calibration?.source_revision),
    candidateYield,
    failedGates: asStringArray(diagnostics.failed_gates),
    unavailableGates: asStringArray(diagnostics.unavailable_gates),
    heldOutSummary: {
      count: asNumber(heldOut?.count) ?? 0,
      medianDistancePx: asNumber(heldOut?.median_boundary_distance_px),
      p90DistancePx: asNumber(heldOut?.p90_boundary_distance_px),
      worstDistancePx: asNumber(heldOut?.worst_boundary_distance_px),
      p90DistanceOverShortSide: asNumber(
        heldOut?.p90_boundary_distance_over_short_side,
      ),
    },
    absoluteSize: {
      status: asString(absoluteSize?.status) ?? "unavailable",
      shortSideBias: asNumber(absoluteSize?.short_side_bias),
      areaBias: asNumber(absoluteSize?.area_bias),
    },
    evidence,
    worstFrames,
  };
}

export function calibrationFitOutlinesForFrame(
  diagnostics: CalibrationFitDiagnostics | null,
  sourceFrameId: string,
  visibleStatuses: ReadonlySet<CalibrationFitDiagnosticOutline["status"]>,
): CalibrationFitDiagnosticOutline[] {
  if (diagnostics === null) return [];
  return diagnostics.evidence
    .filter(
      (item) =>
        item.sourceFrameId === sourceFrameId &&
        visibleStatuses.has(item.status),
    )
    .map((item) => ({
      candidateId: item.candidateId,
      points: item.points,
      status: item.status,
      reason: item.reason,
      confidence: item.confidence,
      qualityScore: item.qualityScore,
      medianDistancePx: item.medianDistancePx,
      p90DistancePx: item.p90DistancePx,
      maximumDistancePx: item.maximumDistancePx,
    }));
}

export function CalibrationFitDiagnosticsPanel({
  diagnostics,
  onSelectFrame,
  visibleStatuses,
  onToggleStatus,
}: {
  diagnostics: CalibrationFitDiagnostics | null;
  onSelectFrame: (sourceFrameId: string) => void;
  visibleStatuses: ReadonlySet<CalibrationFitDiagnosticOutline["status"]>;
  onToggleStatus: (status: CalibrationFitDiagnosticOutline["status"]) => void;
}) {
  if (diagnostics === null) return null;
  const heldOut = diagnostics.heldOutSummary;
  const outlinesAvailable = diagnostics.evidence.some(
    (item) => item.points.length >= 4,
  );
  const yieldLabel =
    diagnostics.candidateYield.raw_count === undefined ||
    diagnostics.candidateYield.accepted_count === undefined
      ? "unavailable"
      : `${diagnostics.candidateYield.accepted_count} accepted of ${diagnostics.candidateYield.raw_count} predictions`;

  return (
    <section
      className={styles.panel}
      aria-label="Calibration fit diagnostic"
      data-diagnostic-only="true"
    >
      <p className={styles.kicker}>Failed calibration · diagnostic only</p>
      <h4>Calibration fit candidate</h4>
      <p className={styles.description}>
        {outlinesAvailable
          ? "Read-only card outlines and metrics show which detections contributed to this fit. This candidate is not published and cannot change reviewed data."
          : "This stored run has no projected outlines. Retry the proposal run to inspect them beside the detector polygons. The candidate is not published and cannot change reviewed data."}
      </p>
      <div
        className={styles.overlayFilters}
        aria-label="Calibration card overlays"
      >
        {(["fit", "held_out", "discarded"] as const).map((status) => (
          <label key={status} className={styles[status]}>
            <input
              type="checkbox"
              checked={visibleStatuses.has(status)}
              onChange={() => onToggleStatus(status)}
            />
            {status === "fit"
              ? "Used for fit"
              : status === "held_out"
                ? "Held out"
                : "Discarded"}
            {` (${diagnostics.evidence.filter((item) => item.status === status).length})`}
          </label>
        ))}
      </div>
      {diagnostics.failureMessage !== null ? (
        <p className={styles.failure}>{diagnostics.failureMessage}</p>
      ) : null}
      {diagnostics.failureAction !== null ? (
        <p className={styles.action}>{diagnostics.failureAction}</p>
      ) : null}
      <dl className={styles.facts}>
        <div>
          <dt>Candidate yield</dt>
          <dd>{yieldLabel}</dd>
        </div>
        <div>
          <dt>Held-out boundary distance</dt>
          <dd>
            {heldOut.count === 0
              ? "unavailable · no independent held-out cards"
              : `${formatPx(heldOut.medianDistancePx)} median · ${formatPx(heldOut.p90DistancePx)} P90 · ${formatPx(heldOut.worstDistancePx)} worst`}
          </dd>
        </div>
        <div>
          <dt>P90 of projected short side</dt>
          <dd>
            {heldOut.p90DistanceOverShortSide === null
              ? "unavailable"
              : `${(heldOut.p90DistanceOverShortSide * 100).toFixed(2)}%`}
          </dd>
        </div>
        <div>
          <dt>Optional size comparison</dt>
          <dd>{diagnostics.absoluteSize.status}</dd>
        </div>
        <div>
          <dt>Short-side bias</dt>
          <dd>{formatPercent(diagnostics.absoluteSize.shortSideBias)}</dd>
        </div>
        <div>
          <dt>Area bias</dt>
          <dd>{formatPercent(diagnostics.absoluteSize.areaBias)}</dd>
        </div>
      </dl>
      <div className={styles.gates}>
        <strong>Failed gates</strong>
        {diagnostics.failedGates.length === 0 ? (
          <span>Unavailable</span>
        ) : (
          <ul>
            {diagnostics.failedGates.map((gate) => (
              <li key={gate}>
                {formatGate(gate)}
                {diagnostics.unavailableGates.includes(gate)
                  ? " · unavailable"
                  : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
      {diagnostics.candidateAvailable ? (
        <p className={styles.digest}>
          Candidate {diagnostics.candidateDigest ?? "digest unavailable"}
        </p>
      ) : (
        <p className={styles.action}>
          No finite calibration fit candidate is available.
        </p>
      )}
      {diagnostics.sourceRevision !== null ? (
        <p className={styles.digest}>
          Source revision {diagnostics.sourceRevision}
        </p>
      ) : null}
      {diagnostics.worstFrames.length > 0 ? (
        <div className={styles.worstFrames}>
          <strong>Worst held-out frames</strong>
          {diagnostics.worstFrames.map((frame, index) => (
            <button
              className={styles.frameButton}
              key={`${frame.sourceFrameId}:${frame.candidateId}`}
              type="button"
              onClick={() => onSelectFrame(frame.sourceFrameId)}
            >
              {`Open worst fit ${index + 1} · ${frame.sourceFrameId} · ${formatPx(frame.maximumDistancePx)} max`}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function readEvidence(value: unknown): DiagnosticEvidence | null {
  const item = asObject(value);
  const candidateId = asString(item?.candidate_id);
  const sourceFrameId = asString(item?.source_frame_id);
  if (item === null || candidateId === null || sourceFrameId === null)
    return null;
  const residual = asObject(item.residual);
  const quality = asObject(item.quality_metrics);
  return {
    candidateId,
    sourceFrameId,
    points: readPoints(item.projected_full_card_outline),
    status: "discarded",
    reason: asString(item.rejection_reason),
    confidence: asNumber(item.confidence),
    qualityScore: asNumber(quality?.quality_score),
    medianDistancePx: asNumber(residual?.median_boundary_distance_px),
    p90DistancePx: asNumber(residual?.p90_boundary_distance_px),
    maximumDistancePx: asNumber(residual?.maximum_boundary_distance_px),
  };
}

function readPoints(value: unknown): Point[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((rawPoint) => {
    if (!Array.isArray(rawPoint) || rawPoint.length !== 2) return [];
    const x = asNumber(rawPoint[0]);
    const y = asNumber(rawPoint[1]);
    return x === null || y === null ? [] : [{ x, y }];
  });
}

function asObject(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function formatPx(value: number | null): string {
  return value === null ? "unavailable" : `${value.toFixed(2)} px`;
}

function formatPercent(value: number | null): string {
  return value === null ? "unavailable" : `${(value * 100).toFixed(2)}%`;
}

function formatGate(value: string): string {
  return value
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}
