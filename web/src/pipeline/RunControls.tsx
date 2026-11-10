import { useCallback, useEffect, useMemo, useState } from "react";

import { type PipelineRunResponse } from "../api/pipelineContracts";
import { type EnqueueJobBody } from "../api/jobsContracts";
import styles from "../App.module.css";
import { JobStartActions } from "../jobs/JobStartActions";
import { useJobSubmission } from "../jobs/useJobSubmission";
import { buildEventLaunchFields } from "./EventLaunchFields";
import { buildVisibleCardLaunchFields } from "./VisibleCardLaunchFields";
import { buildVisualIdentityLaunchFields } from "./VisualIdentityLaunchFields";
import { RunHistoryPresentation } from "./RunHistoryPresentation";
import { usePipelineLaunchClient } from "./usePipelineLaunchClient";

import {
  buildCropInputOptions,
  buildRunRequest,
  createRunId,
  describeRunError,
  pipelineRunFromJob,
  RUN_STAGE_KEYS,
  UPSTREAM_STAGE,
  type RunStageKey,
  type RunControlsProps,
  cropInputKey,
  cropPolicyOptions,
  initialVisibleCardModelVariant,
  type InputOrigin,
  type ProcessorOrigin,
  type VisibleCardModelVariant,
} from "./pipelineLaunchRequest";

export function RunControls({
  recordingId,
  stage,
  stages,
  onRefresh,
}: RunControlsProps) {
  const client = usePipelineLaunchClient();
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
  const selectedEventSet = (() => {
    if (runStage !== "visible_cards" || upstreamStage === undefined)
      return null;
    const generated = upstreamStage.selected_event_set_generated;
    const reference = upstreamStage.selected_event_set_reference;
    const selected =
      inputOrigin === "reviewed"
        ? (reference ?? generated)
        : (generated ?? reference);
    return selected?.set_id === undefined || selected.version === undefined
      ? null
      : {
          ...selected,
          choice: selected === reference ? "reference" : "generated",
        };
  })();
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
      (selectedEventOption === null && selectedEventSet === null) ||
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
  void visibleCardRunRequest;

  const eventAction = buildEventLaunchFields({
    recordingId,
    blockers: stage.run_blockers,
    request: eventRunRequest,
  });

  const visibleCardAction = buildVisibleCardLaunchFields({
    historicalOptions,
    selectedEventOption,
    selectedEventSet,
    generatedRevisionId,
    reviewedRevisionId,
    setHistoricalRevisionId,
    setInputOrigin,
    setMessage,
    visibleCardBlockers,
    visibleCardModelVariant,
    setVisibleCardModelVariant,
    request: visibleCardRunRequest,
  });

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

  const identityAction = buildVisualIdentityLaunchFields({
    recordingId,
    selectedCropInput,
    setCropInputSelection,
    busy,
    proposedCropInputsLoadedFor,
    cropInputOptions,
    reviewedRevisionId,
    reviewedInputListed,
    stage,
    selectedProcessorOrigin,
    setIdentityProviderState,
    setMessage,
    visualIdentityRunRequest,
    selectedIdentityCropPolicy,
    identityCropPolicyOptions,
    setIdentityCropPolicyState,
  });

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
                ...(selectedEventOption === null && selectedEventSet === null
                  ? [
                      historicalOptions.length === 0
                        ? "No compatible event revision is available."
                        : "Select an exact event revision before starting.",
                    ]
                  : []),
              ]}
              canSubmit={
                visibleCardBlockers.length === 0 &&
                (selectedEventOption !== null || selectedEventSet !== null)
              }
              onStart={async () => {
                if (selectedEventOption === null && selectedEventSet === null)
                  return false;
                const runId = createRunId("visible_cards");
                const request = buildRunRequest(
                  "visible_cards",
                  runId,
                  selectedEventOption?.node_revision_id ?? selectedRevisionId,
                  latestRun,
                  inputOrigin,
                  processorOrigin,
                  visibleCardModelVariant,
                  null,
                  selectedEventOption,
                  null,
                  selectedEventOption?.node_revision_id ===
                    generatedRevisionId &&
                    inputOrigin === "generated" &&
                    historicalRevisionId === ""
                    ? "current_head"
                    : "historical",
                );
                if (selectedEventSet !== null) {
                  const response = await fetch(
                    `/api/recordings/${encodeURIComponent(recordingId)}/event-sets/${encodeURIComponent(selectedEventSet.set_id)}/versions/${encodeURIComponent(selectedEventSet.version)}`,
                  );
                  if (!response.ok) {
                    setMessage("The selected event set could not be loaded.");
                    return false;
                  }
                  const saved = (await response.json()) as {
                    content_sha256: string;
                  };
                  request.request.input_event_set_ref = {
                    set_id: selectedEventSet.set_id,
                    version: selectedEventSet.version,
                    content_sha256: saved.content_sha256,
                  };
                }
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

      <RunHistoryPresentation
        selectedRun={selectedRun}
        stage={stage}
        runStage={runStage}
        trackedRunId={trackedRunId}
        setTrackedRunId={setTrackedRunId}
        setLiveRun={setLiveRun}
        setMessage={setMessage}
      />
    </section>
  );
}
