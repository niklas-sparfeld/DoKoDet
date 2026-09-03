import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, within } from "@testing-library/react";

import type { VisibleCardReviewBatch } from "./api/client";
import {
  insertPointIntoPolygon,
  VisibleCardReviewPage,
} from "./visibleCardReview";

describe("VisibleCardReviewPage failed finder output", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the source, recovered proposal, and raw response for a malformed result", async () => {
    const batchId = "visible-card-batch-0123456789abcdef01234567";
    const itemId = "recording-vc-0000-item-one:frame_00";
    const rawResponse = {
      candidates: [
        {
          content: {
            parts: [{ text: '{"cards":[{"box_2d":{"x_min":101}}]}' }],
          },
        },
      ],
    };
    const batch = {
      schema_version: "visible-card-review-batch/v1",
      batch_id: batchId,
      recording_id: "recording-detail-1",
      request_digest: "a".repeat(64),
      status: "failed",
      created_at_utc: "2026-09-01T07:20:46Z",
      updated_at_utc: "2026-09-01T07:20:46Z",
      detector: {
        bundle_id: "fixture-visible-card-detector",
        bundle_digest: "b".repeat(64),
        model: "gemini-3.6-flash",
        provider: "gemini",
        provider_version: "gemini-visible-cards-v1",
        preprocessing: "gemini-native-image-v1",
        confidence_threshold: 0,
        input_size: 1,
      },
      progress: {
        phase: "failed",
        total_items: 1,
        frames_extracted: 1,
        finder_completed: 0,
        failed_items: 1,
      },
      items: [
        {
          item_id: itemId,
          status: "failed",
          event_id: "cardevent-event-1",
          event_index: 0,
          event_time_s: 0.4,
          event_time_ms: 400,
          target_offset_ms: 0,
          frame_index: 4,
          actual_offset_ms: 0,
          finder_status: "unavailable",
          failure: {
            code: "provider_error",
            message:
              "Gemini returned a malformed response: card 0 box_2d must be the tight bounds of its visible polygon.",
            stage: "finder",
            item_id: itemId,
            retryable: true,
          },
          source: {
            package_id: "recording-vc-0000-item-one",
            frame_part_name: "frame_00",
            target_offset_ms: 0,
            image_url: `/v1/visible-card-reviews/${batchId}/items/${encodeURIComponent(itemId)}/image`,
            frame_sha256: "c".repeat(64),
            source_asset_id: "source-detail-1",
            source_lineage_group: "session-detail-1",
            source_asset_sha256: "d".repeat(64),
            width: 100,
            height: 80,
          },
          finder: {
            provider: "gemini",
            provider_version: "gemini-visible-cards-v1",
            request_digest: "e".repeat(64),
            result_digest: "f".repeat(64),
            prediction_sha256: "1".repeat(64),
            proposals_recovered: true,
            raw_response: rawResponse,
            proposals: [
              {
                proposal_index: 0,
                box_2d: { y_min: 100, x_min: 100, y_max: 800, x_max: 800 },
                polygon: [
                  { x: 100, y: 100 },
                  { x: 800, y: 100 },
                  { x: 800, y: 800 },
                  { x: 100, y: 800 },
                ],
                side: "unknown",
                label: "visible card",
              },
            ],
          },
          review: null,
        },
      ],
      failures: [],
      queue_schema_version: "visible-card-review-queue/v2",
      queue_digest: null,
      revision: 0,
      summary: {
        total_frames: 1,
        reviewed_frames: 0,
        pending_frames: 0,
        failed_frames: 1,
        usable_frames: 0,
        empty_frames: 0,
        unusable_frames: 0,
        retained_cards: 0,
        accepted_proposals: 0,
        corrected_proposals: 0,
        removed_proposals: 0,
        added_cards: 0,
        identity_unusable_cards: 0,
      },
      review_state: "draft",
      reviewer: null,
      completed_at_utc: null,
      completed_version_id: null,
      completed_version_digest: null,
      completion_receipt_id: null,
      completion_receipt_digest: null,
      parent_version_id: null,
      parent_digest: null,
      downstream_readiness: {
        state: "not_ready",
        message: "Retry the failed finder item before review.",
        queue_digest: null,
      },
    } as unknown as VisibleCardReviewBatch;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(batch), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(<VisibleCardReviewPage batchId={batchId} selectedItemId={itemId} />);

    expect(
      await screen.findByAltText("Exact event source frame at 0.400 s"),
    ).toHaveAttribute("src", batch.items[0].source?.image_url);
    expect(
      screen.getByText(/box_2d must be the tight bounds/),
    ).toBeInTheDocument();
    expect(screen.getByText("Proposal 1")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "1 finder proposal" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Finder diagnostics")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText("Finder diagnostics"));
    expect(
      screen.getByText(/Candidate JSON captured from the finder/),
    ).toBeInTheDocument();
    expect(document.body.textContent).toContain('"x_min": 101');
    expect(
      screen.getByText(/These proposals are display-only/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Accept proposal 1" }),
    ).toBeDisabled();

    const showRawResult = screen.getByRole("button", {
      name: "Show raw result",
    });
    await user.click(showRawResult);
    const rawDialog = screen.getByRole("dialog", {
      name: "Gemini raw result",
    });
    expect(rawDialog).toHaveTextContent(/"candidates"/);
    expect(rawDialog).toHaveTextContent(/\\"x_min\\":101/);
    await user.click(
      within(rawDialog).getByRole("button", { name: "Close raw result" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(showRawResult);
  });
});

describe("visible-card polygon editor", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("inserts a point into the closest polygon edge", () => {
    const polygon = [
      { x: 100, y: 100 },
      { x: 900, y: 100 },
      { x: 900, y: 900 },
      { x: 100, y: 900 },
    ];

    expect(insertPointIntoPolygon(polygon, { x: 900, y: 500 })).toEqual([
      polygon[0],
      polygon[1],
      { x: 900, y: 500 },
      polygon[2],
      polygon[3],
    ]);
  });

  it("selects, drags, and deletes an existing point", async () => {
    const batchId = "visible-card-batch-editor-0123456789";
    const itemId = "editor-item";
    const batch = makeEditorBatch(batchId, itemId);
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(batch), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );

    render(<VisibleCardReviewPage batchId={batchId} selectedItemId={itemId} />);

    await screen.findByAltText("Exact event source frame at 0.400 s");
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Correct proposal 1" }));
    const canvas = screen.getByRole("img", { name: "1 finder proposal" });
    vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    const user = userEvent.setup();
    const point = screen.getByRole("button", {
      name: "Polygon 1, point 1 at 100, 100",
    });
    await user.click(point);
    expect(
      screen.getAllByRole("button", { name: /Polygon 1, point/ }),
    ).toHaveLength(4);
    fireEvent.pointerDown(point, {
      clientX: 10,
      clientY: 10,
      pointerId: 7,
    });
    fireEvent.pointerMove(canvas, {
      clientX: 20,
      clientY: 25,
      pointerId: 7,
    });
    fireEvent.pointerUp(canvas, { pointerId: 7 });

    expect(
      screen.getByRole("button", {
        name: "Polygon 1, point 1 at 200, 250",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove selected point" }),
    );
    expect(
      screen.getAllByRole("button", { name: /Polygon 1, point/ }),
    ).toHaveLength(3);
  });
});

function makeEditorBatch(
  batchId: string,
  itemId: string,
): VisibleCardReviewBatch {
  const polygon = [
    { x: 100, y: 100 },
    { x: 900, y: 100 },
    { x: 900, y: 900 },
    { x: 100, y: 900 },
  ];
  return {
    schema_version: "visible-card-review-batch/v1",
    batch_id: batchId,
    recording_id: "editor-recording",
    request_digest: "a".repeat(64),
    status: "ready",
    created_at_utc: "2026-09-03T07:00:00Z",
    updated_at_utc: "2026-09-03T07:00:00Z",
    detector: {
      bundle_id: "editor-detector",
      bundle_digest: "b".repeat(64),
      model: "editor-model",
      provider: "editor-provider",
      provider_version: "editor-provider-v1",
      preprocessing: "editor-preprocessing-v1",
      confidence_threshold: 0,
      input_size: 100,
    },
    progress: {
      phase: "ready",
      total_items: 1,
      frames_extracted: 1,
      finder_completed: 1,
      failed_items: 0,
    },
    items: [
      {
        item_id: itemId,
        status: "pending",
        event_id: "editor-event",
        event_index: 0,
        event_time_s: 0.4,
        event_time_ms: 400,
        target_offset_ms: 0,
        frame_index: 0,
        actual_offset_ms: 0,
        finder_status: "ok",
        failure: null,
        source: {
          package_id: "editor-package",
          frame_part_name: "frame_00",
          target_offset_ms: 0,
          image_url: "/editor-frame.png",
          frame_sha256: "c".repeat(64),
          source_asset_id: "editor-source",
          source_lineage_group: "editor-lineage",
          source_asset_sha256: "d".repeat(64),
          width: 100,
          height: 100,
        },
        finder: {
          provider: "editor-provider",
          provider_version: "editor-provider-v1",
          request_digest: "e".repeat(64),
          result_digest: "f".repeat(64),
          prediction_sha256: "1".repeat(64),
          proposals_recovered: false,
          raw_response: null,
          proposals: [
            {
              proposal_index: 0,
              box_2d: { x_min: 100, y_min: 100, x_max: 900, y_max: 900 },
              polygon,
              side: "unknown",
              label: "visible card",
            },
          ],
        },
        review: null,
      },
    ],
    failures: [],
    queue_schema_version: "visible-card-review-queue/v2",
    queue_digest: null,
    revision: 0,
    summary: {
      total_frames: 1,
      reviewed_frames: 0,
      pending_frames: 1,
      failed_frames: 0,
      usable_frames: 0,
      empty_frames: 0,
      unusable_frames: 0,
      retained_cards: 0,
      accepted_proposals: 0,
      corrected_proposals: 0,
      removed_proposals: 0,
      added_cards: 0,
      identity_unusable_cards: 0,
    },
    review_state: "draft",
    reviewer: null,
    completed_at_utc: null,
    completed_version_id: null,
    completed_version_digest: null,
    completion_receipt_id: null,
    completion_receipt_digest: null,
    parent_version_id: null,
    parent_digest: null,
    downstream_readiness: {
      state: "not_ready",
      message: "Review is in progress.",
      queue_digest: null,
    },
  } as unknown as VisibleCardReviewBatch;
}
