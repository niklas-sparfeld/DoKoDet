import { act, renderHook, waitFor } from "@testing-library/react";
import {
  ApiError,
  type PipelineProposalRunResponse,
  type PipelineReferenceResource,
} from "../api/client";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import { usePipelineVisibleCardEditorController } from "./PipelineVisibleCardEditorController";

const reference = {
  recording_id: "recording-1",
  content_type: "visible_cards",
  state: { draft_state: "draft" },
  draft: {
    revision: 1,
    source_revision_id: "source-old",
    proposal_revision_id: "proposal-old",
    items: [],
  },
} as unknown as PipelineReferenceResource;

function setup(
  updatePipelineReferenceDraft: ReturnType<typeof vi.fn>,
  getPipelineReference = vi.fn(async () => reference),
  proposalRevisionId: string | null = null,
  getCalibrationRefinement = vi.fn(async () => ({})),
  startCalibrationRefinement = vi.fn(async () => ({})),
  proposalRun: PipelineProposalRunResponse | null = null,
  currentReference: PipelineReferenceResource = reference,
) {
  const input = {
    client: {
      updatePipelineReferenceDraft,
      getPipelineReference,
      getCalibrationRefinement,
      startCalibrationRefinement,
    } as never,
    recordingId: "recording-1",
    operatorId: "operator-1",
    generatedRevisionId: "generated-1",
    generatedSourceRevisionId: "generated-1",
    proposalRevisionId,
    proposalRun,
    referenceRef: { current: currentReference },
    serverRevisionRef: { current: 1 },
    getFrames: () => [] as EditableFrame[],
    setLocalFrames: vi.fn(),
    completionBusy: false,
    saveState: "saved" as const,
    setSaveState: vi.fn(),
    setError: vi.fn(),
    setNotice: vi.fn(),
    setRebasingReference: vi.fn(),
    setRebasingProposal: vi.fn(),
    generatedRunId: null,
    setGeneratedFrames: vi.fn(),
    setGeneratedLoading: vi.fn(),
    setLoading: vi.fn(),
    setReference: vi.fn(),
    setSelected: vi.fn(),
    setProposalRun: vi.fn(),
    setProposalRevisionId: vi.fn(),
    setProposalLoading: vi.fn(),
    setProposalError: vi.fn(),
    setCalibrationRefinement: vi.fn(),
    calibrationRefinementRef: { current: null },
    setCalibrationLoading: vi.fn(),
    setCalibrationError: vi.fn(),
    setCreatingReference: vi.fn(),
    setCompletionBusy: vi.fn(),
    setReviewerId: vi.fn(),
    calibrationProposalRevisionId: proposalRevisionId,
    selectedFrameIdRef: { current: null },
    inspectedFrameKeysRef: { current: new Set<string>() },
    setInspectedFrameKeys: vi.fn(),
  };
  return {
    ...renderHook(() => usePipelineVisibleCardEditorController(input)),
    input,
  };
}

