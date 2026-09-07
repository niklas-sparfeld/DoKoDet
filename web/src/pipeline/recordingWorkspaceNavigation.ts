import type { MouseEvent } from "react";

import type { PipelineStageKey, PipelineWorkspaceStage } from "../api/client";
import {
  recordingPipelineComparePath,
  recordingPipelinePath,
  type PipelineUrlState,
} from "./recordingPipelineUrl";
import type { PipelinePrimaryActionKind } from "./recordingWorkspacePresentation";

export function actionHref(
  recordingId: string,
  stage: PipelineStageKey,
  action: PipelinePrimaryActionKind,
  state: PipelineUrlState,
): string {
  if (action === "compare") {
    return recordingPipelineComparePath(recordingId, stage, state);
  }
  return recordingPipelinePath(recordingId, stage, {
    ...state,
    view:
      action === "review" || action === "continue_review"
        ? "reviewed"
        : state.view,
  });
}

export function actionStateForStage(
  stage: PipelineWorkspaceStage,
  state: PipelineUrlState,
  action: PipelinePrimaryActionKind,
): PipelineUrlState {
  if (action !== "open_analysis") {
    return state;
  }
  return {
    ...state,
    analysis:
      stage.analyses.find((analysis) => analysis.state === "complete")
        ?.analysis_id ?? null,
  };
}

export function isModifiedClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}
