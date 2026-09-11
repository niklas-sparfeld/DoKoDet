import { renderHook, waitFor } from "@testing-library/react";

import {
  deriveReviewPrewarmBlocks,
  usePipelineReviewPrewarm,
} from "./pipelineReviewPrewarm";

describe("deriveReviewPrewarmBlocks", () => {
  it("starts with the next item instead of the selected block", () => {
    expect(deriveReviewPrewarmBlocks(12, 5)).toEqual([
      [6, 7, 8, 9],
      [10, 11, 4, 3],
      [2, 1, 0],
    ]);
  });

  it("uses previous items when there are no later neighbors", () => {
    expect(deriveReviewPrewarmBlocks(10, 9)).toEqual([
      [8, 7, 6, 5],
      [4, 3, 2, 1],
      [0],
    ]);
  });

  it("clamps lists shorter than one block", () => {
    expect(deriveReviewPrewarmBlocks(3, 2)).toEqual([[1, 0]]);
  });
});

describe("usePipelineReviewPrewarm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("skips selected URLs and warms next neighbors with bounded concurrency", async () => {
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

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(2));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual(["/frame/6", "/frame/7"]);
    expect(maximumConcurrentRequests).toBe(2);

    for (const resolve of resolvers.values()) resolve();
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(4));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual(["/frame/6", "/frame/7", "/frame/8", "/frame/9"]);
    for (const resolve of resolvers.values()) resolve();
  });

  it("keeps active URLs deduplicated across rapid selection changes", async () => {
    const resolvers = new Map<string, () => void>();
    const fetchImplementation = vi.fn<typeof fetch>((input) => {
      const url = String(input);
      return new Promise<Response>((resolve) => {
        resolvers.set(url, () => resolve(new Response("warm")));
      });
    });
    vi.stubGlobal("fetch", fetchImplementation);
    const items = Array.from({ length: 8 }, (_, index) => index);
    const getUrls = (item: number) => [`/frame/${item}`];

    const { rerender } = renderHook(
      ({ selectedIndex }) =>
        usePipelineReviewPrewarm(items, selectedIndex, getUrls),
      { initialProps: { selectedIndex: 0 } },
    );

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(2));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual(["/frame/1", "/frame/2"]);

    rerender({ selectedIndex: 1 });
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(2));
    expect(
      fetchImplementation.mock.calls.filter(
        ([input]) => String(input) === "/frame/2",
      ),
    ).toHaveLength(1);

    for (const resolve of resolvers.values()) resolve();
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(4));
    expect(
      fetchImplementation.mock.calls.map(([input]) => String(input)),
    ).toEqual(["/frame/1", "/frame/2", "/frame/3", "/frame/4"]);
    for (const resolve of resolvers.values()) resolve();
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

    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(4));
    rerender({ selectedIndex: 1 });
    await waitFor(() => expect(fetchImplementation).toHaveBeenCalledTimes(5));
    expect(
      fetchImplementation.mock.calls.filter(
        ([input]) => String(input) === "/frame/1",
      ),
    ).toHaveLength(1);
  });
});