describe("usePipelineVisibleCardEditorController", () => {
  it("sends queued commands in order and clears the queue after success", async () => {
    let resolveFirst: ((value: PipelineReferenceResource) => void) | undefined;
    const update = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<PipelineReferenceResource>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValue(reference);
    const { result } = setup(update);

    act(() => {
      result.current.enqueue(
        { operation: "set_frame_review", item_id: "frame-1", item: {} },
        "first",
        (frames) => frames,
      );
      result.current.enqueue(
        { operation: "set_frame_review", item_id: "frame-1", item: {} },
        "second",
        (frames) => frames,
      );
    });
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(result.current.queueLength).toBe(2);
    await act(async () => resolveFirst?.(reference));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.queueLength).toBe(0));
    expect(
      update.mock.calls.map(([, , request]) => request.command_id),
    ).toEqual([
      expect.stringMatching(/^pipeline-visible-card-/),
      expect.stringMatching(/^pipeline-visible-card-/),
    ]);
  });

  it("stops on a stale revision and keeps the command available for retry", async () => {
    const update = vi.fn().mockRejectedValue(new ApiError(409, {}));
    const { result } = setup(update);
    act(() => {
      result.current.enqueue(
        { operation: "set_frame_review", item_id: "frame-1", item: {} },
        "save",
        (frames) => frames,
      );
    });

    await waitFor(() => expect(result.current.queueLength).toBe(1));
    expect(result.current.isProcessing()).toBe(false);
    expect(result.current.firstUnappliedCommand).toBe(
      "Set Frame Review frame-1",
    );
  });

  it("does not refresh calibration after an ignore-region command", async () => {
    const update = vi.fn().mockResolvedValue(reference);
    const getCalibrationRefinement = vi.fn().mockResolvedValue({});
    const { result } = setup(
      update,
      undefined,
      "proposal-1",
      getCalibrationRefinement,
    );

    act(() => {
      result.current.enqueue(
        {
          operation: "create_ignore_region",
          item_id: "frame-1",
          region: {} as never,
        },
        "ignore",
        (frames) => frames,
      );
    });

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(getCalibrationRefinement).not.toHaveBeenCalled();
  });

  it("uses the explicit start action to refresh calibration", async () => {
    const update = vi.fn().mockResolvedValue(reference);
    const getCalibrationRefinement = vi.fn().mockResolvedValue({});
    const startCalibrationRefinement = vi.fn().mockResolvedValue({
      preview: { status: "pass" },
    });
    const { result, input } = setup(
      update,
      undefined,
      "proposal-1",
      getCalibrationRefinement,
      startCalibrationRefinement,
    );
    input.calibrationRefinementRef.current = {
      draft: { draft_id: "draft-1" },
    } as never;

    await act(async () => result.current.refreshCalibrationPreview());

    expect(startCalibrationRefinement).toHaveBeenCalledWith("recording-1", {
      proposal_revision_id: "proposal-1",
      draft_id: "draft-1",
    });
    expect(getCalibrationRefinement).not.toHaveBeenCalled();
  });

  it("retries a temporary command failure and then drains the queue", async () => {
    vi.useFakeTimers();
    try {
      const update = vi
        .fn()
        .mockRejectedValueOnce(new Error("temporary"))
        .mockResolvedValue(reference);
      const { result } = setup(update);
      act(() => {
        result.current.enqueue(
          { operation: "set_frame_review", item_id: "frame-1", item: {} },
          "save",
          (frames) => frames,
        );
      });
      await act(async () => Promise.resolve());
      expect(update).toHaveBeenCalledTimes(1);
      await act(async () => vi.advanceTimersByTimeAsync(100));
      expect(update).toHaveBeenCalledTimes(2);
      expect(result.current.queueLength).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops after a terminal command failure", async () => {
    const update = vi.fn().mockRejectedValue(new ApiError(422, {}));
    const { result, input } = setup(update);
    act(() => {
      result.current.enqueue(
        { operation: "set_frame_review", item_id: "frame-1", item: {} },
        "save",
        (frames) => frames,
      );
    });
    await waitFor(() =>
      expect(input.setSaveState).toHaveBeenCalledWith("error"),
    );
    expect(result.current.queueLength).toBe(1);
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("rebases to the selected proposal through the controller API", async () => {
    const update = vi.fn().mockResolvedValue(reference);
    const proposalRun = {
      request: { input_revision_ids: ["proposal-source"] },
      state: { output_revision_ids: ["proposal-new"] },
    } as unknown as PipelineProposalRunResponse;
    const { result } = setup(
      update,
      undefined,
      "proposal-new",
      undefined,
      undefined,
      proposalRun,
    );

    await act(async () => result.current.rebaseReferenceToProposal());

    expect(update).toHaveBeenCalledWith(
      "recording-1",
      "visible_cards",
      expect.objectContaining({
        expected_revision: 1,
        operator_id: "operator-1",
        operations: [
          {
            operation: "rebase",
            source_revision_id: "proposal-source",
            proposal_revision_id: "proposal-new",
          },
        ],
      }),
    );
  });

  it("starts a reference from the selected proposal's detector input", async () => {
    const update = vi.fn().mockResolvedValue(reference);
    const proposalRun = {
      request: { input_revision_ids: ["proposal-source"] },
      state: { output_revision_ids: ["proposal-new"] },
    } as unknown as PipelineProposalRunResponse;
    const emptyReference = {
      ...reference,
      draft: {
        ...reference.draft,
        source_revision_id: null,
        items: [],
      },
    } as PipelineReferenceResource;
    const { result } = setup(
      update,
      undefined,
      "proposal-new",
      undefined,
      undefined,
      proposalRun,
      emptyReference,
    );

    act(() => result.current.startReference());

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0][2].operations).toEqual([
      {
        operation: "rebase",
        source_revision_id: "proposal-source",
        proposal_revision_id: "proposal-new",
      },
    ]);
  });

  it("clears its retry timer when the controller unmounts", async () => {
    vi.useFakeTimers();
    try {
      const update = vi.fn().mockRejectedValue(new Error("temporary"));
      const { result, unmount } = setup(update);
      act(() => {
        result.current.enqueue(
          { operation: "set_frame_review", item_id: "frame-1", item: {} },
          "save",
          (frames) => frames,
        );
      });
      await act(async () => Promise.resolve());
      expect(vi.getTimerCount()).toBe(1);
      unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
