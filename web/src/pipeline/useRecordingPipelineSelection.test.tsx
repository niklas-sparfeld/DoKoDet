import { act, renderHook } from "@testing-library/react";
import { vi } from "vitest";

import { ApiError } from "../api/transport";
import type { PipelineWorkspaceStage } from "../api/pipelineContracts";
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

function stage(recordingId: string): PipelineWorkspaceStage {
  return {
    key: "events",
    processor_key: "events-processor",
    processor_type: "events-processor",
    output_content_type: "events",
    state: "data-available",
    input_options: [
      {
        revision_id: `${recordingId}-revision`,
        node_id: `${recordingId}-node`,
        node_revision_id: `${recordingId}-node-revision`,
        is_current_head: true,
        content_type: "events",
        origin: "processor",
        completion_state: "complete",
        coverage_state: "full-recording",
        display_label: `${recordingId} generated events`,
        content_sha256: "a".repeat(64),
        input_revision_ids: [],
        producer: {},
        coverage: {},
        created_at: "2026-09-06T00:00:00Z",
      },
    ],
    selection_revision: 1,
    selected_generated: null,
    selected_completed_reference: null,
    runs: [],
    analyses: [],
    compatible_input_sets: [],
    can_run: true,
    run_blockers: [],
    comparable_run_ids: [],
  } as unknown as PipelineWorkspaceStage;
}

describe("recording pipeline selection request ownership", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["success", "failure", "conflict"] as const)(
    "ignores a delayed old-recording %s after the new workspace loads",
    async (outcome) => {
      const oldRequest = deferred<never>();
      const setWorkspace = vi.fn();
      const setNotice = vi.fn();
      const loadWorkspace = vi.fn(async () => {});
      const updatePipelineSelection = vi
        .fn()
        .mockReturnValueOnce(oldRequest.promise)
        .mockResolvedValueOnce({
          selection: {
            revision: 2,
            selected_generated: {
              node_id: "B-node",
              revision_id: "B-node-revision",
            },
            selected_completed_reference: null,
          },
        });
      const client = { updatePipelineSelection } as never;
      const makeProps = (recordingId: string) => ({
        recordingId,
        stage: stage(recordingId),
      });
      const { result, rerender } = renderHook(
        ({ recordingId, stage: selectedStage }) =>
          useRecordingPipelineSelection({
            recordingId,
            stageKey: "events",
            compare: false,
            backendStageKey: "events",
            stage: selectedStage,
            setWorkspace,
            loadWorkspace,
            client,
            setNotice,
            urlState: {} as never,
            setUrlState: vi.fn(),
          }),
        { initialProps: makeProps("A") },
      );

      let oldAttempt!: Promise<void>;
      act(() => {
        oldAttempt = result.current.selectGeneratedRevision("A-node-revision");
      });
      setNotice.mockClear();
      rerender(makeProps("B"));
      expect(result.current.selectionBusy).toBe(false);

      if (outcome === "success") {
        await act(async () =>
          oldRequest.resolve({
            selection: {
              revision: 2,
              selected_generated: {
                node_id: "A-node",
                revision_id: "A-node-revision",
              },
              selected_completed_reference: null,
            },
          } as never),
        );
      } else {
        await act(async () =>
          oldRequest.reject(
            outcome === "conflict"
              ? new ApiError(409, {})
              : new Error("offline"),
          ),
        );
      }
      await oldAttempt;

      expect(setWorkspace).not.toHaveBeenCalled();
      expect(setNotice).not.toHaveBeenCalled();
      expect(loadWorkspace).not.toHaveBeenCalled();
      expect(result.current.selectionBusy).toBe(false);

      await act(async () => {
        await result.current.selectGeneratedRevision("B-node-revision");
      });
      expect(updatePipelineSelection).toHaveBeenLastCalledWith("B", "events", {
        expected_revision: 1,
        selected_generated: {
          node_id: "B-node",
          revision_id: "B-node-revision",
        },
      });
      expect(setNotice).toHaveBeenLastCalledWith(
        "Processor input revision selected.",
      );
      expect(result.current.selectionBusy).toBe(false);
    },
  );
});
