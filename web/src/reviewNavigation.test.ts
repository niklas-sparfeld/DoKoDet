import { describe, expect, it } from "vitest";

import { findAdjacentUnfinishedItem } from "./reviewNavigation";

const items = [
  { itemId: "first", reviewState: "accepted" },
  { itemId: "second", reviewState: "pending" },
  { itemId: "third", reviewState: "affected" },
  { itemId: "fourth", reviewState: "rejected" },
];

describe("findAdjacentUnfinishedItem", () => {
  const needsReview = (item: (typeof items)[number]) =>
    item.reviewState === "pending" || item.reviewState === "affected";

  it("finds the nearest unfinished item in either direction", () => {
    expect(
      findAdjacentUnfinishedItem(items, "first", 1, needsReview)?.itemId,
    ).toBe("second");
    expect(
      findAdjacentUnfinishedItem(items, "fourth", -1, needsReview)?.itemId,
    ).toBe("third");
  });

  it("starts at the requested end when there is no selection", () => {
    expect(
      findAdjacentUnfinishedItem(items, null, 1, needsReview)?.itemId,
    ).toBe("second");
    expect(
      findAdjacentUnfinishedItem(items, null, -1, needsReview)?.itemId,
    ).toBe("third");
  });

  it("does not wrap at either boundary", () => {
    expect(
      findAdjacentUnfinishedItem(items, "third", 1, needsReview),
    ).toBeUndefined();
    expect(
      findAdjacentUnfinishedItem(items, "second", -1, needsReview),
    ).toBeUndefined();
  });
});
