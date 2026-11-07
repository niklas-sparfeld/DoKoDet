import { useCallback, useMemo, useState } from "react";

import type {
  PipelineComparisonResponse,
  PipelineStageKey,
  PipelineWorkspaceStage,
} from "../api/client";
import type { PipelineCardEventRailItem } from "../cardEvents/PipelineCardEventRailItem";
import styles from "../App.module.css";
import { RecordingTimelineRail } from "./RecordingTimelineRail";
import type { PipelineUrlState } from "./recordingPipelineUrl";
import type {
  RecordingTimelineRailItem,
  RecordingWorkspacePresentation,
} from "./recordingWorkspacePresentation";
import railStyles from "./RecordingWorkspaceRail.module.css";

type RailCollection = {
  key: string;
  items: RecordingTimelineRailItem[];
};

type PresentationRailItem = NonNullable<
  RecordingWorkspacePresentation["rail"]
>["items"][number];

export type RecordingWorkspaceRailController = {
  comparison: PipelineComparisonResponse | null;
  visibleRail: RecordingWorkspacePresentation["rail"];
  handleEventRailItemsChange: (items: PipelineCardEventRailItem[]) => void;
  handleComparisonRailItemsChange: (items: RecordingTimelineRailItem[]) => void;
  handleComparisonChange: (comparison: PipelineComparisonResponse) => void;
  handleRailTimeChange: (timeUs: number) => void;
  handleRailItemSelect: (item: PresentationRailItem) => void;
};

export function useRecordingWorkspaceRail({
  recordingId,
  stage,
  stageKey,
  compare,
  urlState,
  durationUs,
  rail,
  onReplaceUrlState,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage | undefined;
  stageKey: PipelineStageKey | null;
  compare: boolean;
  urlState: PipelineUrlState;
  durationUs: number;
  rail: RecordingWorkspacePresentation["rail"];
  onReplaceUrlState: (state: PipelineUrlState) => void;
}): RecordingWorkspaceRailController {
  const [eventRail, setEventRail] = useState<RailCollection | null>(null);
  const [comparisonRail, setComparisonRail] = useState<RailCollection | null>(
    null,
  );
  const [comparison, setComparison] =
    useState<PipelineComparisonResponse | null>(null);
  const currentStageKey = stage?.key ?? stageKey ?? "events";
  const railKey = `${recordingId}:${currentStageKey}:${compare ? "compare" : "task"}`;
  const comparisonRailKey = `${recordingId}:${currentStageKey}:comparison`;

  const handleComparisonRailItemsChange = useCallback(
    (items: RecordingTimelineRailItem[]) => {
      setComparisonRail((current) => {
        const key = comparisonRailKey;
        if (sameRailItems(current?.items, items) && current?.key === key) {
          return current;
        }
        return { key, items };
      });
    },
    [comparisonRailKey],
  );
  const handleComparisonChange = useCallback(
    (nextComparison: PipelineComparisonResponse) =>
      setComparison(nextComparison),
    [],
  );
  const handleEventRailItemsChange = useCallback(
    (items: PipelineCardEventRailItem[]) => {
      setEventRail({
        key: railKey,
        items: buildEventRailItems(items, durationUs),
      });
    },
    [durationUs, railKey],
  );
  const visibleRail = useMemo(() => {
    if (rail === null) return null;
    const customRail = compare
      ? comparisonRail?.key === comparisonRailKey
        ? comparisonRail
        : null
      : stage?.key === "events"
        ? eventRail?.key === railKey
          ? eventRail
          : null
        : undefined;
    return customRail === undefined
      ? rail
      : customRailForRail(rail, customRail?.items ?? [], urlState.item);
  }, [
    compare,
    comparisonRail,
    comparisonRailKey,
    eventRail,
    rail,
    railKey,
    stage?.key,
    urlState.item,
  ]);

  const handleRailTimeChange = useCallback(
    (timeUs: number) => onReplaceUrlState({ ...urlState, tUs: timeUs }),
    [onReplaceUrlState, urlState],
  );
  const handleRailItemSelect = useCallback(
    (item: PresentationRailItem) => {
      if (item.selectionParam === "none") {
        if (item.timeRange !== null) {
          onReplaceUrlState({ ...urlState, tUs: item.timeRange.startUs });
        }
        return;
      }
      onReplaceUrlState({
        ...urlState,
        item: item.selectionParam === "item" ? item.itemId : null,
        analysis: item.selectionParam === "analysis" ? item.itemId : null,
        tUs: item.timeRange?.startUs ?? urlState.tUs,
      });
    },
    [onReplaceUrlState, urlState],
  );

  return {
    comparison,
    visibleRail,
    handleEventRailItemsChange,
    handleComparisonRailItemsChange,
    handleComparisonChange,
    handleRailTimeChange,
    handleRailItemSelect,
  };
}

