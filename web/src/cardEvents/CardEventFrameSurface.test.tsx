import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pipelineDerivedFramePath } from "../api/client";
import { CardEventFrameSurface } from "./CardEventFrameSurface";
import { loadCachedReviewFrame } from "./cardEventFrameCache";

const recordingId = "recording-frame-surface";

function frameResponse(status = 200): Response {
  return new Response(Uint8Array.from([1, 2, 3, 4]), {
    status,
    headers: { "Content-Type": "image/jpeg" },
  });
}

describe("CardEventFrameSurface", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads a cached exact review frame for the requested time", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(frameResponse()),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_250_001}
        playback="derived"
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "CardEvent review frame at 0:01.250001",
      }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      pipelineDerivedFramePath(recordingId, 1_250_001),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-frame-settled", "true"),
    );
  });

  it("shows a loading overlay until the derived frame is ready", async () => {
    let release: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_000_000}
        playback="derived"
      />,
    );

    expect(await screen.findByText("Updating frame…")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "CardEvent review source frame" }),
    ).toHaveAttribute("data-frame-settled", "false");

    await act(async () => {
      release?.(frameResponse());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-frame-settled", "true"),
    );
    expect(screen.queryByText("Updating frame…")).not.toBeInTheDocument();
  });

  it("reuses an in-memory cached frame without refetching", async () => {
    const url = pipelineDerivedFramePath(recordingId, 3_000_000);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(frameResponse()),
    );
    vi.stubGlobal("fetch", fetchMock);
    await loadCachedReviewFrame(url);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={3_000_000}
        playback="derived"
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "CardEvent review frame at 0:03.000000",
      }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("region", { name: "CardEvent review source frame" }),
    ).toHaveAttribute("data-frame-settled", "true");
  });
});
