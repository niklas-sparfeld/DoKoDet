import { pipelineDerivedFramePath } from "../api/client";
import {
  TimelineRailSeekingControls,
  TimelineRailSeekingPortal,
  useTimelineRailSeekingSlot,
} from "../pipeline/TimelineRailSeekingControls";
import type { EditableFrame } from "./PipelineVisibleCardTypes";

export function visibleCardReviewPrewarmUrls(
  recordingId: string,
  frame: EditableFrame,
): string[] {
  const identity = frame.outcome.frame_identity;
  return identity === null
    ? []
    : [pipelineDerivedFramePath(recordingId, identity.requested_time_us)];
}

export function VisibleCardReviewNavigation({
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
}: {
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const timelineSeekingSlot = useTimelineRailSeekingSlot();
  const groups = [
    {
      label: "Frame navigation",
      controls: [
        {
          label: "Previous frame",
          symbol: "⏮",
          shortcut: "ArrowLeft",
          ariaShortcut: "ArrowLeft",
          disabled: !hasPrevious,
          disabledReason: "There is no previous frame.",
          onClick: onPrevious,
        },
        {
          label: "Next frame",
          symbol: "⏭",
          shortcut: "ArrowRight",
          ariaShortcut: "ArrowRight",
          disabled: !hasNext,
          disabledReason: "There is no next frame.",
          onClick: onNext,
        },
      ],
    },
  ] as const;

  return timelineSeekingSlot === null ? (
    <TimelineRailSeekingControls groups={groups} />
  ) : (
    <TimelineRailSeekingPortal slot={timelineSeekingSlot} groups={groups} />
  );
}
