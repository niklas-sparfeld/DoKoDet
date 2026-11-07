import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadWorkingAreaFrame,
  resetWorkingAreaFrameCacheForTests,
  useWorkingAreaFrame,
  workingAreaFrameCanMutate,
  workingAreaFramePath,
  type WorkingAreaFrameRequest,
} from "./workingAreaFrame";

const digest = "a".repeat(64);

function request(
  overrides: Partial<WorkingAreaFrameRequest> = {},
): WorkingAreaFrameRequest {
  return {
    recordingId: "recording-1",
    sourceId: "source-revision-1",
    sourceSha256: digest,
    requestedTimeUs: 1_234_567,
    mode: "exact",
    ...overrides,
  };
}

function frameResponse({
  sourceSha256 = digest,
  requestedTimeUs = 1_234_567,
  resolvedTimeUs = 1_240_000,
  frameIndex = 37,
  status = 200,
}: {
  sourceSha256?: string;
  requestedTimeUs?: number;
  resolvedTimeUs?: number;
  frameIndex?: number;
  status?: number;
} = {}): Response {
  return new Response(new Blob(["frame"]), {
    status,
    headers: {
      ETag: `"${"b".repeat(64)}"`,
      "X-DokoDetector-Source-Sha256": sourceSha256,
      "X-DokoDetector-Frame-Index": String(frameIndex),
      "X-DokoDetector-Frame-Width": "640",
      "X-DokoDetector-Frame-Height": "360",
      "X-DokoDetector-Requested-Time-Us": String(requestedTimeUs),
      "X-DokoDetector-Frame-Time-Us": String(resolvedTimeUs),
      "X-DokoDetector-Frame-Interval-Us": "0",
    },
  });
}

function FrameProbe({ value }: { value: WorkingAreaFrameRequest }) {
  const result = useWorkingAreaFrame(value);
  if (result.state === "loading")
    return <div>loading {result.request.requestedTimeUs}</div>;
  if (result.state === "failed") return <div>failed {result.reason}</div>;
  return (
    <div>
      ready {result.frame.requestedTimeUs}/{result.frame.resolvedTimeUs}{" "}
      {result.frame.identity.frameId}{" "}
      {String(workingAreaFrameCanMutate(result.frame))}
    </div>
  );
}

describe("workingAreaFrame", () => {
  beforeEach(() => {
    resetWorkingAreaFrameCacheForTests();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:frame");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("retains requested and resolved identity and allows mutation only for exact frames", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(frameResponse()));
    const exact = await loadWorkingAreaFrame(request());
    expect(exact.requestedTimeUs).toBe(1_234_567);
    expect(exact.resolvedTimeUs).toBe(1_240_000);
    expect(exact.identity).toEqual({
      sourceId: `source-revision-1:${digest}`,
      frameId: "37@1240000",
      width: 640,
      height: 360,
      contentSha256: "b".repeat(64),
    });
    expect(workingAreaFrameCanMutate(exact)).toBe(true);

    const sampledRequest = request({ mode: "sampled" });
    expect(workingAreaFramePath(sampledRequest)).toContain(
      "preview=sampled_250ms",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(frameResponse({ requestedTimeUs: 1_250_000 })),
    );
    const sampled = await loadWorkingAreaFrame(sampledRequest);
    expect(sampled.requestedTimeUs).toBe(1_234_567);
    expect(sampled.resolvedTimeUs).toBe(1_240_000);
    expect(workingAreaFrameCanMutate(sampled)).toBe(false);
  });

  it("reports source changes and request failures explicitly", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(frameResponse({ sourceSha256: "c".repeat(64) })),
    );
    await expect(loadWorkingAreaFrame(request())).rejects.toThrow(
      "source changed",
    );

    resetWorkingAreaFrameCacheForTests();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(frameResponse({ status: 503 })),
    );
    await expect(loadWorkingAreaFrame(request())).rejects.toThrow("(503)");
  });

  it("does not let a late scrub response replace the newer frame", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((url: string | URL | Request) => {
      if (String(url).endsWith("/1000000")) {
        return new Promise<Response>((resolve) => {
          resolveFirst = resolve;
        });
      }
      return Promise.resolve(
        frameResponse({
          requestedTimeUs: 2_000_000,
          resolvedTimeUs: 2_010_000,
          frameIndex: 51,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = request({ requestedTimeUs: 1_000_000 });
    const { rerender } = render(<FrameProbe value={first} />);
    rerender(<FrameProbe value={request({ requestedTimeUs: 2_000_000 })} />);
    expect(
      await screen.findByText(/ready 2000000\/2010000 51@2010000 true/),
    ).toBeInTheDocument();

    await act(async () => {
      resolveFirst?.(
        frameResponse({
          requestedTimeUs: 1_000_000,
          resolvedTimeUs: 1_005_000,
          frameIndex: 25,
        }),
      );
    });
    await waitFor(() =>
      expect(screen.getByText(/ready 2000000\/2010000/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/ready 1000000/)).not.toBeInTheDocument();
  });
});
