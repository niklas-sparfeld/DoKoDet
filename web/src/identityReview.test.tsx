import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";

import { IdentityReviewPage } from "./identityReview";
import { RecordingDetailView } from "./recordings";
import { emptyRecordingDetail } from "./test/roundAnalysisFixture";

const batchId = "visual-card-identity-batch-0123456789abcdef01234567";

function identityItem(itemId: string, proposal: object | null) {
  return {
    schema_version: "visual-card-identity-review-item/v1",
    item_id: itemId,
    visible_card_review_item_id: `${itemId}:frame_00`,
    source: {
      visible_card_review_batch_id: "visible-card-batch-fixture",
      visible_card_review_item_id: `${itemId}:frame_00`,
      package_id: itemId,
      frame_part_name: "frame_00",
      image_url: `/v1/visible-card-reviews/visible-card-batch-fixture/items/${itemId}%3Aframe_00/image`,
      frame_sha256: "1".repeat(64),
      source_asset_id: "source-fixture",
      source_lineage_group: "group-fixture",
      source_asset_sha256: "2".repeat(64),
      width: 40,
      height: 30,
    },
    visible_card: {
      card_id: itemId,
      visible_region: {
        polygons: [
          [
            { x: 100, y: 100 },
            { x: 900, y: 100 },
            { x: 900, y: 900 },
            { x: 100, y: 900 },
          ],
        ],
      },
      derived_box: {
        box_2d: { x_min: 100, y_min: 100, x_max: 900, y_max: 900 },
      },
      identity_usability: {
        usable: true,
        reason: "sufficient_identity_evidence",
      },
      side: "face_up",
      failure_tags: [],
    },
    visible_card_digest: "3".repeat(64),
    crop: {
      image_url: `/v1/identity-reviews/${batchId}/items/${itemId}/crop`,
      sha256: "4".repeat(64),
      byte_length: 42,
      content_type: "image/x-portable-pixmap",
      width: 32,
      height: 24,
      policy_id: "raw_rectangular",
      policy_digest: "5".repeat(64),
    },
    proposal,
    decision: {
      schema_version: "visual-card-identity-decision/v1",
      status: "pending",
      identity: null,
      reason: null,
      reviewer: null,
      updated_at_utc: null,
    },
    status: "ready",
    failure: null,
  };
}

function proposal(itemId: string) {
  return {
    schema_version: "visual-card-identity-proposal/v1",
    item_id: itemId,
    crop_sha256: "4".repeat(64),
    classifier: {
      name: "fixture-identity",
      version: "fixture-identity-v1",
      calibration: "uncalibrated",
      bundle_identity: null,
    },
    status: "ok",
    candidates: [
      { card: "CLUBS_NINE", probability: 0.75 },
      { card: "SPADES_NINE", probability: 0.25 },
    ],
    score: 0.75,
    result: { fixture: true },
    result_digest: "6".repeat(64),
  };
}

function batchFixture() {
  return {
    schema_version: "visual-card-identity-review-batch/v1",
    batch_id: batchId,
    recording_id: "recording-fixture",
    request_digest: "7".repeat(64),
    status: "ready",
    created_at_utc: "2026-09-02T10:00:00Z",
    updated_at_utc: "2026-09-02T10:00:00Z",
    classifier: {
      name: "fixture-identity",
      version: "fixture-identity-v1",
      calibration: "uncalibrated",
      bundle_identity: null,
    },
    crop_policy: {
      policy_id: "raw_rectangular",
      policy_digest: "5".repeat(64),
      policy: { policy_id: "raw_rectangular" },
    },
    progress: {
      phase: "ready",
      total_items: 2,
      crops_materialized: 2,
      proposals_completed: 2,
      failed_items: 0,
    },
    items: [
      identityItem("identity-item-1", proposal("identity-item-1")),
      identityItem("identity-item-2", null),
    ],
    coverage: {
      schema_version: "visual-card-identity-review-coverage/v1",
      visible_card_review_item_count: 2,
      reviewed_visible_card_count: 2,
      identity_usable_card_count: 2,
      excluded_card_count: 0,
      excluded_cards: [],
      coverage_digest: "8".repeat(64),
    },
    failures: [],
  };
}

describe("IdentityReviewPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows source context, frozen crop, proposal lineage, and navigation", async () => {
    const batch = batchFixture();
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(batch), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<IdentityReviewPage batchId={batchId} selectedItemId={null} />);

    expect(
      await screen.findByRole("heading", { name: "Visual card identities" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("Source frame frame_00")).toHaveAttribute(
      "src",
      expect.stringContaining("visible-card-batch-fixture"),
    );
    expect(
      screen.getByAltText("Frozen identity crop for identity-item-1"),
    ).toHaveAttribute(
      "src",
      `/v1/identity-reviews/${batchId}/items/identity-item-1/crop`,
    );
    expect(screen.getByText("CLUBS_NINE")).toBeInTheDocument();
    expect(
      screen.getByText("Source, crop, and proposal lineage"),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(
      screen.getByAltText("Frozen identity crop for identity-item-2"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No classifier proposal is available/),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?item=identity-item-2");
  });

  it("shows the identity batch summary in the recording workspace", async () => {
    const batch = batchFixture();
    const readiness = {
      schema_version: "visual-card-identity-review-readiness/v1",
      recording_id: "recording-detail-1",
      state: "ready",
      message: "Ready to review 2 identity-usable cards.",
      blocker: null,
      selected_card_count: 2,
      batch,
      preview_digest: "9".repeat(64),
    };
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path.endsWith("/identity-review")) {
        return Promise.resolve(
          new Response(JSON.stringify(readiness), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/visible-card-review")) {
        return Promise.resolve(
          new Response(JSON.stringify({ schema_version: "other" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(emptyRecordingDetail), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RecordingDetailView
        recordingId="recording-detail-1"
        selectedAnalysisId={null}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Visual card identities" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Ready to review 2 identity-usable cards."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open identity review workspace" }),
    ).toHaveAttribute("href", `/identity-reviews/${batchId}`);
  });
});
