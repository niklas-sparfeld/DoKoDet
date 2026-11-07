import { act, renderHook, waitFor } from "@testing-library/react";

import { ApiError } from "../api/transport";
import type { PipelineWorkspace } from "../api/pipelineContracts";
import { useRecordingPipelineData } from "./useRecordingPipelineData";
import { useRecordingPipelineSelection } from "./useRecordingPipelineSelection";

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
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each(["success", "failure"] as const)(
    "ignores a deferred A conflict-reload %s after B renders before its load timer",
    async (outcome) => {
      vi.useFakeTimers();
      graphFetch();
      const conflictReload = deferred<PipelineWorkspace>();
      const getRecordingPipeline = vi
        .fn()
        .mockResolvedValueOnce(workspace("A", "initial-A"))
        .mockReturnValueOnce(conflictReload.promise)
        .mockResolvedValueOnce(workspace("B", "new-B"));
      const updatePipelineSelection = vi.fn(() =>
        Promise.reject(new ApiError(409, {})),
      );
      const client = { getRecordingPipeline, updatePipelineSelection } as never;
      const setNotice = vi.fn();
      const { result, rerender } = renderHook(
        ({ recordingId }: { recordingId: string }) => {
          const data = useRecordingPipelineData(
            recordingId,
            "events",
            null,
            client,
          );
          const selection = useRecordingPipelineSelection({
            recordingId,
            stageKey: "events",
            compare: false,
            backendStageKey: "events",
            stage: data.workspace?.stages[0],
            setWorkspace: data.setWorkspace,
            loadWorkspace: data.loadWorkspace,
            client,
            setNotice,
            urlState: {} as never,
            setUrlState: vi.fn(),
          });
          return { data, selection };
        },
        { initialProps: { recordingId: "A" } },
      );

      await act(async () => {
        vi.runOnlyPendingTimers();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(result.current.data.workspace?.diagnostics[0].code).toBe(
        "initial-A",
      );

      let conflictAttempt!: Promise<void>;
      act(() => {
        conflictAttempt =
          result.current.selection.selectGeneratedRevision(null);
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(getRecordingPipeline).toHaveBeenCalledTimes(2);
      setNotice.mockClear();

      rerender({ recordingId: "B" });
      if (outcome === "success") {
        await act(async () =>
          conflictReload.resolve(workspace("A", "stale-conflict-reload")),
        );
      } else {
        await act(async () => conflictReload.reject(new Error("offline")));
      }
      await act(async () => conflictAttempt);

      expect(result.current.data.workspace?.diagnostics[0].code).toBe(
        "initial-A",
      );
      expect(result.current.data.error).toBeNull();
      expect(setNotice).not.toHaveBeenCalled();

      await act(async () => {
        vi.runOnlyPendingTimers();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(getRecordingPipeline).toHaveBeenCalledTimes(3);
      expect(result.current.data.workspace?.recording_id).toBe("B");
      expect(result.current.data.workspace?.diagnostics[0].code).toBe("new-B");
    },
  );

  it("starts a fresh A load after a scheduled B switch is canceled", async () => {
    vi.useFakeTimers();
    graphFetch();
    const firstA = deferred<PipelineWorkspace>();
    const secondA = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi
      .fn()
      .mockReturnValueOnce(firstA.promise)
      .mockReturnValueOnce(secondA.promise);
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({ recordingId }: { recordingId: string }) =>
        useRecordingPipelineData(recordingId, "events", null, client),
      { initialProps: { recordingId: "A" } },
    );

    await act(async () => vi.runOnlyPendingTimers());
    expect(getRecordingPipeline).toHaveBeenCalledTimes(1);
    rerender({ recordingId: "B" });
    rerender({ recordingId: "A" });
    await act(async () => vi.runOnlyPendingTimers());

    expect(getRecordingPipeline).toHaveBeenCalledTimes(2);
    await act(async () => secondA.resolve(workspace("A", "replacement-A")));
    expect(result.current.workspace?.diagnostics[0].code).toBe("replacement-A");
    await act(async () => firstA.resolve(workspace("A", "aborted-A")));
    expect(result.current.workspace?.diagnostics[0].code).toBe("replacement-A");
  });

  it("allows B to load again after a failed B load and return through A", async () => {
    vi.useFakeTimers();
    graphFetch();
    const firstA = deferred<PipelineWorkspace>();
    const failedB = deferred<PipelineWorkspace>();
    const retriedB = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi
      .fn()
      .mockReturnValueOnce(firstA.promise)
      .mockReturnValueOnce(failedB.promise)
      .mockReturnValueOnce(retriedB.promise);
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({ recordingId }: { recordingId: string }) =>
        useRecordingPipelineData(recordingId, "events", null, client),
      { initialProps: { recordingId: "A" } },
    );

    await act(async () => vi.runOnlyPendingTimers());
    await act(async () => firstA.resolve(workspace("A", "first-A")));
    rerender({ recordingId: "B" });
    await act(async () => vi.runOnlyPendingTimers());
    await act(async () => failedB.reject(new Error("failed B")));
    rerender({ recordingId: "A" });
    await act(async () => vi.runOnlyPendingTimers());
    rerender({ recordingId: "B" });
    await act(async () => vi.runOnlyPendingTimers());

    expect(getRecordingPipeline).toHaveBeenCalledTimes(3);
    await act(async () => retriedB.resolve(workspace("B", "retried-B")));
    expect(result.current.workspace?.diagnostics[0].code).toBe("retried-B");
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

  it("loads the new recording after the prior recording has completed", async () => {
    graphFetch();
    const first = deferred<PipelineWorkspace>();
    const second = deferred<PipelineWorkspace>();
    const getRecordingPipeline = vi.fn((recordingId: string) =>
      recordingId === "first" ? first.promise : second.promise,
    );
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({ recordingId }: { recordingId: string }) =>
        useRecordingPipelineData(recordingId, "events", null, client),
      { initialProps: { recordingId: "first" } },
    );

    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(1));
    await act(async () => first.resolve(workspace("first", "first-loaded")));
    await waitFor(() =>
      expect(result.current.workspace?.recording_id).toBe("first"),
    );

    rerender({ recordingId: "second" });
    await waitFor(() => expect(getRecordingPipeline).toHaveBeenCalledTimes(2));
    expect(result.current.workspace?.recording_id).toBe("first");
    await act(async () => second.resolve(workspace("second", "second-loaded")));
    await waitFor(() =>
      expect(result.current.workspace?.recording_id).toBe("second"),
    );
  });

  it("does not expose the prior recording graph while the new graph loads", async () => {
    const firstGraph = deferred<Response>();
    const secondGraph = deferred<Response>();
    const fetchMock = vi.fn<typeof fetch>((input) =>
      String(input).includes("/first/pipeline/lineage")
        ? firstGraph.promise
        : secondGraph.promise,
    );
    vi.stubGlobal("fetch", fetchMock);
    const getRecordingPipeline = vi.fn(() =>
      Promise.resolve(workspace("recording", "ok")),
    );
    const client = { getRecordingPipeline } as never;
    const { result, rerender } = renderHook(
      ({ recordingId }: { recordingId: string }) =>
        useRecordingPipelineData(recordingId, "events", null, client),
      { initialProps: { recordingId: "first" } },
    );
    const graphResponse = (recordingId: string) =>
      new Response(
        JSON.stringify({
          schema_version: "pipeline-lineage-graph/v1",
          nodes: [{ node_id: `${recordingId}-node` }],
          revisions: [],
          runs: [],
          artifacts: [],
          edges: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await act(async () => firstGraph.resolve(graphResponse("first")));
    await waitFor(() =>
      expect(result.current.lineageGraph?.nodes[0].node_id).toBe("first-node"),
    );

    rerender({ recordingId: "second" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(result.current.lineageGraph).toBeNull();
    expect(result.current.lineageGraphError).toBeNull();

    await act(async () => secondGraph.resolve(graphResponse("second")));
    await waitFor(() =>
      expect(result.current.lineageGraph?.nodes[0].node_id).toBe("second-node"),
    );
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
