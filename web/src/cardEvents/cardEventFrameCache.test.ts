import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isAbortError,
  loadCachedReviewFrame,
  peekCachedReviewFrame,
  resetReviewFrameCacheForTests,
} from "./cardEventFrameCache";

function frameResponse(status = 200): Response {
  return new Response(Uint8Array.from([1, 2, 3, 4]), {
    status,
    headers: { "Content-Type": "image/jpeg" },
  });
}

describe("cardEventFrameCache", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetReviewFrameCacheForTests();
  });

  it("does not let an aborted waiter poison a later load of the same URL", async () => {
    let release: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const firstController = new AbortController();
    const firstLoad = loadCachedReviewFrame("/frame-a", firstController.signal);
    firstController.abort();
    await expect(firstLoad).rejects.toSatisfy(isAbortError);

    const secondLoad = loadCachedReviewFrame("/frame-a");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    release?.(frameResponse());
    await expect(secondLoad).resolves.toEqual(expect.any(String));
    expect(peekCachedReviewFrame("/frame-a")).not.toBeNull();
  });

  it("keeps the shared fetch running after the UI aborts", async () => {
    let release: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const controller = new AbortController();
    const abortedLoad = loadCachedReviewFrame("/frame-b", controller.signal);
    controller.abort();
    await expect(abortedLoad).rejects.toSatisfy(isAbortError);

    release?.(frameResponse());
    await expect(loadCachedReviewFrame("/frame-b")).resolves.toEqual(
      expect.any(String),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
