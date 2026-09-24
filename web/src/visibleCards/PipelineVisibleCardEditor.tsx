import { PipelineVisibleCardEditorView } from "./PipelineVisibleCardEditorView";
import type { PipelineVisibleCardEditorProps } from "./PipelineVisibleCardEditorView";

export type { PipelineVisibleCardRailItem } from "./PipelineVisibleCardTypes";
export type { PipelineVisibleCardEditorProps } from "./PipelineVisibleCardEditorView";

export function PipelineVisibleCardEditor(
  props: PipelineVisibleCardEditorProps,
) {
  return <PipelineVisibleCardEditorView {...props} />;
}