export function RecordingWorkspaceTimelineRail({
  recordingId,
  navigationStep,
  stage,
  compare,
  rail,
  onTimeChange,
  onItemSelect,
}: {
  recordingId: string;
  navigationStep: import("./recordingPipelineUrl").PipelineNavigationStepKey;
  stage: PipelineWorkspaceStage;
  compare: boolean;
  rail: RecordingWorkspacePresentation["rail"];
  onTimeChange: (timeUs: number) => void;
  onItemSelect: (item: PresentationRailItem) => void;
}) {
  return (
    <section
      className={`${styles.pipelineRailSlot} ${railStyles.slot}`}
      aria-label="Timeline Rail"
      data-slot="bottom"
    >
      {(navigationStep === "visible_cards" ||
        navigationStep === "virtual_scenes") &&
      !compare ? (
        <div
          data-visible-card-navigation-slot
          aria-label="Visible-card frame navigation"
        />
      ) : null}
      {rail !== null ? (
        <RecordingTimelineRail
          key={`${stage.key}:${compare ? "compare" : "task"}`}
          recordingId={recordingId}
          durationUs={rail.durationUs}
          currentTimeUs={rail.currentTimeUs}
          selectedItemId={rail.selectedItemId}
          lanes={rail.lanes}
          items={rail.items}
          stillFrameMode={stage.key === "events" && !compare}
          onTimeChange={onTimeChange}
          onItemSelect={onItemSelect}
        />
      ) : (
        <p className={railStyles.hint}>Timeline unavailable.</p>
      )}
    </section>
  );
}

export function buildEventRailItems(
  items: PipelineCardEventRailItem[],
  durationUs: number,
): RecordingTimelineRailItem[] {
  return items
    .flatMap<RecordingTimelineRailItem>((item) => [
      {
        id: `event:${item.itemId}`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId:
          item.state === "pending" || item.state === "affected"
            ? "review-state"
            : "events",
        label: item.label,
        state: item.state,
        timeRange: { startUs: item.startUs, endUs: item.endUs },
        runId: null,
      },
      {
        id: `event:${item.itemId}:state`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "review-state",
        label: `${item.label} · ${item.state}`,
        state: item.state,
        timeRange: { startUs: item.startUs, endUs: item.endUs },
        runId: null,
      },
    ])
    .concat({
      id: "events:coverage",
      itemId: "events:coverage",
      selectionParam: "none" as const,
      laneId: "coverage",
      label: "Full recording",
      state: "reviewed",
      timeRange: { startUs: 0, endUs: Math.max(durationUs, 0) },
      runId: null,
    });
}

function customRailForRail(
  rail: NonNullable<RecordingWorkspacePresentation["rail"]>,
  items: RecordingTimelineRailItem[],
  selectedItemId: string | null,
): NonNullable<RecordingWorkspacePresentation["rail"]> {
  return {
    ...rail,
    items,
    selectedItemId:
      items.find((item) => item.itemId === selectedItemId)?.id ?? null,
    lanes: rail.lanes.map((lane) => ({
      ...lane,
      itemCount: items.filter((item) => item.laneId === lane.id).length,
    })),
  };
}

function sameRailItems(
  current: RecordingTimelineRailItem[] | undefined,
  next: RecordingTimelineRailItem[],
): boolean {
  return (
    current !== undefined &&
    current.length === next.length &&
    current.every(
      (item, index) =>
        item.id === next[index].id &&
        item.state === next[index].state &&
        item.timeRange?.startUs === next[index].timeRange?.startUs,
    )
  );
}
