import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pipelineDerivedFramePath } from "../api/client";
import { CardEventFrameSurface } from "./CardEventFrameSurface";

const recordingId = "recording-frame-surface";

function frameResponse(status = 200): Response {
  return new Response(new Blob(["frame"], { type: "image/jpeg" }), {
    status,
    headers: { "Content-Type": "image/jpeg" },
  });
}

function requestedTime(input: RequestInfo | URL): number {
  const value = String(input).split("/").pop();
  return Number(value);
}

describe("CardEventFrameSurface", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads the recording-owned exact source frame for the requested time", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(frameResponse()),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_250_001}
      />,
    );

    expect(
      await screen.findByRole("img", {
        name: "Exact CardEvent source frame at 0:01.250001",
      }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      pipelineDerivedFramePath(recordingId, 1_250_001),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      screen.getByRole("region", { name: "CardEvent exact source frame" }),
    ).toHaveAttribute("data-frame-status", "ready");
  });

  it("ignores an earlier response after the requested time changes", async () => {
    const pending = new Map<number, (value: Response) => void>();
    const fetchMock = vi.fn<typeof fetch>(
      (input) =>
        new Promise<Response>((resolve) => {
          pending.set(requestedTime(input), resolve);
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const rendered = render(
      <CardEventFrameSurface recordingId={recordingId} requestedTimeUs={0} />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rendered.rerender(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={2_000_000}
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    pending.get(2_000_000)?.(frameResponse());
    expect(
      await screen.findByRole("img", {
        name: "Exact CardEvent source frame at 0:02.000000",
      }),
    ).toBeInTheDocument();

    pending.get(0)?.(frameResponse());
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "CardEvent exact source frame" }),
      ).toHaveAttribute("data-requested-time-us", "2000000"),
    );
    expect(
      screen.getByRole("img", {
        name: "Exact CardEvent source frame at 0:02.000000",
      }),
    ).toBeInTheDocument();
  });

  it("retains the last frame while an unavailable replacement is requested", async () => {
    let requestCount = 0;
    const replacement = {
      resolve: null as ((value: Response) => void) | null,
    };
    const fetchMock = vi.fn<typeof fetch>(() => {
      requestCount += 1;
      if (requestCount === 2) {
        return new Promise<Response>((resolve) => {
          replacement.resolve = resolve;
        });
      }
      return Promise.resolve(frameResponse(requestCount === 1 ? 200 : 404));
    });
    vi.stubGlobal("fetch", fetchMock);

    const rendered = render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={1_000_000}
      />,
    );
    const firstFrame = await screen.findByRole("img", {
      name: "Exact CardEvent source frame at 0:01.000000",
    });
    const firstSource = firstFrame.getAttribute("src");

    rendered.rerender(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={2_000_000}
      />,
    );
    expect(
      await screen.findByText("Loading exact source frame at 0:02.000000…"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Exact CardEvent source frame at 0:01.000000",
      }),
    ).toHaveAttribute("src", firstSource);

    replacement.resolve?.(frameResponse(404));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Exact source frame unavailable (404).",
    );
    expect(
      screen.getByRole("region", { name: "CardEvent exact source frame" }),
    ).toHaveAttribute("data-requested-time-us", "2000000");
    expect(
      screen.getByRole("img", {
        name: "Exact CardEvent source frame at 0:01.000000",
      }),
    ).toHaveAttribute("src", firstSource);
  });

  it("reports a request failure without changing the requested time", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.reject(new Error("frame service offline")),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <CardEventFrameSurface
        recordingId={recordingId}
        requestedTimeUs={3_000_000}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "frame service offline",
    );
    expect(
      screen.getByRole("region", { name: "CardEvent exact source frame" }),
    ).toHaveAttribute("data-frame-status", "failed");
    expect(
      screen.getByRole("region", { name: "CardEvent exact source frame" }),
    ).toHaveAttribute("data-requested-time-us", "3000000");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
