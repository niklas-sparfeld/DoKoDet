import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "../api/transport";
import { createJobsClient } from "../api/jobsClient";
import { createPipelineProcessingClient } from "../api/pipelineProcessingClient";
import {
  type PipelineRun,
  type PipelineRunResponse,
  type PipelineRunStartRequest,
  type PipelineStageKey,
  type PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import { type EnqueueJobBody } from "../api/jobsContracts";
import styles from "../App.module.css";
import { JobStartActions } from "../jobs/JobStartActions";
import { useJobSubmission } from "../jobs/useJobSubmission";
import {
  ProbabilityOverlay,
  readProbabilityMetrics,
} from "./ProbabilityOverlay";
import { readRunActivity } from "./ObservationRunFormatting";

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
  | "local-rfdetr-fine-frame"
  | "local-rfdetr-crop-review";
type CropInputKind =
  | "gemini_polygon"
  | "rfdetr_segment"
  | "proposed_virtual_cards"
  | "reviewed_virtual_card"
  | "reviewed_visible_card";
type CropInputOption = {
  kind: CropInputKind;
  revisionId: string;
  nodeRef: {
    node_id: string;
    revision_id: string;
    revision_policy: "current_head" | "historical";
  };
  label: string;
};

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
    value: "local-rfdetr-fine-frame",
    label: "Local · RF-DETR fine-frame refinement",
  },
  {
    value: "local-rfdetr-crop-review",
    label: "Local · RF-DETR crop refinement review",
  },
];

const RUN_STAGE_KEYS: readonly RunStageKey[] = [
  "events",
  "visible_cards",
  "visual_identities",
];

const UPSTREAM_STAGE: Record<Exclude<RunStageKey, "events">, RunStageKey> = {
  visible_cards: "events",
  visual_identities: "visible_cards",
};

type RunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
};

