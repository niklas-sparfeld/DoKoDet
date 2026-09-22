import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  pipelineDerivedFramePath,
  repositoryBundleVideoPath,
} from "../api/client";
import { CardEventFrameSurface } from "./CardEventFrameSurface";
import {
  loadCachedReviewFrame,
  resetReviewFrameCacheForTests,
} from "./cardEventFrameCache";
import { resetRecordingVideoCacheForTests } from "./recordingVideoCache";

const recordingId = "recording-frame-surface";

function frameResponse(status = 200): Response {
  return new Response(Uint8Array.from([1, 2, 3, 4]), {
    status,
    headers: { "Content-Type": "image/jpeg" },
  });
}

function videoResponse(): Response {
  return new Response(Uint8Array.from([0, 1, 2, 3]), {
    status: 200,
    headers: {
      "Content-Type": "video/mp4",
      "Content-Length": "4",
    },
  });
}

function stubReviewFetch(
  handler: (url: string) => Promise<Response> | Response,
): ReturnType<typeof vi.fn<typeof fetch>> {
  const fetchMock = vi.fn<typeof fetch>((input) => {
    const url = String(input);
    if (url === repositoryBundleVideoPath(recordingId)) {
      return Promise.resolve(videoResponse());
    }
    return Promise.resolve(handler(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function derivedFetchCount(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>): number {
  return fetchMock.mock.calls.filter(([input]) =>
    String(input).includes("/derived-views/exact-event/"),
  ).length;
}

describe("CardEventFrameSurface", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetReviewFrameCacheForTests();
    resetRecordingVideoCacheForTests();
  });

  it("loads a cached exact review frame for the requested time", async () => {
    const fetchMock = stubReviewFetch(() => frameResponse());

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
    );
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-frame-settled", "true"),
    );
    expect(
      screen.getByLabelText("CardEvent review source frame").querySelector("video"),
    ).not.toBeNull();
  });

  it("shows a loading overlay until the derived frame is ready", async () => {
    let release: ((value: Response) => void) | undefined;
    stubReviewFetch(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

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
    const fetchMock = stubReviewFetch(() => frameResponse());
    await loadCachedReviewFrame(url);
    expect(derivedFetchCount(fetchMock)).toBe(1);

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
    expect(derivedFetchCount(fetchMock)).toBe(1);
    expect(
      screen.getByRole("region", { name: "CardEvent review source frame" }),
    ).toHaveAttribute("data-frame-settled", "true");
  });

  it("keeps the video element mounted when switching to video playback", async () => {
    stubReviewFetch(() => frameResponse());

    const { rerender } = render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_000_000}
        playback="derived"
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "CardEvent review frame at 0:01.000000",
      }),
    ).toBeInTheDocument();
    const video = screen
      .getByLabelText("CardEvent review source frame")
      .querySelector("video");
    expect(video).not.toBeNull();

    rerender(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_033_333}
        playback="video"
      />,
    );

    expect(
      screen.getByLabelText("CardEvent review source frame").querySelector("video"),
    ).toBe(video);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("does not show an abort error when the requested time changes mid-fetch", async () => {
    const resolvers = new Map<string, (value: Response) => void>();
    stubReviewFetch((url) => {
      return new Promise<Response>((resolve) => {
        resolvers.set(url, resolve);
      });
    });

    const { rerender } = render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_000_000}
        playback="derived"
      />,
    );

    expect(await screen.findByText("Updating frame…")).toBeInTheDocument();

    rerender(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={2_000_000}
        playback="derived"
      />,
    );

    const secondUrl = pipelineDerivedFramePath(recordingId, 2_000_000);
    await waitFor(() => expect(resolvers.has(secondUrl)).toBe(true));

    await act(async () => {
      resolvers.get(secondUrl)?.(frameResponse());
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent review source frame" }),
      ).toHaveAttribute("data-frame-settled", "true"),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/aborted/i)).not.toBeInTheDocument();
  });
});
