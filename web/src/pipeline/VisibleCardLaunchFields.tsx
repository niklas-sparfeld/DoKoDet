import styles from "../App.module.css";
import type { JobStartAction } from "../jobs/JobStartActions";
import type {
  PipelineRunStartRequest,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import {
  VISIBLE_CARD_MODEL_VARIANTS,
  type VisibleCardModelVariant,
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

export function buildVisibleCardLaunchFields({
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
  request,
}: {
  historicalOptions: PipelineWorkspaceStage["input_options"];
  selectedEventOption: PipelineWorkspaceStage["input_options"][number] | null;
  selectedEventSet: { set_id: string; version: string; choice: string } | null;
  generatedRevisionId: string | null;
  reviewedRevisionId: string | null;
  setHistoricalRevisionId: (value: string) => void;
  setInputOrigin: (value: "generated" | "reviewed") => void;
  setMessage: (value: string | null) => void;
  visibleCardBlockers: string[];
  visibleCardModelVariant: VisibleCardModelVariant;
  setVisibleCardModelVariant: (value: VisibleCardModelVariant) => void;
  request: PipelineRunStartRequest["request"];
}): JobStartAction {
  return {
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
              <span>Exact event input</span>
              <select
                aria-label="Exact event input"
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
            ) : selectedEventSet === null ? (
              <p className={styles.pipelineRunInputValue}>
                No compatible event revision or event set is selected.
              </p>
            ) : null}
            {selectedEventSet ? (
              <p className={styles.pipelineRunInputValue}>
                Event set {selectedEventSet.set_id}@{selectedEventSet.version} ·{" "}
                {selectedEventSet.choice}
              </p>
            ) : null}
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
                  {request.implementation?.name ??
                    "visible-card-detector-adapter"}{" "}
                  · {request.implementation?.version ?? "v1"}
                </dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{formatValue(request.model ?? null)}</dd>
              </div>
              <div>
                <dt>Processing configuration</dt>
                <dd>{formatValue(request.configuration)}</dd>
              </div>
              <div>
                <dt>Extraction policy</dt>
                <dd>{formatValue(request.extraction_policy)}</dd>
              </div>
            </dl>
          </>
        ),
      },
    ],
  };
}
