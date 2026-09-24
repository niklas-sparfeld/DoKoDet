import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { describeError } from "./PipelineVisibleCardFormatting";

describe("visible-card editor error descriptions", () => {
  it("prefers an API error message and falls back to standard errors", () => {
    expect(
      describeError(
        new ApiError(422, { error: { message: "Invalid polygon." } }),
      ),
    ).toBe("Invalid polygon.");
    expect(describeError(new Error("Network unavailable."))).toBe(
      "Network unavailable.",
    );
    expect(describeError({})).toBe(
      "The visible-card reference could not be saved.",
    );
  });
});
