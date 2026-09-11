import { renderHook, waitFor } from "@testing-library/react";

import {
  deriveReviewPrewarmBlocks,
  usePipelineReviewPrewarm,
} from "./pipelineReviewPrewarm";

describe("deriveReviewPrewarmBlocks", () => {
  it("selects the first block and the next block at the beginning", () => {
    expect(deriveReviewPrewarmBlocks(12, 0)).toEqual([
      [0, 1, 2, 3],
      [4, 5, 6, 7],
    ]);
  });

  it("prioritizes the selected block, then previous and next in the middle", () => {
    expect(deriveReviewPrewarmBlocks(16, 6)).toEqual([
      [4, 5, 6, 7],
      [0, 1, 2, 3],
      [8, 9, 10, 11],
    ]);
  });

  it("clamps the selected block and previous block at the end", () => {
    expect(deriveReviewPrewarmBlocks(10, 9)).toEqual([
      [8, 9],
      [4, 5, 6, 7],
    ]);
  });

  it("clamps lists shorter than one block", () => {
    expect(deriveReviewPrewarmBlocks(3, 2)).toEqual([[0, 1, 2]]);
  });
});

describe("usePipelineReviewPrewarm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("warms blocks in order with at most four concurrent requests", async () => {
    const activeRequests: string[] = [];
    let maximumConcurrentRequests = 0;
    const resolvers = new Map<string, () => void>();
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      activeRequests.push(url);
      maximumConcurrentRequests = Math.max(
        maximumConcurrentRequests,
        activeRequests.length,
      );
      return new Promise<Response>((resolve) => {
        resolvers.set(url, () => {
          activeRequests.splice(activeRequests.indexOf(url), 1);
          resolve(new Response("warm"));
        });
      });
    });
    vi.stubGlobal("fetch", fetchImplementation);

    const items = Array.from({ length: 10 }, (_, index) => index);
    renderHook(() =>
      usePipelineReviewPrewarm(items, 5, (item) => [`/frame/${item}`]),
    );

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(4));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual(["/frame/4", "/frame/5", "/frame/6", "/frame/7"]);
    expect(maximumConcurrentRequests).toBe(4);

    for (const resolve of resolvers.values()) resolve();
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(8));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual([
      "/frame/4",
      "/frame/5",
      "/frame/6",
      "/frame/7",
      "/frame/0",
      "/frame/1",
      "/frame/2",
      "/frame/3",
    ]);
  });

  it("aborts stale work and does not surface warm failures", async () => {
    const signals: AbortSignal[] = [];
    const fetchImplementation = vi.fn<typeof fetch>((_input, init) => {
      const signal = init?.signal;
      if (signal !== undefined && signal !== null) signals.push(signal);
      return Promise.reject(new Error("warm failed"));
    });
    vi.stubGlobal("fetch", fetchImplementation);

    const { rerender, unmount } = renderHook(
      ({ selectedIndex }) =>
        usePipelineReviewPrewarm(
          ["a", "b", "c", "d", "e"],
          selectedIndex,
          (item) => [`/frame/${item}`],
        ),
      { initialProps: { selectedIndex: 0 } },
    );

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalled());
    rerender({ selectedIndex: 4 });
    await waitFor(() => expect(signals[0]).toBeDefined());
    expect(signals[0]?.aborted).toBe(true);
    unmount();
    expect(signals.at(-1)?.aborted).toBe(true);
  });

  it("does not request URLs that were already warmed in the mounted session", async () => {
    const fetchImplementation = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("warm")),
    );
    vi.stubGlobal("fetch", fetchImplementation);
    const items = Array.from({ length: 8 }, (_, index) => index);
    const getUrls = (item: number) => [`/frame/${item}`];

    const { rerender } = renderHook(
      ({ selectedIndex }) =>
        usePipelineReviewPrewarm(items, selectedIndex, getUrls),
      { initialProps: { selectedIndex: 0 } },
    );

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(8));
    rerender({ selectedIndex: 1 });
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(8));
  });
});
