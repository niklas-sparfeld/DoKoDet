import { describe, expect, it } from "vitest";
import {
  comparisonFixture,
  emptyAndFailedFixtures,
  historicalReadOnlyFixture,
  intervalOnlyEvidenceFixture,
  missingCalibrationFixture,
  untimedInferredActionFixture,
  workingAreaStepFixtures,
} from "./workingAreaFixtures";

describe("working-area capability fixtures", () => {
  it("covers all six processing steps and comparison", () => {
    expect(workingAreaStepFixtures.map((fixture) => fixture.step)).toEqual([
      "events",
      "visible_cards",
      "virtual_scenes",
      "visual_identities",
      "table_observations",
      "round_analyses",
    ]);
    expect(comparisonFixture).toMatchObject({
      leftRunId: expect.any(String),
      rightRunId: expect.any(String),
      referenceRevisionId: expect.any(String),
    });
  });

  it("keeps empty, failed, historical, and missing-calibration states explicit", () => {
    expect(emptyAndFailedFixtures.map((fixture) => fixture.state)).toEqual([
      "empty",
      "failed",
    ]);
    expect(historicalReadOnlyFixture.expectedEditable).toBe(false);
    expect(missingCalibrationFixture.evidence).toMatchObject({
      requiresCalibration: true,
      calibration: null,
      expectedOverlayVisible: false,
      expectedEditingEnabled: false,
    });
  });

  it("does not invent a seek target for interval-only or untimed evidence", () => {
    expect(intervalOnlyEvidenceFixture.evidence).toMatchObject({
      sourceFrameId: null,
      expectedSeek: false,
    });
    expect(untimedInferredActionFixture.evidence).toMatchObject({
      requestedTimeUs: null,
      resolvedFrameId: null,
      expectedRailRow: true,
      expectedSeek: false,
    });
  });
});
