import { describe, expect, it } from "vitest";

import {
  PIPELINE_STAGE_KEYS,
  isPipelineStageKey,
  readPipelineUrlState,
  readRecordingPipelineRoute,
  recordingPipelineComparePath,
  recordingPipelineNavigationPath,
  recordingPipelinePath,
} from "./recordingPipelineUrl";

describe("recording pipeline URL helpers", () => {
  it("recognizes every pipeline stage key", () => {
    expect(PIPELINE_STAGE_KEYS).toEqual([
      "events",
      "visible_cards",
      "visual_identities",
      "table_observations",
      "round_analyses",
    ]);
    expect(PIPELINE_STAGE_KEYS.every(isPipelineStageKey)).toBe(true);
    expect(isPipelineStageKey("not-a-stage")).toBe(false);
  });

  it.each([
    [
      "/recordings/recording%2Fone",
      { recordingId: "recording/one", stage: null, compare: false },
    ],
    [
      "/recordings/recording-1/pipeline/events/",
      { recordingId: "recording-1", stage: "events", compare: false },
    ],
    [
      "/recordings/recording-1/pipeline/round_analyses/compare",
      { recordingId: "recording-1", stage: "round_analyses", compare: true },
    ],
  ])("reads a valid route: %s", (pathname, expected) => {
    expect(readRecordingPipelineRoute(pathname)).toEqual(expected);
  });

  it.each([
    "/",
    "/recordings",
    "/recordings/%E0%A4%A",
    "/recordings/recording/pipeline/events/other",
  ])("rejects an invalid route: %s", (pathname) => {
    expect(readRecordingPipelineRoute(pathname)).toBeNull();
  });

  it("keeps a recognized recording while rejecting an unknown stage", () => {
    expect(
      readRecordingPipelineRoute("/recordings/recording-1/pipeline/unknown"),
    ).toEqual({ recordingId: "recording-1", stage: null, compare: false });
  });

  it("reads encoded selection and analysis state", () => {
    expect(
      readPipelineUrlState(
        "?view=reviewed&review=visible-card-review-1&revision=revision%2F1&item=event%2F1&t_us=-17&left=run%2F1&right=run%2F2&reference=ref%2F1&analysis=analysis-1",
      ),
    ).toEqual({
      view: "reviewed",
      startReview: null,
      review: "visible-card-review-1",
      revision: "revision/1",
      lineage: null,
      item: "event/1",
      tUs: -17,
      left: "run/1",
      right: "run/2",
      reference: "ref/1",
      analysis: "analysis-1",
      frameReviewQueue: null,
    });
  });

  it("drops empty and invalid query values", () => {
    expect(
      readPipelineUrlState(
        "?view=invalid&revision=&item=&t_us=3.5&left=&right=&reference=&analysis=",
      ),
    ).toEqual({
      view: null,
      startReview: null,
      review: null,
      revision: null,
      lineage: null,
      item: null,
      tUs: null,
      left: null,
      right: null,
      reference: null,
      analysis: null,
      frameReviewQueue: null,
    });
  });

  it("preserves a direct proposal-review request through route construction", () => {
    const state = readPipelineUrlState(
      "?view=generated&start_review=proposal&revision=detector-1&item=frame-1",
    );

    expect(state.startReview).toBe("proposal");
    expect(recordingPipelinePath("recording-1", "visible_cards", state)).toBe(
      "/recordings/recording-1/pipeline/visible_cards?view=generated&start_review=proposal&revision=detector-1&item=frame-1",
    );
  });

  it("keeps frame review return state without starting a proposal review", () => {
    const state = readPipelineUrlState(
      "?view=generated&revision=detector-1&item=frame-1&frame_review=0096-M4",
    );

    expect(recordingPipelinePath("recording-1", "visible_cards", state)).toBe(
      "/recordings/recording-1/pipeline/visible_cards?view=generated&revision=detector-1&item=frame-1&frame_review=0096-M4",
    );
    expect(state.startReview).toBeNull();
  });

  it("constructs task paths with selection and analysis state", () => {
    expect(
      recordingPipelinePath("recording/one", "round_analyses", {
        view: "generated",
        revision: "revision/1",
        item: "item/1",
        tUs: 42,
        left: "ignored-left",
        right: "ignored-right",
        reference: "ignored-reference",
        analysis: "analysis-1",
      }),
    ).toBe(
      "/recordings/recording%2Fone/pipeline/round_analyses?view=generated&revision=revision%2F1&item=item%2F1&t_us=42&analysis=analysis-1",
    );
  });

  it("preserves an exact lineage choice when the stage changes", () => {
    const state = readPipelineUrlState(
      "?lineage=%7B%22events%22%3A%7B%22node_id%22%3A%22n1%22%2C%22revision_id%22%3A%22r4%22%7D%7D",
    );

    expect(recordingPipelinePath("recording-1", "visible_cards", state)).toBe(
      "/recordings/recording-1/pipeline/visible_cards?lineage=%7B%22events%22%3A%7B%22node_id%22%3A%22n1%22%2C%22revision_id%22%3A%22r4%22%7D%7D",
    );
    expect(
      readPipelineUrlState(
        new URL(
          recordingPipelinePath("recording-1", "visible_cards", state),
          "http://localhost",
        ).search,
      ).lineage,
    ).toBe(state.lineage);
  });

  it("keeps virtual scenes as a distinct step and preserves lineage", () => {
    const path = recordingPipelineNavigationPath(
      "recording-1",
      "virtual_scenes",
      {
        lineage: "selection-json",
      },
    );
    expect(path).toBe(
      "/recordings/recording-1/pipeline/virtual_scenes?lineage=selection-json",
    );
    expect(
      readRecordingPipelineRoute(new URL(path, "http://localhost").pathname),
    ).toMatchObject({
      stage: "virtual_scenes",
      compare: false,
    });
  });

  it("constructs comparison paths with run and reference selection", () => {
    expect(
      recordingPipelineComparePath("recording/one", "events", {
        view: "reviewed",
        revision: "revision/1",
        item: "item/1",
        tUs: 42,
        left: "run/1",
        right: "run/2",
        reference: "reference/1",
        analysis: "ignored-analysis",
      }),
    ).toBe(
      "/recordings/recording%2Fone/pipeline/events/compare?view=reviewed&revision=revision%2F1&item=item%2F1&t_us=42&left=run%2F1&right=run%2F2&reference=reference%2F1",
    );
  });
});
