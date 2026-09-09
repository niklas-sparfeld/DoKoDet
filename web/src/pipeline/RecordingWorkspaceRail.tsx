import { useCallback, useMemo, useState } from "react";

import type {
  PipelineComparisonResponse,
  PipelineStageKey,
  PipelineWorkspaceStage,
} from "../api/client";
import type { PipelineCardEventRailItem } from "../cardEvents/PipelineCardEventEditor";
import type { PipelineVisibleCardRailItem } from "../visibleCards/PipelineVisibleCardEditor";
import type { PipelineVisualIdentityRailItem } from "../visualIdentities/PipelineVisualIdentityEditor";
import styles from "../App.module.css";
import { RecordingTimelineRail } from "./RecordingTimelineRail";
import type { PipelineUrlState, PipelineView } from "./recordingPipelineUrl";
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
  selectedEventRunId: string | null;
  selectedVisibleCardRunId: string | null;
  selectedVisualIdentityRunId: string | null;
  handleEventRailItemsChange: (items: PipelineCardEventRailItem[]) => void;
  handleVisibleCardRailItemsChange: (
    items: PipelineVisibleCardRailItem[],
  ) => void;
  handleVisualIdentityRailItemsChange: (
    items: PipelineVisualIdentityRailItem[],
  ) => void;
  handleComparisonRailItemsChange: (items: RecordingTimelineRailItem[]) => void;
  handleComparisonChange: (comparison: PipelineComparisonResponse) => void;
  handleRailTimeChange: (timeUs: number) => void;
  handleRailItemSelect: (item: PresentationRailItem) => void;
};

