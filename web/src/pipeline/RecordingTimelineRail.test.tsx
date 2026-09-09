import { act, fireEvent, render, screen } from "@testing-library/react";

import type {
  RecordingTimelineRailItem,
  RecordingTimelineRailLane,
} from "./recordingWorkspacePresentation";
import { RecordingTimelineRail } from "./RecordingTimelineRail";

const LANES: RecordingTimelineRailLane[] = [
  { id: "events", label: "Events", itemCount: 2, state: "complete" },
];
const ITEMS: RecordingTimelineRailItem[] = [
  {
    id: "run-1:event-1",
    itemId: "event-1",
    selectionParam: "item",
    laneId: "events",
    label: "card_played",
    state: "pending",
    timeRange: { startUs: 1_000_000, endUs: 2_000_000 },
    runId: "run-1",
  },
  {
    id: "run-1:event-2",
    itemId: "event-2",
    selectionParam: "item",
    laneId: "events",
    label: "trick_cleared",
    state: "accepted",
    timeRange: { startUs: 5_000_000, endUs: 6_000_000 },
    runId: "run-1",
  },
];
let sourceVideo: HTMLVideoElement | null = null;

function renderRail({
  currentTimeUs = 0,
  onTimeChange = vi.fn(),
  onItemSelect = vi.fn(),
}: {
  currentTimeUs?: number;
  onTimeChange?: (timeUs: number) => void;
  onItemSelect?: (item: RecordingTimelineRailItem) => void;
} = {}) {
  render(
    <RecordingTimelineRail
      recordingId="timeline-recording"
      durationUs={10_000_000}
      currentTimeUs={currentTimeUs}
      selectedItemId={null}
      lanes={LANES}
      items={ITEMS}
      onTimeChange={onTimeChange}
      onItemSelect={onItemSelect}
    />,
  );
  return { onTimeChange, onItemSelect };
}

