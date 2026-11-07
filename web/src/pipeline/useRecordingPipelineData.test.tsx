import { act, renderHook, waitFor } from "@testing-library/react";

import type { PipelineWorkspace } from "../api/pipelineContracts";
import { useRecordingPipelineData } from "./useRecordingPipelineData";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function workspace(recordingId: string, marker: string): PipelineWorkspace {
  return {
    schema_version: "pipeline-workspace/v1",
    recording_id: recordingId,
    video: {
      schema_version: "recording-video/v1",
      recording_id: recordingId,
      relative_path: `${recordingId}/video.mp4`,
      video_sha256: "a".repeat(64),
      byte_length: 1,
      duration_us: 1,
    },
    stages: [
      "events",
      "visible_cards",
      "visual_identities",
      "table_observations",
      "round_analyses",
    ].map((key) => ({
      key,
      processor_key: `${key}-processor`,
      processor_type: `${key}-processor`,
      output_content_type: key,
      state: "video-only",
      input_options: [],
      selection_revision: null,
      selected_generated: null,
      selected_completed_reference: null,
      runs: [],
      analyses: [],
      compatible_input_sets: [],
      can_run: true,
      run_blockers: [],
      comparable_run_ids: [],
    })),
    diagnostics: [{ code: marker, message: marker, revision_id: null }],
  } as PipelineWorkspace;
}

function graphFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("unavailable", { status: 503 })),
    ),
  );
}

describe("recording pipeline workspace data", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("ignores a late response after switching recordings", async () => {
    graphFetch();
    const first = deferred<PipelineWorkspace>();
    const second = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi.fn((recordingId: string) =>
      recordingId === "first" ? first.promise : second.promise,
    );
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({
        recordingId,
        stageKey,
      }: {
        recordingId: string;
        stageKey: "events" | "visible_cards";
      }) => useRecordingPipelineData(recordingId, stageKey, null, client),
      { initialProps: { recordingId: "first", stageKey: "events" } },
    );

    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(1));
    rerender({ recordingId: "second", stageKey: "events" });
    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(2));
    await act(async () => second.resolve(workspace("second", "new-recording")));
    await waitFor(() =>
      expect(result.current.workspace?.recording_id).toBe("second"),
    );
    await act(async () => first.resolve(workspace("first", "stale-recording")));
    expect(result.current.workspace?.diagnostics[0].code).toBe("new-recording");
  });

  it("ignores a late response after switching stages", async () => {
    graphFetch();
    const events = deferred<PipelineWorkspace>();
    const visibleCards = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi.fn(
      (_recordingId: string, _init: unknown, stage: string) =>
        stage === "events" ? events.promise : visibleCards.promise,
    );
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({ stageKey }: { stageKey: "events" | "visible_cards" }) =>
        useRecordingPipelineData("recording", stageKey, null, client),
      { initialProps: { stageKey: "events" } },
    );

    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(1));
    rerender({ stageKey: "visible_cards" });
    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(2));
    await act(async () =>
      visibleCards.resolve(workspace("recording", "visible")),
    );
    await waitFor(() =>
      expect(result.current.loadedStageKey).toBe("visible_cards"),
    );
    await act(async () =>
      events.resolve(workspace("recording", "events-stale")),
    );
    expect(result.current.workspace?.diagnostics[0].code).toBe("visible");
  });

  it("keeps only the newest workspace refresh response", async () => {
    graphFetch();
    const initial = deferred<PipelineWorkspace>();
    const olderRefresh = deferred<PipelineWorkspace>();
    const newerRefresh = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi
      .fn()
      .mockReturnValueOnce(initial.promise)
      .mockReturnValueOnce(olderRefresh.promise)
      .mockReturnValueOnce(newerRefresh.promise);
    const client = { getRecordingPipeline } as never;
    const { result } = renderHook(() =>
      useRecordingPipelineData("recording", "events", null, client),
    );

    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(1));
    await act(async () => initial.resolve(workspace("recording", "initial")));
    await act(async () => {
      void result.current.loadWorkspace();
      void result.current.loadWorkspace();
    });
    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(3));
    await act(async () =>
      newerRefresh.resolve(workspace("recording", "newest")),
    );
    await act(async () =>
      olderRefresh.resolve(workspace("recording", "older")),
    );
    expect(result.current.workspace?.diagnostics[0].code).toBe("newest");
  });

  it("reports lineage graph errors without changing the saved selection", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("failure", { status: 503 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const getRecordingPipeline = vi.fn(() =>
      Promise.resolve(workspace("recording", "ok")),
    );
    const client = { getRecordingPipeline } as never;
    const { result } = renderHook(() =>
      useRecordingPipelineData("recording", "events", "saved-lineage", client),
    );

    await waitFor(() =>
      expect(result.current.lineageGraphError).toBe(
        "Lineage data could not be loaded.",
      ),
    );
    expect(result.current.lineageValidation).toEqual({
      lineage: "saved-lineage",
      notice:
        "Lineage data could not be loaded. The saved selection was not changed.",
    });
  });
});
