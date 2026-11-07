import { describe, expect, it, vi } from "vitest";

import {
  createCalibrationClient,
  pipelineCalibrationRefinementApplyPath,
  pipelineCalibrationRefinementReadPath,
} from "./calibrationClient";

describe("calibration client", () => {
  it("encodes refinement query values and sends update bodies", async () => {
    const fetcher = vi.fn<typeof fetch>(() =>
      Promise.resolve(new Response("{}")),
    );
    const client = createCalibrationClient(fetcher);
    const payload = {
      draft_id: "draft/1",
      expected_revision: 3,
      command: { type: "move" },
    };

    await client.updateCalibrationRefinement(
      "recording/1",
      "proposal/2",
      payload,
    );

    expect(
      pipelineCalibrationRefinementReadPath(
        "recording/1",
        "proposal/2",
        "draft 1",
      ),
    ).toBe(
      "/api/recordings/recording%2F1/pipeline/calibration-refinement?proposal_revision_id=proposal%2F2&draft_id=draft+1",
    );
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      pipelineCalibrationRefinementReadPath("recording/1", "proposal/2"),
    );
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify(payload),
      headers: expect.any(Headers),
    });
    expect(
      pipelineCalibrationRefinementApplyPath("recording/1", "proposal/2"),
    ).toBe(
      "/api/recordings/recording%2F1/pipeline/calibration-refinement/apply?proposal_revision_id=proposal%2F2",
    );
  });
});
