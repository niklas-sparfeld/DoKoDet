import { ApiError } from "../api/transport";
import type { JobDetail } from "../api/jobsContracts";
import type {
  PipelineRun,
  PipelineRunResponse,
  PipelineRunStartRequest,
  PipelineStageKey,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";

export type RunStageKey = Extract<
  PipelineStageKey,
  "events" | "visible_cards" | "visual_identities"
>;
export const RUN_STAGE_KEYS: readonly RunStageKey[] = [
  "events",
  "visible_cards",
  "visual_identities",
];
export const UPSTREAM_STAGE: Record<
  Exclude<RunStageKey, "events">,
  RunStageKey
> = { visible_cards: "events", visual_identities: "visible_cards" };

export type RunControlsProps = {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  stages: PipelineWorkspaceStage[];
  onRefresh: () => Promise<void>;
};

export type InputOrigin = "generated" | "reviewed";
export type ProcessorOrigin = "cloud" | "local";
export type VisibleCardModelVariant =
  | "gemini"
  | "local"
  | "local-rfdetr-segmentation"
  | "local-rfdetr-fine-frame"
  | "local-rfdetr-crop-review";
export type CropInputKind =
  | "gemini_polygon"
  | "rfdetr_segment"
  | "proposed_virtual_cards"
  | "reviewed_virtual_card"
  | "reviewed_visible_card";
export type CropInputOption = {
  kind: CropInputKind;
  revisionId: string;
  nodeRef: {
    node_id: string;
    revision_id: string;
    revision_policy: "current_head" | "historical";
  };
  label: string;
};

export const VISIBLE_CARD_MODEL_VARIANTS: readonly {
  value: VisibleCardModelVariant;
  label: string;
}[] = [
  { value: "gemini", label: "Cloud · Gemini" },
  { value: "local", label: "Local · configured legacy provider" },
  { value: "local-rfdetr-segmentation", label: "Local · RF-DETR segmentation" },
  {
    value: "local-rfdetr-fine-frame",
    label: "Local · RF-DETR fine-frame refinement",
  },
  {
    value: "local-rfdetr-crop-review",
    label: "Local · RF-DETR crop refinement review",
  },
];

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
function readRecord(value: unknown): Record<string, unknown> | null {
  return readObject(value);
}

export function buildRunRequest(
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

export function buildCropInputOptions(
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

export function cropInputKey(option: CropInputOption): string {
  return `${option.kind}:${option.revisionId}`;
}

export function cropPolicyOptions(kind: CropInputKind) {
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

export function formatCropInputKind(kind: CropInputKind): string {
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

export function describeCropInputRun(request: Record<string, unknown>): string {
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

export function initialVisibleCardModelVariant(
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

export function pipelineRunFromJob(
  job: JobDetail,
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

export function createRunId(stage: RunStageKey): string {
  const suffix =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().slice(0, 12)
      : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `${stage}-run-${suffix}`;
}

export function describeRunError(reason: unknown): string {
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
