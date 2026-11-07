import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { JobDetail } from "../api/jobsContracts";
import {
  ExactRevisionField,
  JobModelField,
  type ExactRevisionChoice,
} from "./JobStartFields";
import {
  AcceptedJobReceipt,
  useJobSubmission,
  type JobEnqueue,
} from "./useJobSubmission";
import { useJobStartChoices } from "./useJobStartChoices";

const job = { id: "job-1" } as JobDetail;
const payload = {
  type: "visible_card_processing",
  context: { recording_id: "recording-1" },
  request: {
    inputs: [
      { node_id: "events", revision_id: "e2" },
      { node_id: "calibration", revision_id: "c4" },
    ],
  },
};

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "key-1") });
});

describe("job start fields", () => {
  it("requires a choice when revisions are ambiguous and carries each exact revision", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const choices: ExactRevisionChoice[] = [
      {
        nodeId: "events-a",
        revisionId: "e2",
        label: "Events A",
        compatible: true,
      },
      {
        nodeId: "events-b",
        revisionId: "e7",
        label: "Events B",
        compatible: true,
      },
    ];
    render(
      <>
        <ExactRevisionField
          label="Events revision"
          choices={choices}
          value=""
          onChange={onChange}
        />
        <ExactRevisionField
          label="Calibration revision"
          choices={[
            {
              nodeId: "cal",
              revisionId: "c4",
              label: "Calibration",
              compatible: true,
            },
          ]}
          value=""
          onChange={onChange}
        />
      </>,
    );
    expect(screen.getByLabelText("Events revision")).toHaveValue("");
    await user.selectOptions(
      screen.getByLabelText("Events revision"),
      "events-b:e7",
    );
    await user.selectOptions(
      screen.getByLabelText("Calibration revision"),
      "cal:c4",
    );
    expect(onChange).toHaveBeenNthCalledWith(1, "events-b:e7");
    expect(onChange).toHaveBeenNthCalledWith(2, "cal:c4");
  });

  it("shows unavailable models and prevents selecting them", () => {
    render(
      <JobModelField
        label="Model"
        choices={[
          { id: "model-ok", label: "Model OK", available: true },
          {
            id: "model-off",
            label: "Model off",
            available: false,
            reason: "provider unavailable",
          },
        ]}
        value=""
        onChange={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Model off unavailable: provider unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Model off" }),
    ).not.toBeInTheDocument();
  });
});

describe("dependent choices", () => {
  it("ignores a late response after the selected recording changes", async () => {
    const resolvers: Array<(value: string[]) => void> = [];
    const load = vi.fn((signal: AbortSignal) =>
      signal.aborted
        ? Promise.resolve([])
        : new Promise<string[]>((resolve) => {
            resolvers.push(resolve);
          }),
    );
    function Fixture({ recording }: { recording: string }) {
      const state = useJobStartChoices(recording, load);
      return <div>{state.loading ? "loading" : state.choices.join(",")}</div>;
    }
    const view = render(<Fixture recording="recording-a" />);
    view.rerender(<Fixture recording="recording-b" />);
    await act(async () => resolvers[0]?.(["stale-model"]));
    expect(screen.getByText("loading")).toBeInTheDocument();
  });
});

describe("shared job submission", () => {
  it("prevents double submission and exposes one accepted job receipt", async () => {
    let resolve!: (value: JobDetail) => void;
    const enqueue = vi.fn(
      () => new Promise<JobDetail>((done) => (resolve = done)),
    ) as JobEnqueue;
    const accepted = vi.fn();
    const { result } = renderHook(() => useJobSubmission(enqueue, accepted));
    let first: Promise<JobDetail | null>;
    await act(async () => {
      first = result.current.submit(payload);
      await result.current.submit(payload);
    });
    expect(enqueue).toHaveBeenCalledTimes(1);
    expect(enqueue).toHaveBeenCalledWith(payload, "key-1");
    await act(async () => resolve(job));
    await act(async () => first!);
    expect(accepted).toHaveBeenCalledTimes(1);
    render(<AcceptedJobReceipt job={result.current.job!} />);
    expect(screen.getByRole("link", { name: "job-1" })).toHaveAttribute(
      "href",
      "/jobs/job-1",
    );
  });

  it("reuses the same key and frozen payload after uncertain acceptance", async () => {
    const enqueue = vi
      .fn<JobEnqueue>()
      .mockRejectedValueOnce(new Error("connection lost"))
      .mockResolvedValueOnce(job);
    const { result } = renderHook(() => useJobSubmission(enqueue));
    await act(async () => {
      await result.current.submit(payload);
    });
    expect(result.current.error).toMatch(/uncertain/i);
    await act(async () => {
      await result.current.submit(payload);
    });
    expect(enqueue.mock.calls.map((call) => call[1])).toEqual([
      "key-1",
      "key-1",
    ]);
    expect(enqueue.mock.calls[0]?.[0]).toEqual(enqueue.mock.calls[1]?.[0]);
    expect(result.current.job).toBe(job);
  });

  it("clears a rejected request key so corrected inputs form a new request", async () => {
    const enqueue = vi
      .fn<JobEnqueue>()
      .mockRejectedValueOnce({ status: 409 })
      .mockResolvedValueOnce(job);
    let keyIndex = 0;
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `key-${++keyIndex}`) });
    const { result } = renderHook(() => useJobSubmission(enqueue));
    await act(async () => {
      await result.current.submit(payload);
    });
    await act(async () => {
      await result.current.submit({ ...payload, request: { inputs: [] } });
    });
    expect(enqueue.mock.calls.map((call) => call[1])).toEqual([
      "key-1",
      "key-2",
    ]);
    expect(result.current.error).toBeNull();
  });

  it("can reconcile a lost response after recording navigation through the same submit owner", async () => {
    const enqueue = vi
      .fn<JobEnqueue>()
      .mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(job);
    const { result, rerender } = renderHook(
      ({ recording }) => ({
        ...useJobSubmission(enqueue, () => undefined),
        recording,
      }),
      { initialProps: { recording: "recording-1" } },
    );
    await act(async () => {
      await result.current.submit(payload);
    });
    rerender({ recording: "recording-2" });
    await act(async () => {
      await result.current.submit(payload);
    });
    expect(enqueue).toHaveBeenCalledTimes(2);
    expect(enqueue.mock.calls[1]?.[1]).toBe(enqueue.mock.calls[0]?.[1]);
    expect(result.current.job).toBe(job);
  });
});
