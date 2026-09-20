import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createDokoDetectorClient,
  type PipelineRun,
  type PipelineRunResponse,
  type PipelineRunStartRequest,
  type PipelineStageKey,
  type PipelineWorkspaceStage,
} from "../api/client";
import styles from "../App.module.css";
import {
  ProbabilityOverlay,
  readProbabilityMetrics,
} from "./ProbabilityOverlay";

type RunStageKey = Extract<
  PipelineStageKey,
  "events" | "visible_cards" | "visual_identities"
>;
type InputOrigin = "generated" | "reviewed";
type ProcessorOrigin = "cloud" | "local";
type VisibleCardModelVariant =
  | "gemini"
  | "local"
  | "local-rfdetr-segmentation"
  | "local-rfdetr-cascade"
  | "local-rfdetr-cascade-0068"
  | "local-rfdetr-cascade-0070";

const VISIBLE_CARD_MODEL_VARIANTS: readonly {
  value: VisibleCardModelVariant;
  label: string;
}[] = [
  { value: "gemini", label: "Cloud · Gemini" },
  { value: "local", label: "Local · configured legacy provider" },
  {
    value: "local-rfdetr-segmentation",
    label: "Local · RF-DETR segmentation",
  },
  {
    value: "local-rfdetr-cascade",
    label: "Local · RF-DETR cascade (configured)",
  },
  {
    value: "local-rfdetr-cascade-0068",
    label: "Local · RF-DETR cascade · 0068 reviewed",
  },
  {
    value: "local-rfdetr-cascade-0070",
    label: "Local · RF-DETR cascade · 0070 synthetic",
  },
];

const RUN_STAGE_KEYS: readonly RunStageKey[] = [
  "events",
  "visible_cards",
  "visual_identities",
];

const RUN_STAGE_LABELS: Record<RunStageKey, string> = {
  events: "event detection",
  visible_cards: "visible-card detection",
  visual_identities: "visual identity classification",
};

const UPSTREAM_STAGE: Record<Exclude<RunStageKey, "events">, RunStageKey> = {
  visible_cards: "events",
  visual_identities: "visible_cards",
};

const TERMINAL_STATES = new Set(["complete", "partial", "failed"]);

type RunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
  compact?: boolean;
};

type RunFacts = {
  run_id: string;
  status: string;
  attempt: number;
  request: Record<string, unknown>;
  state: Record<string, unknown>;
};

