import styles from "../App.module.css";
import type { JobStartAction } from "../jobs/JobStartActions";
import type {
  PipelineRunStartRequest,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import {
  cropInputKey,
  type CropInputOption,
  type ProcessorOrigin,
} from "./pipelineLaunchRequest";

function formatValue(value: unknown): string {
  if (value == null) return "None";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "Unavailable";
  }
}

export function buildVisualIdentityLaunchFields({
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
}: {
  recordingId: string;
  selectedCropInput: CropInputOption | null;
  setCropInputSelection: (value: string) => void;
  busy: boolean;
  proposedCropInputsLoadedFor: string | null;
  cropInputOptions: CropInputOption[];
  reviewedRevisionId: string | null;
  reviewedInputListed: boolean;
  stage: PipelineWorkspaceStage;
  selectedProcessorOrigin: ProcessorOrigin;
  setIdentityProviderState: (value: {
    recordingId: string;
    provider: ProcessorOrigin;
  }) => void;
  setMessage: (value: string | null) => void;
  visualIdentityRunRequest: PipelineRunStartRequest["request"];
  selectedIdentityCropPolicy: string;
  identityCropPolicyOptions: { value: string; label: string }[];
  setIdentityCropPolicyState: (value: {
    recordingId: string;
    policy: string;
  }) => void;
}): JobStartAction {
  return {
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
}