describe("RecordingTimelineRail", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    sourceVideo?.remove();
    sourceVideo = null;
  });

  it("keeps playback controls beside the scrubber without a redundant heading", () => {
    renderRail();

    expect(screen.queryByText("Timeline Rail")).not.toBeInTheDocument();
    expect(screen.queryByText("Recording navigation")).not.toBeInTheDocument();

    const controls = screen.getByRole("group", { name: "Playback controls" });
    const scrubber = controls.parentElement;
    const range = screen.getByRole("slider", { name: "Recording playhead" });

    expect(scrubber).not.toBeNull();
    expect(scrubber?.firstElementChild).toBe(controls);
    expect(scrubber?.lastElementChild).toBe(range.parentElement);
  });

  it("renders ordered accessible lanes and selects an item with its source time", () => {
    const { onTimeChange, onItemSelect } = renderRail();

    expect(
      screen.getByRole("group", { name: "Events lane" }),
    ).toBeInTheDocument();
    const first = screen.getByRole("button", {
      name: "card_played, 0:01–0:02, pending",
    });
    expect(first).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(first);

    expect(onItemSelect).toHaveBeenCalledWith(ITEMS[0]);
    expect(onTimeChange).toHaveBeenCalledWith(1_000_000);
  });

  it("supports keyboard item stepping and pointer-captured scrubbing", () => {
    const { onTimeChange } = renderRail();
    const first = screen.getByRole("button", {
      name: "card_played, 0:01–0:02, pending",
    });
    const second = screen.getByRole("button", {
      name: "trick_cleared, 0:05–0:06, accepted",
    });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(second).toHaveFocus();
    expect(onTimeChange).toHaveBeenCalledWith(5_000_000);

    const range = screen.getByRole("slider", { name: "Recording playhead" });
    const setPointerCapture = vi.fn();
    const hasPointerCapture = vi.fn(() => true);
    const releasePointerCapture = vi.fn();
    Object.defineProperty(range, "setPointerCapture", {
      configurable: true,
      value: setPointerCapture,
    });
    Object.defineProperty(range, "hasPointerCapture", {
      configurable: true,
      value: hasPointerCapture,
    });
    Object.defineProperty(range, "releasePointerCapture", {
      configurable: true,
      value: releasePointerCapture,
    });
    fireEvent.change(range, { target: { value: "3500000" } });
    fireEvent.pointerDown(range, { pointerId: 7 });
    fireEvent.pointerUp(range, { pointerId: 7 });

    expect(setPointerCapture).toHaveBeenCalledWith(7);
    expect(releasePointerCapture).toHaveBeenCalledWith(7);
    expect(onTimeChange).toHaveBeenCalledWith(3_500_000);
  });

  it("floats the preview above the playhead only while the rail is hovered", () => {
    renderRail({ currentTimeUs: 3_000_000 });
    const preview = () =>
      document.querySelector<HTMLElement>("[data-preview-position-us]");
    const rail = document.querySelector<HTMLElement>("[data-zoom]");
    const first = screen.getByRole("button", {
      name: "card_played, 0:01–0:02, pending",
    });

    expect(preview()).not.toBeInTheDocument();

    fireEvent.pointerEnter(rail!);
    expect(preview()).toHaveAttribute("data-preview-position-us", "3000000");

    fireEvent.pointerEnter(first);
    expect(preview()).toHaveAttribute("data-preview-position-us", "1500000");

    const range = screen.getByRole("slider", { name: "Recording playhead" });
    Object.defineProperty(range, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 100, width: 200 }),
    });
    fireEvent.pointerMove(range, { clientX: 250 });
    expect(preview()).toHaveAttribute("data-preview-position-us", "7500000");

    fireEvent.pointerLeave(rail!);
    expect(preview()).not.toBeInTheDocument();
  });

  it("keeps the preview mounted and targets the matching source video for playback", async () => {
    const otherVideo = document.createElement("video");
    otherVideo.dataset.recordingSourceVideo = "other-recording";
    const play = vi.fn(() => Promise.resolve());
    sourceVideo = document.createElement("video");
    sourceVideo.dataset.recordingSourceVideo = "timeline-recording";
    Object.defineProperty(sourceVideo, "paused", {
      configurable: true,
      value: true,
    });
    Object.defineProperty(sourceVideo, "play", {
      configurable: true,
      value: play,
    });
    document.body.append(otherVideo, sourceVideo);

    renderRail();

    fireEvent.pointerEnter(document.querySelector("[data-zoom]")!);
    expect(screen.getByText("Loading exact source frame…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Play recording" }));

    await act(async () => await Promise.resolve());
    expect(play).toHaveBeenCalledOnce();
  });

  it("keeps the playhead synchronized with the accepted source video", () => {
    sourceVideo = document.createElement("video");
    sourceVideo.dataset.recordingSourceVideo = "timeline-recording";
    Object.defineProperty(sourceVideo, "currentTime", {
      configurable: true,
      writable: true,
      value: 0,
    });
    Object.defineProperty(sourceVideo, "paused", {
      configurable: true,
      value: true,
    });
    document.body.append(sourceVideo);
    const { onTimeChange } = renderRail();

    sourceVideo.currentTime = 4.25;
    fireEvent.timeUpdate(sourceVideo);

    expect(onTimeChange).toHaveBeenCalledWith(4_250_000);
  });

  it("cancels stale exact-frame previews and caches the winning response", async () => {
    vi.useFakeTimers();
    const requests: Array<{
      resolve: (response: Response) => void;
      signal: AbortSignal;
    }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((resolve) => {
            requests.push({
              resolve,
              signal: init?.signal as AbortSignal,
            });
          }),
      ),
    );
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn((blob: Blob) => `blob:${blob.size}`),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    renderRail();
    const first = screen.getByRole("button", {
      name: "card_played, 0:01–0:02, pending",
    });
    const second = screen.getByRole("button", {
      name: "trick_cleared, 0:05–0:06, accepted",
    });

    fireEvent.pointerEnter(first);
    act(() => vi.advanceTimersByTime(120));
    fireEvent.pointerEnter(second);
    act(() => vi.advanceTimersByTime(120));
    expect(requests).toHaveLength(2);
    expect(requests[0].signal.aborted).toBe(true);

    await act(async () => {
      requests[0].resolve(new Response(new Blob(["stale"]), { status: 200 }));
      await Promise.resolve();
    });
    expect(screen.queryByRole("img", { name: /0:01/ })).not.toBeInTheDocument();

    await act(async () => {
      requests[1].resolve(new Response(new Blob(["winning"]), { status: 200 }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(
      screen.getByRole("img", { name: "Exact source frame preview at 0:05" }),
    ).toHaveAttribute("src", expect.stringMatching(/^blob:/));
  });
});