type RunFacts = {
  run_id: string;
  job_id?: string | null;
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
}: RunControlsProps) {
  const client = useMemo(
    () => ({ ...createJobsClient(), ...createPipelineProcessingClient() }),
    [],
  );
  const isRunStage = RUN_STAGE_KEYS.includes(stage.key as RunStageKey);
  const runStage = isRunStage ? (stage.key as RunStageKey) : null;
  const upstreamStage =
    runStage !== null && runStage !== "events"
      ? stages.find((candidate) => candidate.key === UPSTREAM_STAGE[runStage])
      : undefined;
  const generatedRevisionId =
    upstreamStage?.selected_generated?.revision_id ?? null;
  const reviewedRevisionId =
    upstreamStage?.selected_completed_reference?.revision_id ?? null;
  const [inputOrigin, setInputOrigin] = useState<InputOrigin>(() =>
    reviewedRevisionId === null ? "generated" : "reviewed",
  );
  const processorOrigin: ProcessorOrigin = "cloud";
  const [identityProviderState, setIdentityProviderState] = useState<{
    recordingId: string;
    provider: ProcessorOrigin;
  }>({ recordingId, provider: "local" });
  const [visibleCardModelVariant, setVisibleCardModelVariant] =
    useState<VisibleCardModelVariant>(() =>
      initialVisibleCardModelVariant(stage.runs[0]),
    );
  const [historicalRevisionId, setHistoricalRevisionId] = useState<string>("");
  const [cropInputSelection, setCropInputSelection] = useState("");
  const [identityCropPolicyState, setIdentityCropPolicyState] = useState<{
    recordingId: string;
    policy: string;
  }>({ recordingId, policy: "" });
  const [proposedCropInputs, setProposedCropInputs] = useState<
    Array<{
      node_id: string;
      revision_id: string;
      created_at: string;
      detector_revision_id: string;
      calibration_revision_id: string;
      supported_frame_count: number;
      unsupported_frame_count: number;
    }>
  >([]);
  const [proposedCropInputsLoadedFor, setProposedCropInputsLoadedFor] =
    useState<string | null>(null);
  const [trackedRunId, setTrackedRunId] = useState<string | null>(
    () =>
      stage.runs.find(
        (run) => run.status === "queued" || run.status === "running",
      )?.run_id ?? null,
  );
  const [liveRun, setLiveRun] = useState<PipelineRunResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const enqueue = useCallback(
    (payload: EnqueueJobBody, key: string) => client.enqueueJob(payload, key),
    [client],
  );
  const eventSubmission = useJobSubmission(enqueue);
  const visibleCardSubmission = useJobSubmission(enqueue);
  useEffect(() => {
    if (runStage !== "visual_identities") return;
    const controller = new AbortController();
    void client
      .listVisualIdentityProposedCropInputs(recordingId, {
        signal: controller.signal,
      })
      .then((response) => {
        setProposedCropInputs(
          Array.isArray(response.inputs) ? response.inputs : [],
        );
        setProposedCropInputsLoadedFor(recordingId);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setProposedCropInputs([]);
          setMessage(describeRunError(reason));
          setProposedCropInputsLoadedFor(recordingId);
        }
      });
    return () => controller.abort();
  }, [client, recordingId, runStage]);
  const cropInputOptions =
    runStage === "visual_identities" && upstreamStage !== undefined
      ? [
          ...buildCropInputOptions(upstreamStage),
          ...(proposedCropInputsLoadedFor === recordingId
            ? proposedCropInputs
            : []
          ).map((input) => ({
            kind: "proposed_virtual_cards" as const,
            revisionId: input.revision_id,
            nodeRef: {
              node_id: input.node_id,
              revision_id: input.revision_id,
              revision_policy: "historical" as const,
            },
            label: `Proposed virtual cards · ${input.revision_id} · ${input.supported_frame_count} supported frames · calibration ${input.calibration_revision_id}`,
          })),
        ]
      : [];
  const selectedCropInput =
    cropInputOptions.find(
      (option) =>
        cropInputKey(option) ===
        (cropInputSelection.startsWith(`${recordingId}::`)
          ? cropInputSelection.slice(recordingId.length + 2)
          : ""),
    ) ?? (cropInputOptions.length === 1 ? cropInputOptions[0] : null);
  const selectedProcessorOrigin =
    selectedCropInput?.kind === "proposed_virtual_cards"
      ? "local"
      : runStage === "visual_identities"
        ? identityProviderState.recordingId === recordingId
          ? identityProviderState.provider
          : "local"
        : processorOrigin;
  const identityCropPolicy =
    identityCropPolicyState.recordingId === recordingId
      ? identityCropPolicyState.policy
      : "";
  const identityCropPolicyOptions = selectedCropInput
    ? cropPolicyOptions(selectedCropInput.kind)
    : [];
  const selectedIdentityCropPolicy = identityCropPolicyOptions.some(
    (policy) => policy.value === identityCropPolicy,
  )
    ? identityCropPolicy
    : (identityCropPolicyOptions[0]?.value ?? "");
  const selectedRevisionId =
    runStage === "visual_identities"
      ? (selectedCropInput?.revisionId ?? null)
      : historicalRevisionId ||
        (inputOrigin === "reviewed" ? reviewedRevisionId : generatedRevisionId);
  const selectedEventOption =
    runStage === "visible_cards"
      ? (upstreamStage?.input_options.find(
          (option) => option.node_revision_id === selectedRevisionId,
        ) ?? null)
      : null;
  const reviewedInputListed =
    reviewedRevisionId !== null &&
    (upstreamStage?.input_options.some(
      (option) =>
        option.node_revision_id === reviewedRevisionId &&
        option.origin !== "processor",
    ) ??
      false);
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

  const startRun = async (): Promise<boolean> => {
    if (
      runStage !== "visual_identities" ||
      selectedRevisionId === null ||
      selectedCropInput === null
    ) {
      setMessage(
        "Select a compatible crop input before starting the processor.",
      );
      return false;
    }
    setBusy(true);
    setMessage(null);
    const runId = createRunId(runStage);
    try {
      const response = await client.startVisualIdentityRun(
        recordingId,
        buildRunRequest(
          runStage,
          runId,
          selectedRevisionId,
          latestRun,
          inputOrigin,
          selectedProcessorOrigin,
          visibleCardModelVariant,
          selectedCropInput?.kind ?? null,
          selectedEventOption,
          selectedCropInput?.nodeRef ?? null,
          historicalRevisionId !== "" || inputOrigin === "reviewed"
            ? "historical"
            : "current_head",
          selectedIdentityCropPolicy,
        ),
      );
      setLiveRun(response);
      setTrackedRunId(response.run_id);
      void onRefresh().catch((reason: unknown) => {
        setMessage(describeRunError(reason));
      });
      return true;
    } catch (reason: unknown) {
      setMessage(describeRunError(reason));
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (runStage === null) {
    return null;
  }

  const historicalOptions = upstreamStage?.input_options ?? [];
  const visibleCardBlockers = stage.run_blockers.filter(
    (blocker) =>
      selectedEventOption === null ||
      !/^Select a complete events revision first\.$/i.test(blocker),
  );
  const canStart =
    runStage === "visual_identities" &&
    selectedRevisionId !== null &&
    (runStage !== "visual_identities" ||
      proposedCropInputsLoadedFor === recordingId);
  const eventRunRequest = buildRunRequest(
    "events",
    "preview",
    null,
    latestRun,
    inputOrigin,
  ).request;

  const visibleCardRunRequest = buildRunRequest(
    "visible_cards",
    "preview",
    selectedRevisionId,
    latestRun,
    inputOrigin,
    processorOrigin,
    visibleCardModelVariant,
    null,
    selectedEventOption,
    null,
    selectedEventOption?.node_revision_id === generatedRevisionId &&
      inputOrigin === "generated" &&
      historicalRevisionId === ""
      ? "current_head"
      : "historical",
  ).request;

  const eventAction = {
    id: "event-processing",
    label: "Detect events",
    description:
      "Create a fresh event result from the accepted recording video. This starts queued processing and does not change review decisions.",
    expectedOutput:
      "A new event data revision that remains available for inspection and review.",
    sections: [
      {
        title: "Source",
        content: (
          <>
            <p>Recording: {recordingId}</p>
            <p>Source: accepted recording video</p>
            {stage.run_blockers.map((blocker) => (
              <p className={styles.detailBlocker} key={blocker} role="alert">
                {blocker}
              </p>
            ))}
          </>
        ),
      },
      {
        title: "Processor",
        content: (
          <dl>
            <div>
              <dt>Implementation</dt>
              <dd>
                {eventRunRequest.implementation?.name ?? "cardeventnet"} ·{" "}
                {eventRunRequest.implementation?.version ?? "file-v1"}
              </dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{formatValue(eventRunRequest.model ?? null)}</dd>
            </div>
            <div>
              <dt>Configuration</dt>
              <dd>{formatValue(eventRunRequest.configuration)}</dd>
            </div>
            <div>
              <dt>Extraction policy</dt>
              <dd>{formatValue(eventRunRequest.extraction_policy)}</dd>
            </div>
          </dl>
        ),
      },
    ],
  };

  const visibleCardAction = {
    id: "visible-card-processing",
    label: "Detect visible cards",
    description:
      "Create a fresh visible-card result from one exact event revision. The selected input, detector, model, and processing configuration stay frozen for this job.",
    expectedOutput:
      "A new visible-card data revision that remains available for inspection and review.",
    sections: [
      {
        title: "Input",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Exact event revision</span>
              <select
                aria-label="Exact event revision"
                value={selectedEventOption?.node_revision_id ?? ""}
                disabled={historicalOptions.length === 0}
                onChange={(event) => {
                  const selected = historicalOptions.find(
                    (option) => option.node_revision_id === event.target.value,
                  );
                  setHistoricalRevisionId(
                    selected === undefined ||
                      selected.node_revision_id === generatedRevisionId ||
                      selected.node_revision_id === reviewedRevisionId
                      ? ""
                      : selected.node_revision_id,
                  );
                  if (selected?.node_revision_id === reviewedRevisionId) {
                    setInputOrigin("reviewed");
                  } else {
                    setInputOrigin("generated");
                  }
                  setMessage(null);
                }}
              >
                <option value="">Select one exact event revision</option>
                {historicalOptions.map((option) => (
                  <option
                    key={`${option.node_id}:${option.node_revision_id}`}
                    value={option.node_revision_id}
                  >
                    {option.display_label} · {option.node_revision_id}
                  </option>
                ))}
              </select>
            </label>
            {selectedEventOption ? (
              <p className={styles.pipelineRunInputValue}>
                {selectedEventOption.display_label} · node{" "}
                {selectedEventOption.node_id} · revision{" "}
                {selectedEventOption.node_revision_id}
              </p>
            ) : (
              <p className={styles.pipelineRunInputValue}>
                No compatible event revision is selected.
              </p>
            )}
            {visibleCardBlockers.map((blocker) => (
              <p className={styles.detailBlocker} key={blocker} role="alert">
                {blocker}
              </p>
            ))}
          </>
        ),
      },
      {
        title: "Detector and processing",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Detector and model</span>
              <select
                aria-label="Detector and model"
                value={visibleCardModelVariant}
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
            <dl>
              <div>
                <dt>Implementation</dt>
                <dd>
                  {visibleCardRunRequest.implementation?.name ??
                    "visible-card-detector-adapter"}{" "}
                  · {visibleCardRunRequest.implementation?.version ?? "v1"}
                </dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{formatValue(visibleCardRunRequest.model ?? null)}</dd>
              </div>
              <div>
                <dt>Processing configuration</dt>
                <dd>{formatValue(visibleCardRunRequest.configuration)}</dd>
              </div>
              <div>
                <dt>Extraction policy</dt>
                <dd>{formatValue(visibleCardRunRequest.extraction_policy)}</dd>
              </div>
            </dl>
          </>
        ),
      },
    ],
  };

  const visualIdentityRunRequest = buildRunRequest(
    "visual_identities",
    "preview",
    selectedRevisionId,
    latestRun,
    inputOrigin,
    selectedProcessorOrigin,
    visibleCardModelVariant,
    selectedCropInput?.kind ?? null,
    null,
    selectedCropInput?.nodeRef ?? null,
    selectedCropInput?.nodeRef.revision_policy ?? "historical",
    selectedIdentityCropPolicy,
  ).request;

  const identityAction = {
    id: "visual-identity-classification",
    label: "Classify visual identities",
    description:
      "Create a fresh visual identity result from one exact crop geometry revision. Classification creates processor outcomes; a person reviews and accepts or rejects identities separately.",
    expectedOutput:
      "A new visual identity data revision with the exact crop input and crop policy retained in its lineage.",
    sections: [
      {
        title: "Crop geometry input",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Exact crop geometry revision</span>
              <select
                aria-label="Exact crop geometry revision"
                value={selectedCropInput ? cropInputKey(selectedCropInput) : ""}
                disabled={busy || proposedCropInputsLoadedFor !== recordingId}
                onChange={(event) => {
                  setCropInputSelection(
                    `${recordingId}::${event.target.value}`,
                  );
                  setIdentityCropPolicyState({ recordingId, policy: "" });
                  setMessage(null);
                }}
              >
                {cropInputOptions.length !== 1 ? (
                  <option value="">Select one exact crop input</option>
                ) : null}
                {cropInputOptions.map((option) => (
                  <option
                    key={cropInputKey(option)}
                    value={cropInputKey(option)}
                  >
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            {selectedCropInput ? (
              <p className={styles.pipelineRunInputValue}>
                Source node {selectedCropInput.nodeRef.node_id} · revision{" "}
                {selectedCropInput.nodeRef.revision_id} ·{" "}
                {selectedCropInput.nodeRef.revision_policy}
              </p>
            ) : (
              <p className={styles.pipelineRunInputValue}>
                {proposedCropInputsLoadedFor !== recordingId
                  ? "Loading exact proposed scene revisions…"
                  : cropInputOptions.length === 0
                    ? "No compatible crop geometry inputs are available."
                    : "Choose an exact crop geometry input. Multiple inputs require an explicit choice."}
              </p>
            )}
            {selectedCropInput?.kind === "proposed_virtual_cards" ? (
              <p className={styles.pipelineRunInputValue}>
                Proposal-derived virtual cards use the local classifier. This
                geometry is not reviewed evidence and creates no review
                decision.
              </p>
            ) : null}
            {reviewedRevisionId === null ? (
              <p className={styles.pipelineRunInputValue}>
                Reviewed virtual-card input unavailable: complete a maintained
                visible-card reference.
              </p>
            ) : !reviewedInputListed ? (
              <p className={styles.pipelineRunInputValue}>
                Reviewed virtual-card input unavailable: the completed reference
                revision is not present in the workspace inputs.
              </p>
            ) : null}
            {stage.run_blockers.map((blocker) => (
              <p className={styles.detailBlocker} key={blocker} role="alert">
                {blocker}
              </p>
            ))}
          </>
        ),
      },
      {
        title: "Provider and model",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Classifier provider</span>
              <select
                aria-label="Classifier provider"
                value={selectedProcessorOrigin}
                disabled={
                  busy || selectedCropInput?.kind === "proposed_virtual_cards"
                }
                onChange={(event) => {
                  setIdentityProviderState({
                    recordingId,
                    provider: event.target.value as ProcessorOrigin,
                  });
                  setMessage(null);
                }}
              >
                <option value="local">Local · configured classifier</option>
                <option value="cloud">Cloud · Gemini</option>
              </select>
            </label>
            <p>
              Default: local classifier. The service checks provider and model
              availability before it accepts the run; an unavailable choice
              returns an error and keeps this form open.
            </p>
            <dl>
              <div>
                <dt>Implementation</dt>
                <dd>
                  {visualIdentityRunRequest.implementation?.name} ·{" "}
                  {visualIdentityRunRequest.implementation?.version}
                </dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>
                  Selected by the configured classifier for{" "}
                  {selectedProcessorOrigin === "cloud" ? "Gemini" : "local"}.
                </dd>
              </div>
              <div>
                <dt>Processing configuration</dt>
                <dd>{formatValue(visualIdentityRunRequest.configuration)}</dd>
              </div>
              <div>
                <dt>Extraction policy</dt>
                <dd>
                  {formatValue(visualIdentityRunRequest.extraction_policy)}
                </dd>
              </div>
            </dl>
          </>
        ),
      },
      {
        title: "Crop policy",
        content: (
          <>
            <label className={styles.pipelineRunSelector}>
              <span>Crop policy</span>
              <select
                aria-label="Crop policy"
                value={selectedIdentityCropPolicy}
                disabled={busy || identityCropPolicyOptions.length === 0}
                onChange={(event) =>
                  setIdentityCropPolicyState({
                    recordingId,
                    policy: event.target.value,
                  })
                }
              >
                {identityCropPolicyOptions.map((policy) => (
                  <option key={policy.value} value={policy.value}>
                    {policy.label}
                  </option>
                ))}
              </select>
            </label>
            <p>Crop output encoding: PPM.</p>
            <p>
              The policy is limited to choices supported by this exact geometry
              source. It does not change or review that geometry.
            </p>
          </>
        ),
      },
    ],
  };

  return (
    <section
      className={styles.pipelineRunControls}
      aria-label="Processor actions"
    >
      {stage.run_blockers.length > 0 &&
      runStage !== "events" &&
      runStage !== "visible_cards" &&
      runStage !== "visual_identities" ? (
        <p className={styles.detailBlocker}>{stage.run_blockers[0]}</p>
      ) : (
        <>
          {runStage === "events" ? (
            <JobStartActions
              actions={[eventAction]}
              submitting={eventSubmission.submitting}
              validationErrors={
                eventSubmission.error ? [eventSubmission.error] : []
              }
              canSubmit={stage.can_run && stage.run_blockers.length === 0}
              onStart={async () => {
                const runId = createRunId("events");
                const runRequest = buildRunRequest(
                  "events",
                  runId,
                  null,
                  latestRun,
                  inputOrigin,
                );
                const accepted = await eventSubmission.submit({
                  type: "event_processing",
                  context: { recording_id: recordingId },
                  request: runRequest as unknown as Record<string, unknown>,
                });
                if (accepted === null) return false;
                const run = pipelineRunFromJob(
                  accepted,
                  recordingId,
                  "event-detection",
                );
                setLiveRun(run);
                setTrackedRunId(run.run_id);
                setMessage(null);
                await onRefresh();
                return true;
              }}
            />
          ) : runStage === "visible_cards" ? (
            <JobStartActions
              actions={[visibleCardAction]}
              submitting={visibleCardSubmission.submitting}
              validationErrors={[
                ...visibleCardBlockers,
                ...(selectedEventOption === null
                  ? [
                      historicalOptions.length === 0
                        ? "No compatible event revision is available."
                        : "Select an exact event revision before starting.",
                    ]
                  : []),
              ]}
              canSubmit={
                visibleCardBlockers.length === 0 && selectedEventOption !== null
              }
              onStart={async () => {
                if (selectedEventOption === null) return false;
                const runId = createRunId("visible_cards");
                const request = buildRunRequest(
                  "visible_cards",
                  runId,
                  selectedRevisionId,
                  latestRun,
                  inputOrigin,
                  processorOrigin,
                  visibleCardModelVariant,
                  null,
                  selectedEventOption,
                  null,
                  selectedEventOption.node_revision_id ===
                    generatedRevisionId &&
                    inputOrigin === "generated" &&
                    historicalRevisionId === ""
                    ? "current_head"
                    : "historical",
                );
                const accepted = await visibleCardSubmission.submit({
                  type: "visible_card_detection",
                  context: { recording_id: recordingId },
                  request: request as unknown as Record<string, unknown>,
                });
                if (accepted === null) return false;
                const run = pipelineRunFromJob(
                  accepted,
                  recordingId,
                  "visible-card-detection",
                );
                setLiveRun(run);
                setTrackedRunId(run.run_id);
                setMessage(null);
                await onRefresh();
                return true;
              }}
            />
          ) : runStage === "visual_identities" ? (
            <JobStartActions
              key={recordingId}
              actions={[identityAction]}
              loading={proposedCropInputsLoadedFor !== recordingId}
              submitting={busy}
              validationErrors={[
                ...(message === null ? [] : [message]),
                ...stage.run_blockers,
                ...(selectedCropInput === null
                  ? [
                      cropInputOptions.length === 0
                        ? "No compatible crop geometry input is available."
                        : "Select an exact crop geometry input before starting.",
                    ]
                  : []),
                ...(selectedIdentityCropPolicy === ""
                  ? ["Select a crop policy supported by this geometry input."]
                  : []),
              ]}
              canSubmit={
                canStart && stage.can_run && stage.run_blockers.length === 0
              }
              onStart={async () => {
                if (selectedCropInput === null) return false;
                return startRun();
              }}
            />
          ) : null}
        </>
      )}

      {message !== null && runStage !== "visual_identities" ? (
        <p className={styles.pipelineRunMessage} role="alert">
          {message}
        </p>
      ) : null}

      {selectedRun !== null ? (
        <>
          {selectedRun.job_id ? (
            <p>
              <a href={`/jobs/${encodeURIComponent(selectedRun.job_id)}`}>
                View job {selectedRun.job_id}
              </a>
            </p>
          ) : null}
          <RunStatus
            run={selectedRun}
            showProbabilities={runStage === "events"}
          />
        </>
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
                {runStage === "visual_identities" ? (
                  <span>{describeCropInputRun(run.request)}</span>
                ) : null}
                <span>
                  {run.implementation.name} {run.implementation.version}
                  {run.model === null ? " · no model" : " · model retained"}
                </span>
                {run.failure !== null && run.failure !== undefined ? (
                  <span>{run.failure.message}</span>
                ) : null}
                {run.job_id ? (
                  <a href={`/jobs/${encodeURIComponent(run.job_id)}`}>
                    View job
                  </a>
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
  showProbabilities,
}: {
  run: RunFacts;
  showProbabilities: boolean;
}) {
  const [probabilitiesOpen, setProbabilitiesOpen] = useState(false);
  const state = run.state;
  const progress = readObject(state.progress);
  const completed = readNumber(progress?.completed);
  const total = readNumber(progress?.total);
  const failure = readObject(state.terminal_failure);
  const failureMessage = readString(failure?.message);
  const activity = readRunActivity(state);
  const probabilityMetrics = showProbabilities
    ? readProbabilityMetrics(state)
    : null;
  const closeProbabilities = useCallback(() => setProbabilitiesOpen(false), []);
  const message =
    run.status === "complete"
      ? "The processor completed and retained its output revision."
      : run.status === "partial"
        ? "The processor returned a partial result. Review the successful items in the job details."
        : run.status === "failed"
          ? "The processor failed. Review the job details to retry with the exact frozen inputs."
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
      {activity?.message !== null && activity?.message !== undefined ? (
        <p>
          {activity.message}
          {activity.step !== null && activity.steps !== null
            ? ` (step ${activity.step}/${activity.steps})`
            : ""}
        </p>
      ) : null}
      {failureMessage !== null ? <p>{failureMessage}</p> : null}
      {activity !== null && activity.logs.length > 0 ? (
        <details className={styles.pipelineRunHistory}>
          <summary>Processor log ({activity.logs.length} messages)</summary>
          <ol>
            {activity.logs.slice(-50).map((entry, index) => (
              <li key={`${entry.at ?? "log"}-${index}`}>{entry.message}</li>
            ))}
          </ol>
        </details>
      ) : null}
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
        <div>
          <dt>Crop input</dt>
          <dd>{describeCropInputRun(run.request)}</dd>
        </div>
      </dl>
      {run.job_id ? (
        <a href={`/jobs/${encodeURIComponent(run.job_id)}`}>Manage job</a>
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

function pipelineRunFromJob(
  job: import("../api/jobsContracts").JobDetail,
  recordingId: string,
  processorType: string,
): PipelineRunResponse {
  const status =
    job.state === "waiting" || job.state === "cancelling"
      ? "running"
      : job.state;
  const step = job.steps[0];
  return {
    run_id: job.id,
    job_id: job.id,
    recording_id: recordingId,
    processor_type: processorType,
    status,
    attempt: 1,
    request: job.request,
    state: {
      run_id: job.id,
      status,
      progress: { completed: step?.completed ?? 0, total: step?.total ?? 0 },
      terminal_failure: job.failure,
      output_revision_ids: [],
      items: [],
      metrics: {},
    },
  };
}

function buildRunRequest(
  stage: RunStageKey,
  runId: string,
  inputRevisionId: string | null,
  latestRun: PipelineRun | null,
  inputOrigin: InputOrigin,
  processorOrigin: ProcessorOrigin = "cloud",
  visibleCardModelVariant: VisibleCardModelVariant = "gemini",
  cropInputKind: CropInputKind | null = null,
  eventOption: PipelineWorkspaceStage["input_options"][number] | null = null,
  cropInputRef: CropInputOption["nodeRef"] | null = null,
  eventRevisionPolicy: "current_head" | "historical" = "current_head",
  identityCropPolicyId: string | null = null,
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
            identityCropPolicyId ||
            (cropInputKind === "reviewed_virtual_card" ||
            cropInputKind === "reviewed_visible_card" ||
            (cropInputKind === null && inputOrigin === "reviewed")
              ? "oracle_visible_region"
              : "predicted_visible_region"),
          output_encoding: "ppm",
        }
      : null;
  const model =
    stage === "visual_identities"
      ? undefined
      : (latestRun?.model ?? readRecord(request.model) ?? undefined);
  return {
    request: {
      run_id: runId,
      ...(stage === "visible_cards" && eventOption !== null
        ? {
            input_node_ref: {
              node_id: eventOption.node_id,
              revision_id: eventOption.node_revision_id,
              revision_policy: eventRevisionPolicy,
            },
          }
        : stage === "visual_identities" && cropInputRef !== null
          ? { input_node_ref: cropInputRef }
          : {}),
      ...(stage === "visual_identities" && cropInputKind !== null
        ? { crop_input_kind: cropInputKind }
        : {}),
      implementation,
      ...(model === undefined ? {} : { model }),
      configuration,
      extraction_policy: extractionPolicy,
      crop_policy: cropPolicy,
    },
  };
}

function buildCropInputOptions(
  stage: PipelineWorkspaceStage,
): CropInputOption[] {
  const options: CropInputOption[] = [];
  for (const revision of stage.input_options) {
    if (revision.origin !== "processor") continue;
    const run = stage.runs.find((candidate) =>
      candidate.output_revision_ids.includes(revision.node_revision_id),
    );
    const configuration = readObject(run?.configuration);
    const requestConfiguration = readObject(run?.request.configuration);
    const provider = readString(
      configuration?.provider ?? requestConfiguration?.provider,
    )?.toLowerCase();
    const kind: CropInputKind = provider?.includes("rfdetr")
      ? "rfdetr_segment"
      : "gemini_polygon";
    options.push({
      kind,
      revisionId: revision.node_revision_id,
      nodeRef: {
        node_id: revision.node_id,
        revision_id: revision.node_revision_id,
        revision_policy: revision.is_current_head
          ? "current_head"
          : "historical",
      },
      label: `${formatCropInputKind(kind)} · ${revision.node_revision_id}${
        revision.node_revision_id === stage.selected_generated?.revision_id
          ? " · selected generated revision"
          : ""
      }`,
    });
  }
  const reviewedRevisionId =
    stage.selected_completed_reference?.revision_id ?? null;
  if (reviewedRevisionId !== null) {
    const revision = stage.input_options.find(
      (candidate) =>
        candidate.node_revision_id === reviewedRevisionId &&
        candidate.origin !== "processor",
    );
    if (revision !== undefined) {
      options.push({
        kind: "reviewed_virtual_card",
        revisionId: revision.node_revision_id,
        nodeRef: {
          node_id: revision.node_id,
          revision_id: revision.node_revision_id,
          revision_policy: revision.is_current_head
            ? "current_head"
            : "historical",
        },
        label: `Reviewed virtual cards · ${revision.node_revision_id}`,
      });
      options.push({
        kind: "reviewed_visible_card",
        revisionId: revision.node_revision_id,
        nodeRef: {
          node_id: revision.node_id,
          revision_id: revision.node_revision_id,
          revision_policy: revision.is_current_head
            ? "current_head"
            : "historical",
        },
        label: `Reviewed visible cards · ${revision.node_revision_id}`,
      });
    }
  }
  return options;
}

function cropInputKey(option: CropInputOption): string {
  return `${option.kind}:${option.revisionId}`;
}

function cropPolicyOptions(kind: CropInputKind) {
  if (kind === "reviewed_virtual_card" || kind === "reviewed_visible_card") {
    return [
      { value: "oracle_visible_region", label: "Reviewed visible region" },
      { value: "raw_rectangular", label: "Raw rectangular crop" },
    ];
  }
  return [
    { value: "predicted_visible_region", label: "Predicted visible region" },
    {
      value: "predicted_region_with_other_exclusion",
      label: "Predicted region with other-card exclusion",
    },
    { value: "raw_rectangular", label: "Raw rectangular crop" },
  ];
}

function formatCropInputKind(kind: CropInputKind): string {
  switch (kind) {
    case "gemini_polygon":
      return "Generated · Gemini";
    case "rfdetr_segment":
      return "Generated · RF-DETR";
    case "proposed_virtual_cards":
      return "Proposed virtual cards";
    case "reviewed_virtual_card":
      return "Reviewed virtual cards";
    case "reviewed_visible_card":
      return "Reviewed visible cards";
  }
}

function describeCropInputRun(request: Record<string, unknown>): string {
  const cropInput = readObject(request.crop_input);
  const kind = readString(cropInput?.input_kind);
  const sourceRevisionId = readString(cropInput?.source_revision_id);
  const items =
    typeof cropInput?.item_count === "number"
      ? cropInput.item_count
      : Array.isArray(cropInput?.items)
        ? cropInput.items.length
        : null;
  const policy = readString(readObject(request.crop_policy)?.policy_id);
  const kindLabel =
    kind === "gemini_polygon" ||
    kind === "rfdetr_segment" ||
    kind === "proposed_virtual_cards" ||
    kind === "reviewed_virtual_card" ||
    kind === "reviewed_visible_card"
      ? formatCropInputKind(kind)
      : "Crop input unavailable";
  return [
    kindLabel,
    sourceRevisionId === null ? null : `source ${sourceRevisionId}`,
    readString(
      readObject(cropInput?.proposed_virtual_card_lineage)
        ?.detector_revision_id,
    ),
    readString(
      readObject(cropInput?.proposed_virtual_card_lineage)
        ?.calibration_revision_id,
    ),
    items === null ? null : `${items} crop inputs`,
    policy === null ? null : `policy ${policy}`,
  ]
    .filter((value): value is string => value !== null)
    .join(" · ");
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
  if (backendMessage?.includes("obsolete uncalibrated smoke format")) {
    return `${backendMessage}. Select Cloud to continue, or configure a current Local bundle.`;
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