export function RunControls({
  recordingId,
  stage,
  stages,
  onRefresh,
  compact = false,
}: RunControlsProps) {
  const client = useMemo(() => createDokoDetectorClient(), []);
  const isRunStage = RUN_STAGE_KEYS.includes(stage.key as RunStageKey);
  const runStage = isRunStage ? (stage.key as RunStageKey) : null;
  const upstreamStage =
    runStage !== null && runStage !== "events"
      ? stages.find((candidate) => candidate.key === UPSTREAM_STAGE[runStage])
      : undefined;
  const generatedRevisionId =
    upstreamStage?.selected_generated_revision_id ?? null;
  const reviewedRevisionId =
    upstreamStage?.selected_completed_reference_revision_id ?? null;
  const [inputOrigin, setInputOrigin] = useState<InputOrigin>(() =>
    reviewedRevisionId === null ? "generated" : "reviewed",
  );
  const [processorOrigin, setProcessorOrigin] =
    useState<ProcessorOrigin>("cloud");
  const [visibleCardModelVariant, setVisibleCardModelVariant] =
    useState<VisibleCardModelVariant>(() =>
      initialVisibleCardModelVariant(stage.runs[0]),
    );
  const [historicalRevisionId, setHistoricalRevisionId] = useState<string>("");
  const [trackedRunId, setTrackedRunId] = useState<string | null>(
    () =>
      stage.runs.find(
        (run) => run.status === "queued" || run.status === "running",
      )?.run_id ?? null,
  );
  const [liveRun, setLiveRun] = useState<PipelineRunResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const selectedRevisionId =
    historicalRevisionId ||
    (inputOrigin === "reviewed" ? reviewedRevisionId : generatedRevisionId);
  const selectedRun = useMemo(
    () =>
      liveRun !== null && liveRun.run_id === trackedRunId
        ? liveRun
        : trackedRunId === null
          ? null
          : (stage.runs.find((run) => run.run_id === trackedRunId) ?? null),
    [liveRun, stage.runs, trackedRunId],
  );
  const latestRun = stage.runs[0] ?? null;

  const getRun = useCallback(
    (runId: string, init?: RequestInit): Promise<PipelineRunResponse> => {
      if (runStage === "events") {
        return client.getEventRun(recordingId, runId, init);
      }
      if (runStage === "visible_cards") {
        return client.getVisibleCardRun(recordingId, runId, init);
      }
      return client.getVisualIdentityRun(recordingId, runId, init);
    },
    [client, recordingId, runStage],
  );

  useEffect(() => {
    if (runStage === null || trackedRunId === null) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const response = await getRun(trackedRunId);
        if (cancelled) {
          return;
        }
        setLiveRun(response);
        if (TERMINAL_STATES.has(response.status)) {
          await onRefresh();
          return;
        }
        timer = window.setTimeout(() => void poll(), 1000);
      } catch (reason: unknown) {
        if (!cancelled) {
          setMessage(describeRunError(reason));
          timer = window.setTimeout(() => void poll(), 1000);
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [getRun, onRefresh, runStage, trackedRunId]);

  const setOrigin = (origin: InputOrigin) => {
    setInputOrigin(origin);
    setHistoricalRevisionId("");
    setMessage(null);
  };

  const startRun = async () => {
    if (
      runStage === null ||
      (runStage !== "events" && selectedRevisionId === null)
    ) {
      setMessage(
        "Select a complete compatible input before starting the processor.",
      );
      return;
    }
    setBusy(true);
    setMessage(null);
    const runId = createRunId(runStage);
    try {
      const response = await startProcessorRun(
        client,
        recordingId,
        runStage,
        buildRunRequest(
          runStage,
          runId,
          selectedRevisionId,
          latestRun,
          inputOrigin,
          processorOrigin,
          visibleCardModelVariant,
        ),
      );
      setLiveRun(response);
      setTrackedRunId(response.run_id);
      await onRefresh();
    } catch (reason: unknown) {
      setMessage(describeRunError(reason));
    } finally {
      setBusy(false);
    }
  };

  const retryRun = async (runId: string) => {
    if (runStage === null) {
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const response = await retryProcessorRun(
        client,
        recordingId,
        runStage,
        runId,
      );
      setLiveRun(response);
      setTrackedRunId(response.run_id);
      await onRefresh();
    } catch (reason: unknown) {
      setMessage(describeRunError(reason));
    } finally {
      setBusy(false);
    }
  };

  if (runStage === null) {
    return null;
  }

  const historicalOptions = upstreamStage?.input_options ?? [];
  const hasGenerated = generatedRevisionId !== null;
  const hasReviewed = reviewedRevisionId !== null;
  const canStart =
    stage.can_run && (runStage === "events" || selectedRevisionId !== null);

  return (
    <section
      className={`${styles.pipelineRunControls} ${compact ? styles.pipelineRunControlsCompact : ""}`}
      aria-labelledby={compact ? undefined : "run-controls-heading"}
    >
      {!compact ? (
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.statusLabel}>Processor controls</p>
            <h3 id="run-controls-heading">Run {RUN_STAGE_LABELS[runStage]}</h3>
          </div>
          {selectedRun !== null ? (
            <StatusBadge value={selectedRun.status} />
          ) : null}
        </div>
      ) : null}

      {stage.run_blockers.length > 0 ? (
        <p className={styles.detailBlocker}>{stage.run_blockers[0]}</p>
      ) : (
        <>
          <div className={styles.pipelineRunForm}>
            <div>
              <span className={styles.statusLabel}>
                Input used by the next run
              </span>
              {runStage === "events" ? (
                <p className={styles.pipelineRunInputValue}>
                  Accepted recording video
                </p>
              ) : (
                <div
                  className={styles.pipelineToggleGroup}
                  role="group"
                  aria-label="Input origin"
                >
                  <button
                    className={
                      inputOrigin === "generated"
                        ? styles.pipelineToggleActive
                        : styles.pipelineToggle
                    }
                    type="button"
                    aria-pressed={inputOrigin === "generated"}
                    disabled={!hasGenerated || busy}
                    onClick={() => setOrigin("generated")}
                  >
                    Generated
                  </button>
                  <button
                    className={
                      inputOrigin === "reviewed"
                        ? styles.pipelineToggleActive
                        : styles.pipelineToggle
                    }
                    type="button"
                    aria-pressed={inputOrigin === "reviewed"}
                    disabled={!hasReviewed || busy}
                    onClick={() => setOrigin("reviewed")}
                  >
                    Reviewed
                  </button>
                </div>
              )}
              {runStage !== "events" ? (
                <p className={styles.pipelineRunInputValue}>
                  {selectedRevisionId === null
                    ? "No compatible revision selected"
                    : `${inputOrigin === "reviewed" && !historicalRevisionId ? "Reviewed" : "Exact historical"} · ${selectedRevisionId}`}
                </p>
              ) : null}
              {runStage === "visible_cards" ? (
                <label className={styles.pipelineRunSelector}>
                  <span>Model variant used by the next run</span>
                  <select
                    aria-label="Model variant"
                    value={visibleCardModelVariant}
                    disabled={busy}
                    onChange={(event) => {
                      setVisibleCardModelVariant(
                        event.target.value as VisibleCardModelVariant,
                      );
                      setMessage(null);
                    }}
                  >
                    {VISIBLE_CARD_MODEL_VARIANTS.map((variant) => (
                      <option key={variant.value} value={variant.value}>
                        {variant.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : runStage === "visual_identities" ? (
                <div className={styles.pipelineRunProcessorChoice}>
                  <span className={styles.statusLabel}>
                    Processor used by the next run
                  </span>
                  <div
                    className={styles.pipelineToggleGroup}
                    role="group"
                    aria-label="Processor provider"
                  >
                    <button
                      className={
                        processorOrigin === "cloud"
                          ? styles.pipelineToggleActive
                          : styles.pipelineToggle
                      }
                      type="button"
                      aria-pressed={processorOrigin === "cloud"}
                      disabled={busy}
                      onClick={() => setProcessorOrigin("cloud")}
                    >
                      Cloud
                    </button>
                    <button
                      className={
                        processorOrigin === "local"
                          ? styles.pipelineToggleActive
                          : styles.pipelineToggle
                      }
                      type="button"
                      aria-pressed={processorOrigin === "local"}
                      disabled={busy}
                      onClick={() => setProcessorOrigin("local")}
                    >
                      Local
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
            <button
              className={styles.primaryButton}
              type="button"
              disabled={!canStart || busy}
              onClick={() => void startRun()}
            >
              {busy
                ? "Starting…"
                : latestRun === null
                  ? "Run processor"
                  : "Run again"}
            </button>
          </div>

          {runStage !== "events" ? (
            <details className={styles.pipelineRunHistory}>
              <summary>Use another retained revision</summary>
              <label className={styles.pipelineRunSelector}>
                <span>Exact input revision</span>
                <select
                  aria-label="Exact input revision"
                  value={historicalRevisionId}
                  disabled={busy || historicalOptions.length === 0}
                  onChange={(event) =>
                    setHistoricalRevisionId(event.target.value)
                  }
                >
                  <option value="">Use the selected {inputOrigin} input</option>
                  {historicalOptions.map((option) => (
                    <option key={option.revision_id} value={option.revision_id}>
                      {option.display_label} · {option.revision_id}
                    </option>
                  ))}
                </select>
              </label>
            </details>
          ) : null}
        </>
      )}

      {message !== null ? (
        <p className={styles.pipelineRunMessage} role="alert">
          {message}
        </p>
      ) : null}

      {selectedRun !== null ? (
        <RunStatus
          run={selectedRun}
          onRetry={retryRun}
          busy={busy}
          showProbabilities={runStage === "events"}
        />
      ) : null}

      {stage.runs.length > 0 ? (
        <details className={styles.pipelineRunHistory}>
          <summary>Retained runs and actual inputs</summary>
          <ul className={styles.pipelineRunList}>
            {stage.runs.map((run) => (
              <li key={run.run_id}>
                <button
                  className={styles.pipelineRunSelectButton}
                  type="button"
                  aria-pressed={run.run_id === trackedRunId}
                  onClick={() => {
                    setTrackedRunId(run.run_id);
                    setLiveRun(null);
                    setMessage(null);
                  }}
                >
                  <span>{run.run_id}</span>
                  <StatusBadge value={run.status} />
                </button>
                <span>
                  {run.input_revision_ids.length === 0
                    ? "Accepted recording video"
                    : `Input ${run.input_revision_ids.join(", ")}`}
                </span>
                <span>
                  {run.implementation.name} {run.implementation.version}
                  {run.model === null ? " · no model" : " · model retained"}
                </span>
                {run.failure !== null && run.failure !== undefined ? (
                  <span>{run.failure.message}</span>
                ) : null}
                {run.status === "failed" || run.status === "partial" ? (
                  <button
                    className={styles.detailButton}
                    type="button"
                    disabled={busy}
                    onClick={() => void retryRun(run.run_id)}
                  >
                    Retry same run
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function RunStatus({
  run,
  onRetry,
  busy,
  showProbabilities,
}: {
  run: RunFacts;
  onRetry: (runId: string) => Promise<void>;
  busy: boolean;
  showProbabilities: boolean;
}) {
  const [probabilitiesOpen, setProbabilitiesOpen] = useState(false);
  const state = run.state;
  const progress = readObject(state.progress);
  const completed = readNumber(progress?.completed);
  const total = readNumber(progress?.total);
  const failure = readObject(state.terminal_failure);
  const failureMessage = readString(failure?.message);
  const probabilityMetrics = showProbabilities
    ? readProbabilityMetrics(state)
    : null;
  const closeProbabilities = useCallback(() => setProbabilitiesOpen(false), []);
  const message =
    run.status === "complete"
      ? "The processor completed and retained its output revision."
      : run.status === "partial"
        ? "The processor returned a partial result. Review the successful items or retry the same frozen request."
        : run.status === "failed"
          ? "The processor failed. Retry keeps the run ID and exact frozen inputs."
          : run.status === "queued"
            ? "The processor request is queued."
            : "The processor is running.";
  return (
    <div className={styles.pipelineRunStatus} role="status">
      <p>{message}</p>
      {completed !== null && total !== null ? (
        <p>
          Progress: {completed} / {total} items
        </p>
      ) : null}
      {failureMessage !== null ? <p>{failureMessage}</p> : null}
      <dl className={styles.pipelineRunFacts}>
        <div>
          <dt>Run</dt>
          <dd>{run.run_id}</dd>
        </div>
        <div>
          <dt>Attempt</dt>
          <dd>{run.attempt}</dd>
        </div>
        <div>
          <dt>Input revisions</dt>
          <dd>{formatRequestList(run.request.input_revision_ids)}</dd>
        </div>
        <div>
          <dt>Implementation</dt>
          <dd>{formatIdentity(run.request.implementation)}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{formatValue(run.request.model)}</dd>
        </div>
        <div>
          <dt>Configuration</dt>
          <dd>{formatValue(run.request.configuration)}</dd>
        </div>
        <div>
          <dt>Extraction policy</dt>
          <dd>{formatValue(run.request.extraction_policy)}</dd>
        </div>
        <div>
          <dt>Crop policy</dt>
          <dd>{formatValue(run.request.crop_policy)}</dd>
        </div>
      </dl>
      {run.status === "failed" || run.status === "partial" ? (
        <button
          className={styles.detailButton}
          type="button"
          disabled={busy}
          onClick={() => void onRetry(run.run_id)}
        >
          Retry same run
        </button>
      ) : null}
      {probabilityMetrics !== null ? (
        <button
          className={styles.detailButton}
          type="button"
          onClick={() => setProbabilitiesOpen(true)}
        >
          Show probabilities
        </button>
      ) : null}
      {probabilitiesOpen && probabilityMetrics !== null ? (
        <ProbabilityOverlay
          metrics={probabilityMetrics}
          runId={run.run_id}
          onClose={closeProbabilities}
        />
      ) : null}
    </div>
  );
}

async function startProcessorRun(
  client: ReturnType<typeof createDokoDetectorClient>,
  recordingId: string,
  stage: RunStageKey,
  payload: PipelineRunStartRequest,
): Promise<PipelineRunResponse> {
  if (stage === "events") {
    return client.startEventRun(recordingId, payload);
  }
  if (stage === "visible_cards") {
    return client.startVisibleCardRun(recordingId, payload);
  }
  return client.startVisualIdentityRun(recordingId, payload);
}

async function retryProcessorRun(
  client: ReturnType<typeof createDokoDetectorClient>,
  recordingId: string,
  stage: RunStageKey,
  runId: string,
): Promise<PipelineRunResponse> {
  if (stage === "events") {
    return client.retryEventRun(recordingId, runId);
  }
  if (stage === "visible_cards") {
    return client.retryVisibleCardRun(recordingId, runId);
  }
  return client.retryVisualIdentityRun(recordingId, runId);
}

function buildRunRequest(
  stage: RunStageKey,
  runId: string,
  inputRevisionId: string | null,
  latestRun: PipelineRun | null,
  inputOrigin: InputOrigin,
  processorOrigin: ProcessorOrigin = "cloud",
  visibleCardModelVariant: VisibleCardModelVariant = "gemini",
): PipelineRunStartRequest {
  const request = latestRun?.request ?? {};
  const implementation =
    latestRun?.implementation ??
    (stage === "events"
      ? { name: "cardeventnet", version: "file-v1" }
      : stage === "visible_cards"
        ? { name: "visible-card-detector-adapter", version: "v1" }
        : { name: "visual-identity-classifier-adapter", version: "v1" });
  const configuration = {
    ...(latestRun?.configuration ?? readRecord(request.configuration) ?? {}),
    ...(stage === "visible_cards"
      ? { provider: visibleCardModelVariant }
      : stage === "visual_identities"
        ? { provider: processorOrigin === "cloud" ? "gemini" : "local" }
        : {}),
  };
  const extractionPolicy =
    latestRun?.extraction_policy ??
    (stage === "events"
      ? { policy_id: "exact-event/v1" }
      : { policy_id: "exact-event/v1", output_encoding: "jpeg" });
  const cropPolicy =
    stage === "visual_identities"
      ? {
          policy_id:
            inputOrigin === "reviewed"
              ? "oracle_visible_region"
              : "predicted_visible_region",
          output_encoding: "ppm",
        }
      : null;
  const model = latestRun?.model ?? readRecord(request.model) ?? undefined;
  return {
    request: {
      run_id: runId,
      ...(inputRevisionId === null
        ? { input_revision_ids: [] }
        : {
            input_revision_ids: [inputRevisionId],
            ...(stage === "visible_cards"
              ? { event_revision_id: inputRevisionId }
              : { visible_card_revision_id: inputRevisionId }),
          }),
      implementation,
      ...(model === undefined ? {} : { model }),
      configuration,
      extraction_policy: extractionPolicy,
      crop_policy: cropPolicy,
    },
  };
}

function initialVisibleCardModelVariant(
  run: PipelineRun | undefined,
): VisibleCardModelVariant {
  const provider = readString(
    readObject(run?.configuration)?.provider ??
      readObject(run?.request.configuration)?.provider,
  );
  return VISIBLE_CARD_MODEL_VARIANTS.some(
    (variant) => variant.value === provider,
  )
    ? (provider as VisibleCardModelVariant)
    : "gemini";
}

function createRunId(stage: RunStageKey): string {
  const suffix =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().slice(0, 12)
      : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${stage}-run-${suffix}`;
}

function describeRunError(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return "The processor request could not reach the backend. The request is not recorded.";
  }
  const detail = readObject(
    reason.body && typeof reason.body === "object" ? reason.body : null,
  );
  const nested = readObject(detail?.detail);
  const stableError = readObject(detail?.error);
  const backendMessage =
    readString(stableError?.message) ??
    readString(nested?.message) ??
    readString(detail?.message);
  if (backendMessage?.toLowerCase().includes("checkpoint")) {
    return backendMessage;
  }
  if (
    backendMessage?.toLowerCase().includes("video") ||
    backendMessage?.toLowerCase().includes("recording")
  ) {
    return `The accepted recording video is unavailable: ${backendMessage}`;
  }
  if (reason.status === 404) {
    return "The accepted recording video or selected pipeline input is missing.";
  }
  if (reason.status === 422) {
    return backendMessage === null
      ? "The selected input is incompatible with this processor. Choose a complete upstream revision."
      : `The selected input is incompatible with this processor: ${backendMessage}`;
  }
  return (
    backendMessage ?? `The processor request failed with HTTP ${reason.status}.`
  );
}

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return readObject(value);
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function formatRequestList(value: unknown): string {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value.join(", ") || "Accepted recording video"
    : "Unavailable";
}

function formatIdentity(value: unknown): string {
  const record = readObject(value);
  if (record === null) {
    return "Unavailable";
  }
  const name = readString(record.name);
  const version = readString(record.version);
  return name === null
    ? "Unavailable"
    : version === null
      ? name
      : `${name} ${version}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

function StatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
