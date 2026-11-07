import { describe, expect, it, vi } from "vitest";

import {
  createRecordingsClient,
  recordingDetailPath,
} from "./recordingsClient";

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}

describe("recordings client", () => {
  it("lists and reads recordings through encoded recording paths", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse({ recordings: [] })),
    );
    const client = createRecordingsClient(fetcher);

    await client.listRecordings();
    await client.getRecording("recording/1");

    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      "/v1/recordings",
      recordingDetailPath("recording/1"),
    ]);
    expect(fetcher.mock.calls[1]?.[1]?.method).toBeUndefined();
  });
});
