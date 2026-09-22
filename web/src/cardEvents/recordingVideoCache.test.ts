import { afterEach, describe, expect, it, vi } from "vitest";

import { repositoryBundleVideoPath } from "../api/client";
import {
  loadRecordingVideoUrl,
  MAX_RECORDING_VIDEO_BLOB_BYTES,
  peekRecordingVideoUrl,
  resetRecordingVideoCacheForTests,
} from "./recordingVideoCache";

describe("recordingVideoCache", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetRecordingVideoCacheForTests();
  });

  it("buffers a modest recording video into a blob object URL", async () => {
    const body = new Uint8Array([1, 2, 3, 4, 5]);
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(body, {
          status: 200,
          headers: {
            "Content-Type": "video/mp4",
            "Content-Length": String(body.byteLength),
          },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const url = await loadRecordingVideoUrl("recording-video-cache");
    expect(url.startsWith("blob:")).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(await loadRecordingVideoUrl("recording-video-cache")).toBe(url);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("buffers a ~557MB-class recording into a blob object URL", async () => {
    const size = 557 * 1024 * 1024;
    const cancel = vi.fn(async () => undefined);
    // Avoid allocating 557MB in the test process: only Content-Length matters
    // for the size gate before the body is read.
    const fetchMock = vi.fn<typeof fetch>(async () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array([1, 2, 3, 4]));
          controller.close();
        },
        cancel,
      });
      return new Response(stream, {
        status: 200,
        headers: {
          "Content-Type": "video/mp4",
          "Content-Length": String(size),
        },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const url = await loadRecordingVideoUrl("recording-557mb");
    expect(url.startsWith("blob:")).toBe(true);
    expect(peekRecordingVideoUrl("recording-557mb")).toBe(url);
  });

  it("falls back to the network URL when the video is too large", async () => {
    const networkUrl = repositoryBundleVideoPath("recording-huge");
    const cancel = vi.fn(async () => undefined);
    const fetchMock = vi.fn<typeof fetch>(async () => {
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array([1]));
          controller.close();
        },
        cancel,
      });
      return new Response(stream, {
        status: 200,
        headers: {
          "Content-Type": "video/mp4",
          "Content-Length": String(MAX_RECORDING_VIDEO_BLOB_BYTES + 1),
        },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadRecordingVideoUrl("recording-huge")).resolves.toBe(
      networkUrl,
    );
    expect(cancel).toHaveBeenCalled();
  });
});