export function useRecordingWorkspaceRail({
  recordingId,
  stage,
  stageKey,
  activeView,
  compare,
  urlState,
  displayedRevision,
  durationUs,
  rail,
  onReplaceUrlState,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage | undefined;
  stageKey: PipelineStageKey | null;
  activeView: PipelineView;
  compare: boolean;
  urlState: PipelineUrlState;
  displayedRevision: string | null;
  durationUs: number;
  rail: RecordingWorkspacePresentation["rail"];
  onReplaceUrlState: (state: PipelineUrlState) => void;
}): RecordingWorkspaceRailController {
  const [eventRail, setEventRail] = useState<RailCollection | null>(null);
  const [visibleCardRail, setVisibleCardRail] = useState<RailCollection | null>(
    null,
  );
  const [visualIdentityRail, setVisualIdentityRail] =
    useState<RailCollection | null>(null);
  const [comparisonRail, setComparisonRail] = useState<RailCollection | null>(
    null,
  );
  const [comparison, setComparison] =
    useState<PipelineComparisonResponse | null>(null);
  const currentStageKey = stage?.key ?? stageKey ?? "events";
  const railKey = `${recordingId}:${currentStageKey}:${activeView}:${compare ? "compare" : "task"}`;
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
  const handleVisibleCardRailItemsChange = useCallback(
    (items: PipelineVisibleCardRailItem[]) => {
      setVisibleCardRail({
        key: railKey,
        items: buildVisibleCardRailItems(items, durationUs),
      });
    },
    [durationUs, railKey],
  );
  const handleVisualIdentityRailItemsChange = useCallback(
    (items: PipelineVisualIdentityRailItem[]) => {
      setVisualIdentityRail({
        key: railKey,
        items: buildVisualIdentityRailItems(items, durationUs),
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
      : stage?.key === "events" && activeView === "reviewed"
        ? eventRail?.key === railKey
          ? eventRail
          : null
        : stage?.key === "visible_cards"
          ? visibleCardRail?.key === railKey
            ? visibleCardRail
            : null
          : stage?.key === "visual_identities"
            ? visualIdentityRail?.key === railKey
              ? visualIdentityRail
              : null
            : undefined;
    return customRail === undefined
      ? rail
      : customRailForRail(rail, customRail?.items ?? [], urlState.item);
  }, [
    activeView,
    compare,
    comparisonRail,
    comparisonRailKey,
    eventRail,
    rail,
    railKey,
    stage?.key,
    urlState.item,
    visibleCardRail,
    visualIdentityRail,
  ]);

  const selectedEventRunId = selectedRunId(stage, displayedRevision, "events");
  const selectedVisibleCardRunId = selectedRunId(
    stage,
    displayedRevision ?? stage?.selected_generated_revision_id ?? null,
    "visible_cards",
  );
  const selectedVisualIdentityRunId = selectedRunId(
    stage,
    displayedRevision,
    "visual_identities",
  );

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
    selectedEventRunId,
    selectedVisibleCardRunId,
    selectedVisualIdentityRunId,
    handleEventRailItemsChange,
    handleVisibleCardRailItemsChange,
    handleVisualIdentityRailItemsChange,
    handleComparisonRailItemsChange,
    handleComparisonChange,
    handleRailTimeChange,
    handleRailItemSelect,
  };
}

export function RecordingWorkspaceTimelineRail({
  recordingId,
  stage,
  activeView,
  compare,
  rail,
  onTimeChange,
  onItemSelect,
}: {
  recordingId: string;
  stage: PipelineWorkspaceStage;
  activeView: PipelineView;
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
      {rail !== null ? (
        <RecordingTimelineRail
          key={`${stage.key}:${activeView}:${compare ? "compare" : "task"}`}
          recordingId={recordingId}
          durationUs={rail.durationUs}
          currentTimeUs={rail.currentTimeUs}
          selectedItemId={rail.selectedItemId}
          lanes={rail.lanes}
          items={rail.items}
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

export function buildVisibleCardRailItems(
  items: PipelineVisibleCardRailItem[],
  durationUs: number,
): RecordingTimelineRailItem[] {
  return items.flatMap<RecordingTimelineRailItem>((item) => {
    const timeRange =
      item.timeUs === null
        ? null
        : {
            startUs: item.timeUs,
            endUs: Math.min(Math.max(durationUs, 0), item.timeUs + 1),
          };
    return [
      {
        id: `visible-card:${item.itemId}`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "resolved-frames",
        label: item.label,
        state: item.state,
        timeRange,
        runId: null,
      },
      {
        id: `visible-card:${item.itemId}:decision`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "frame-decision",
        label: `${item.label} · ${item.decision ?? "pending decision"}`,
        state: item.decision ?? item.state,
        timeRange,
        runId: null,
      },
      {
        id: `visible-card:${item.itemId}:proposals`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "proposals",
        label: `${item.label} · ${item.proposalCount} proposal${item.proposalCount === 1 ? "" : "s"}`,
        state: item.state,
        timeRange,
        runId: null,
      },
    ];
  });
}

export function buildVisualIdentityRailItems(
  items: PipelineVisualIdentityRailItem[],
  durationUs: number,
): RecordingTimelineRailItem[] {
  return items.flatMap<RecordingTimelineRailItem>((item) => {
    const timeRange = {
      startUs: item.timeUs,
      endUs: Math.min(Math.max(durationUs, 0), item.timeUs + 1),
    };
    return [
      {
        id: `identity:${item.itemId}`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "identity-cards",
        label: item.label,
        state: item.state,
        timeRange,
        runId: null,
      },
      {
        id: `identity:${item.itemId}:review`,
        itemId: item.itemId,
        selectionParam: "item" as const,
        laneId: "review-state",
        label: `${item.label} · ${item.state}`,
        state: item.state,
        timeRange,
        runId: null,
      },
    ];
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

function selectedRunId(
  stage: PipelineWorkspaceStage | undefined,
  displayedRevision: string | null,
  stageKey: PipelineStageKey,
): string | null {
  if (stage?.key !== stageKey || displayedRevision === null) return null;
  return (
    stage.runs.find((run) =>
      run.output_revision_ids.includes(displayedRevision),
    )?.run_id ?? null
  );
}
