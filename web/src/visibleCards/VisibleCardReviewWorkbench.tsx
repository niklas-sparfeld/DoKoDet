import { VisibleCardReviewWorkbenchView } from "./VisibleCardReviewWorkbenchView";
import type { VisibleCardReviewWorkbenchProps } from "./VisibleCardReviewWorkbenchView";

export type {
  VisibleCardFrameDecision,
  VisibleCardReviewWorkbenchAction,
  VisibleCardReviewWorkbenchProps,
  VisibleRegionWorkbenchAction,
  VirtualCardWorkbenchAction,
} from "./VisibleCardReviewWorkbenchView";
export { WORKBENCH_LAYER_REGISTRY } from "./VisibleCardReviewWorkbenchView";
export type { MappingWorkbenchAction } from "./VisibleCardWorkbenchInteraction";

export function VisibleCardReviewWorkbench(
  props: VisibleCardReviewWorkbenchProps,
) {
  return <VisibleCardReviewWorkbenchView {...props} />;
}
