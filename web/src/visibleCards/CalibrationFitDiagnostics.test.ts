import { describe, expect, it } from "vitest";

import type { PipelineProposalRunResponse } from "../api/client";
import { readCalibrationFitDiagnostics } from "./CalibrationFitDiagnostics";

describe("readCalibrationFitDiagnostics", () => {
  it("keeps published calibration warnings visible in proposal review", () => {
    const run = {
      status: "succeeded",
      state: {
        metrics: {
          calibration_run: {
            status: "published",
            calibration_fit_candidate: {
              candidate_digest: "fit-1",
              fit_observation_ids: ["card-1"],
              held_out_observation_ids: ["card-2"],
            },
            diagnostics: {
              failed_gates: [],
              advisory_checks: {
                spatial_coverage: false,
                held_out_boundary: false,
              },
              candidate_evidence: [
                {
                  candidate_id: "card-1",
                  source_frame_id: "frame-1",
                  projected_full_card_outline: [
                    [0, 0],
                    [10, 0],
                    [12, 2],
                    [10, 10],
                    [0, 10],
                  ],
                },
              ],
            },
          },
        },
      },
    } as unknown as PipelineProposalRunResponse;

    const diagnostics = readCalibrationFitDiagnostics(run);

    expect(diagnostics?.published).toBe(true);
    expect(diagnostics?.failedGates).toEqual([]);
    expect(diagnostics?.advisoryWarnings).toEqual([
      "spatial_coverage",
      "held_out_boundary",
    ]);
    expect(diagnostics?.evidence[0].status).toBe("fit");
    expect(diagnostics?.evidence[0].points).toHaveLength(5);
  });
});
