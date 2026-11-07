import type {
  PipelineWorkspace,
  PipelineWorkspaceStage,
} from "../api/pipelineContracts";
import { decodeLineageSelection } from "./pipelineLineageSelection";
import type { PipelineUrlState } from "./recordingPipelineUrl";

export function chooseInitialStage(
  workspace: PipelineWorkspace,
): PipelineWorkspaceStage {
  return (
    workspace.stages.find(
      (stage) =>
        stage.state !== "video-only" &&
        stage.state !== "empty" &&
        (stage.input_options.length > 0 ||
          stage.runs.length > 0 ||
          stage.analyses.length > 0),
    ) ?? workspace.stages[0]
  );
}

export function sanitizeUrlState(
  state: PipelineUrlState,
  stage: PipelineWorkspaceStage,
  durationUs: number,
  compare: boolean,
): PipelineUrlState {
  const validRunIds = new Set(stage.runs.map((run) => run.run_id));
  const validReferenceIds = new Set(
    stage.input_options
      .filter(
        (option) => option.origin === "manual" || option.origin === "corrected",
      )
      .map((option) => option.node_revision_id),
  );
  const selectedReference = stage.selected_completed_reference?.revision_id;
  return {
    ...state,
    item:
      state.item !== null &&
      (isKnownItem(stage, state.item) ||
        (stage.key === "table_observations" &&
          state.lineage !== null &&
          decodeLineageSelection(state.lineage)?.selected.table_observations !==
            undefined))
        ? state.item
        : null,
    tUs:
      state.tUs === null
        ? null
        : Math.min(Math.max(state.tUs, 0), Math.max(durationUs, 0)),
    left:
      compare && state.left !== null && validRunIds.has(state.left)
        ? state.left
        : null,
    right:
      compare && state.right !== null && validRunIds.has(state.right)
        ? state.right
        : null,
    reference:
      compare &&
      state.reference !== null &&
      (validReferenceIds.has(state.reference) ||
        state.reference === selectedReference)
        ? state.reference
        : null,
    analysis:
      !compare && state.analysis !== null
        ? stage.analyses.some(
            (analysis) => analysis.analysis_id === state.analysis,
          )
          ? state.analysis
          : null
        : null,
    row: compare ? null : state.row,
    hypothesis: compare ? null : state.hypothesis,
  };
}

function isKnownItem(stage: PipelineWorkspaceStage, itemId: string): boolean {
  if (stage.key === "round_analyses") return false;
  const knownItemIds = stage.runs.flatMap((run) => {
    const items = run.state.items;
    return Array.isArray(items)
      ? items.flatMap((item) =>
          typeof item === "object" &&
          item !== null &&
          "item_id" in item &&
          typeof item.item_id === "string"
            ? [item.item_id]
            : [],
        )
      : [];
  });
  return stage.key === "table_observations"
    ? knownItemIds.includes(itemId)
    : knownItemIds.length === 0 || knownItemIds.includes(itemId);
}
