import { buildRecordingWorkspacePresentation } from "./recordingWorkspacePresentation";
import {
  pipelineRevision,
  pipelineRun,
  pipelineWorkspace,
  recordingPipelinePresentationFixture,
  roundAnalysisPresentationFixture,
} from "../test/recordingPipelineFixtures";
import {
  expectedWorkspaceGeometry,
  RECORDING_WORKSPACE_VIEWPORTS,
  WORKSPACE_GEOMETRY_LIMITS,
} from "../test/workspaceGeometry";

describe("recording workspace presentation model", () => {
  it("represents loading and failed shell states without an API response", () => {
    expect(
      buildRecordingWorkspacePresentation({ workspace: null, loading: true }),
    ).toMatchObject({
      state: "loading",
      stage: null,
      rail: null,
      inspector: { primaryAction: null },
    });

    expect(
      buildRecordingWorkspacePresentation({
        workspace: null,
        error: "The accepted recording video is unavailable.",
      }),
    ).toMatchObject({
      state: "failed",
      stage: null,
      inspector: {
        activeBlocker: "The accepted recording video is unavailable.",
        saveState: "failed",
      },
    });
  });

  it.each([
    ["video-only", "video", "idle"],
    ["empty", "video", "idle"],
    ["generated-only", "video", "idle"],
    ["draft", "video", "draft"],
    ["affected", "video", "affected"],
    ["failed", "video", "failed"],
    ["complete", "video", "complete"],
  ] as const)(
    "maps the %s stage state into a stable task, inspector, and rail model",
    (state, surfaceMode, saveState) => {
      const presentation = buildRecordingWorkspacePresentation({
        workspace: recordingPipelinePresentationFixture(state),
        stageKey: "events",
      });

      expect(presentation.state).toBe(state);
      expect(presentation.surface.mode).toBe(surfaceMode);
      expect(presentation.inspector.saveState).toBe(saveState);
      expect(
        presentation.inspector.sections.map((section) => section.key),
      ).toEqual([
        "progress",
        "action",
        "save-state",
        "selection",
        "metadata",
        "details",
      ]);
      expect(presentation.rail?.durationUs).toBe(90_000_000);
      expect(presentation.rail?.lanes.map((lane) => lane.label)).toEqual([
        "Events",
        "Proposals",
        "Review state",
        "Coverage",
      ]);
    },
  );

  it("normalizes stage-specific task modes for every implemented stage", () => {
    const expectedModes = {
      events: "video",
      visible_cards: "source-frame",
      visual_identities: "identity-crop",
      table_observations: "observation",
      round_analyses: "analysis",
    } as const;

    for (const [stageKey, mode] of Object.entries(expectedModes)) {
      const workspace =
        stageKey === "round_analyses"
          ? roundAnalysisPresentationFixture()
          : pipelineWorkspace();
      const presentation = buildRecordingWorkspacePresentation({
        workspace,
        stageKey: stageKey as keyof typeof expectedModes,
      });

      expect(presentation.stage?.key).toBe(stageKey);
      expect(presentation.surface.mode).toBe(mode);
      expect(presentation.rail?.lanes.length).toBeGreaterThan(0);
      expect(presentation.topBar.stageTabs).toHaveLength(5);
    }
  });

  it("uses one comparison surface while retaining the selected stage rail", () => {
    const presentation = buildRecordingWorkspacePresentation({
      workspace: recordingPipelinePresentationFixture("complete"),
      stageKey: "events",
      compare: true,
    });

    expect(presentation.surface.mode).toBe("comparison");
    expect(presentation.rail?.items).toEqual([]);
    expect(presentation.rail?.lanes).toEqual([
      expect.objectContaining({ id: "differences", label: "Differences" }),
      expect.objectContaining({ id: "matches", label: "Matches" }),
    ]);
    expect(presentation.inspector.primaryAction).toMatchObject({
      kind: "compare",
      label: "Compare",
    });
  });

  it("surfaces the first actionable blocker next to a blocked action", () => {
    const presentation = buildRecordingWorkspacePresentation({
      workspace: pipelineWorkspace({
        stageOverrides: {
          events: {
            state: "empty",
            can_run: false,
            run_blockers: ["Select an input revision first."],
            review_blockers: ["No maintained reference exists."],
          },
        },
      }),
      stageKey: "events",
    });

    expect(presentation.inspector.primaryAction).toEqual({
      kind: "blocked",
      label: "Blocked",
      blocker: "Select an input revision first.",
    });
    expect(presentation.inspector.activeBlocker).toBe(
      "Select an input revision first.",
    );
  });

  it("normalizes rail item identity, time, labels, and progress from existing run data", () => {
    const generated = pipelineRevision("events-generated-1");
    const run = pipelineRun("run-events-1", {
      status: "complete",
      output_revision_ids: [generated.revision_id],
      progress: { completed: 1, total: 2 },
      state: {
        items: [
          {
            item_id: "event-1",
            status: "succeeded",
            result: {
              event_type: "card_played",
              start_us: 1_000_000,
              end_us: 1_500_000,
            },
            failure: null,
          },
        ],
      },
    });
    const presentation = buildRecordingWorkspacePresentation({
      workspace: pipelineWorkspace({
        stageOverrides: {
          events: {
            state: "generated-only",
            input_options: [generated],
            selected_generated_revision_id: generated.revision_id,
            runs: [run],
          },
        },
      }),
      stageKey: "events",
      urlState: {
        view: "generated",
        revision: generated.revision_id,
        item: "event-1",
        tUs: 999_000_000,
      },
    });

    expect(presentation.inspector.selection).toMatchObject({
      view: "generated",
      revisionId: generated.revision_id,
      itemId: "event-1",
      timeUs: 90_000_000,
    });
    expect(presentation.inspector.progress).toMatchObject({
      completed: 1,
      total: 2,
      percent: 50,
    });
    expect(presentation.rail?.selectedItemId).toBe("run-events-1:event-1");
    expect(presentation.rail?.items).toEqual([
      {
        id: "run-events-1:event-1",
        itemId: "event-1",
        selectionParam: "item",
        laneId: "proposals",
        label: "card_played",
        state: "succeeded",
        timeRange: { startUs: 1_000_000, endUs: 1_500_000 },
        runId: "run-events-1",
      },
    ]);
  });

  it("uses analysis progress and analysis items for the final stage", () => {
    const presentation = buildRecordingWorkspacePresentation({
      workspace: roundAnalysisPresentationFixture(),
      stageKey: "round_analyses",
      urlState: { analysis: "analysis-1" },
    });

    expect(presentation.surface.mode).toBe("analysis");
    expect(presentation.inspector.selection).toMatchObject({
      analysisId: "analysis-1",
    });
    expect(presentation.inspector.progress).toMatchObject({
      completed: 1,
      total: 1,
      percent: 100,
      label: "Analysis progress",
    });
    expect(presentation.rail?.items[0]).toMatchObject({
      itemId: "analysis-1",
      laneId: "analysis-evidence",
      label: "round-1",
      state: "complete",
    });
    expect(presentation.rail?.selectedItemId).toBe("analysis:analysis-1");
  });

  it("keeps the required viewport fixtures and geometry limits in one place", () => {
    expect(RECORDING_WORKSPACE_VIEWPORTS).toEqual({
      desktop: { name: "desktop", width: 1440, height: 900 },
      compactDesktop: { name: "compact desktop", width: 1280, height: 800 },
      narrow: { name: "narrow", width: 390, height: 844 },
    });
    expect(
      expectedWorkspaceGeometry(RECORDING_WORKSPACE_VIEWPORTS.desktop),
    ).toMatchObject({
      desktop: true,
      inspectorMinWidth: WORKSPACE_GEOMETRY_LIMITS.inspectorMinWidth,
      inspectorMaxWidth: WORKSPACE_GEOMETRY_LIMITS.inspectorMaxWidth,
      topBarMaxHeight: 112,
      railMinHeight: 96,
    });
    expect(
      expectedWorkspaceGeometry(RECORDING_WORKSPACE_VIEWPORTS.narrow).desktop,
    ).toBe(false);
  });
});
