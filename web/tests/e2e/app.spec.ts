import { expect, test } from "@playwright/test";

import {
  ANALYSIS_ID,
  ambiguousStatus,
  ambiguousTimeline,
  changedCounterfactualResponse,
  emptyRecordingDetail,
  impossibleStatus,
  impossibleTimeline,
  incompleteStatus,
  incompleteTimeline,
  RECORDING_ID,
  recordingDetailWithAnalysis,
  resolvedStatus,
  resolvedTimeline,
  unchangedCounterfactualResponse,
} from "../../src/test/roundAnalysisFixture";

const CARD_EVENT_RECORDING_ID = "recording-card-events";
const IDENTITY_BATCH_ID = "visual-card-identity-batch-0123456789abcdef01234567";
const cardEventProposalOne = {
  proposal_id: "proposal-one",
  proposal_generator_run_id: "run-one",
  time_s: 1.5,
  probability: 0.91,
  model_bundle_id: "model-one",
  execution_platform: "local",
  decision: "undecided",
};
const cardEventProposalTwo = {
  proposal_id: "proposal-two",
  proposal_generator_run_id: "run-two",
  time_s: 3,
  probability: 0.72,
  model_bundle_id: "model-two",
  execution_platform: "local",
  decision: "undecided",
};

function cardEventReviewResourceResponse(
  events: Array<Record<string, unknown>> = [
    {
      event_id: "cardevent-event-one",
      effective_time_s: cardEventProposalOne.time_s,
      type: "card_played",
      confidence: "proposed",
      notes: null,
      state: "proposed",
      origin: "model",
      proposal: {
        proposal_id: cardEventProposalOne.proposal_id,
        proposal_generator_run_id:
          cardEventProposalOne.proposal_generator_run_id,
        proposal_time_s: cardEventProposalOne.time_s,
        probability: cardEventProposalOne.probability,
        model_bundle_id: cardEventProposalOne.model_bundle_id,
        execution_platform: cardEventProposalOne.execution_platform,
      },
    },
    {
      event_id: "cardevent-event-two",
      effective_time_s: cardEventProposalTwo.time_s,
      type: "card_played",
      confidence: "proposed",
      notes: null,
      state: "proposed",
      origin: "model",
      proposal: {
        proposal_id: cardEventProposalTwo.proposal_id,
        proposal_generator_run_id:
          cardEventProposalTwo.proposal_generator_run_id,
        proposal_time_s: cardEventProposalTwo.time_s,
        probability: cardEventProposalTwo.probability,
        model_bundle_id: cardEventProposalTwo.model_bundle_id,
        execution_platform: cardEventProposalTwo.execution_platform,
      },
    },
  ],
  overrides: Record<string, unknown> = {},
) {
  const reviewedEvents = events.filter((event) => event.state === "reviewed");
  return {
    annotation: {
      schema_version: "cardevent-annotation/v2",
      video: "card-events.mov",
      events: reviewedEvents.map((event) => ({
        time_s: event.effective_time_s,
        type: event.type,
        confidence: event.confidence,
      })),
    },
    completed_at: null,
    completed_version_digest: null,
    completed_version_id: null,
    completion_receipt_id: null,
    draft_digest: "a".repeat(64),
    draft_revision: 0,
    events,
    full_video_acknowledged: false,
    operator: "operator",
    parent_digest: null,
    parent_review_id: null,
    parent_version_id: null,
    proposals: [cardEventProposalOne, cardEventProposalTwo],
    proposal_decision_digest: null,
    recording_id: CARD_EVENT_RECORDING_ID,
    reviewed_annotation_digest: null,
    reviewer: null,
    review_id: "cardevent-review-1",
    review_state: "draft",
    review_url: "/card-event-reviews/cardevent-review-1",
    schema_version: "cardevent-review-resource/v1",
    source_asset_id: "source-card-events",
    source_sha256: "b".repeat(64),
    updated_at: "2026-09-01T07:20:46Z",
    created_at: "2026-09-01T07:20:46Z",
    video: "card-events.mov",
    ...overrides,
  };
}

function cardEventReviewListItem(
  resource: ReturnType<typeof cardEventReviewResourceResponse>,
) {
  const eventCounts = {
    reviewed: resource.events.filter((event) => event.state === "reviewed")
      .length,
    proposed: resource.events.filter((event) => event.state === "proposed")
      .length,
    dismissed: resource.events.filter((event) => event.state === "dismissed")
      .length,
  };
  return {
    review_id: resource.review_id,
    review_url: resource.review_url,
    recording_id: resource.recording_id,
    state: resource.review_state,
    review_state: resource.review_state,
    operator: resource.operator,
    reviewer: resource.reviewer,
    created_at: resource.created_at,
    updated_at: resource.updated_at,
    completed_at: resource.completed_at,
    completed_version_id: resource.completed_version_id,
    completed_version_digest: resource.completed_version_digest,
    parent_review_id: resource.parent_review_id,
    parent_version_id: resource.parent_version_id,
    event_counts: eventCounts,
    reviewed_event_count: eventCounts.reviewed,
    proposed_event_count: eventCounts.proposed,
    dismissed_event_count: eventCounts.dismissed,
  };
}

const cardEventRecording = {
  ...emptyRecordingDetail,
  recording_id: CARD_EVENT_RECORDING_ID,
  source_asset_id: "source-card-events",
  video_id: "video-card-events",
  round_id: "round-card-events",
  source: {
    ...emptyRecordingDetail.source,
    recording_id: CARD_EVENT_RECORDING_ID,
    video_id: "video-card-events",
    round_id: "round-card-events",
  },
  video: {
    ...emptyRecordingDetail.video,
    url: `/v1/repository-bundles/${CARD_EVENT_RECORDING_ID}/video`,
  },
  training_use: {
    ...emptyRecordingDetail.training_use,
    card_event_task: {
      task_enrollment_id: "enrollment-card-events",
      task: "cardevent_event_detection",
      disposition: "selected",
      lifecycle_state: "active",
      operator: "operator",
      created_at_utc: "2026-09-01T07:20:46Z",
      reason: null,
    },
    eligibility: "review_required",
    blocker:
      "Complete the full recording CardEvent review before training use.",
  },
};

test("loads the frontend foundation shell", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle("DokoDetector");
  await expect(page.getByRole("heading", { name: "Recordings" })).toBeVisible();
});

test("keeps the identity review workspace usable on desktop and narrow viewports", async ({
  page,
}) => {
  const itemId = "identity-item-1";
  const batch = {
    schema_version: "visual-card-identity-review-batch/v1",
    batch_id: IDENTITY_BATCH_ID,
    recording_id: "recording-identity",
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
      total_items: 1,
      crops_materialized: 1,
      proposals_completed: 1,
      failed_items: 0,
    },
    revision: 0,
    review_state: "draft",
    reviewer: null,
    completed_at_utc: null,
    parent_version_id: null,
    parent_version_digest: null,
    publication: null,
    dataset: null,
    summary: {
      total_items: 1,
      pending_items: 1,
      decided_items: 0,
      accepted_items: 0,
      corrected_items: 0,
      identity_unusable_items: 0,
      source_problem_items: 0,
      failed_items: 0,
    },
    items: [
      {
        schema_version: "visual-card-identity-review-item/v1",
        item_id: itemId,
        visible_card_review_item_id: "package-identity:frame_00",
        source: {
          visible_card_review_batch_id: "visible-card-batch-identity",
          visible_card_review_item_id: "package-identity:frame_00",
          package_id: "package-identity",
          frame_part_name: "frame_00",
          image_url: "/fixture-source.jpg",
          frame_sha256: "1".repeat(64),
          source_asset_id: "source-identity",
          source_lineage_group: "group-identity",
          source_asset_sha256: "2".repeat(64),
          width: 40,
          height: 30,
        },
        visible_card: {
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
        },
        visible_card_digest: "3".repeat(64),
        crop: {
          image_url: `/v1/identity-reviews/${IDENTITY_BATCH_ID}/items/${itemId}/crop`,
          sha256: "4".repeat(64),
          byte_length: 42,
          content_type: "image/x-portable-pixmap",
          width: 32,
          height: 24,
          policy_id: "raw_rectangular",
          policy_digest: "5".repeat(64),
        },
        proposal: {
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
          candidates: [{ card: "CLUBS_NINE", probability: 0.75 }],
          score: 0.75,
          result: { fixture: true },
          result_digest: "6".repeat(64),
        },
        decision: {
          schema_version: "visual-card-identity-decision/v1",
          status: "pending",
          identity: null,
          reason: null,
          failure_tags: [],
          reviewer: null,
          updated_at_utc: null,
        },
        status: "ready",
        failure: null,
      },
    ],
    coverage: {
      schema_version: "visual-card-identity-review-coverage/v1",
      visible_card_review_item_count: 1,
      reviewed_visible_card_count: 1,
      identity_usable_card_count: 1,
      excluded_card_count: 0,
      excluded_cards: [],
      coverage_digest: "8".repeat(64),
    },
    failures: [],
  };
  let currentBatch = batch;
  await page.route("**/v1/identity-reviews/**", async (route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "GET" && url.endsWith(IDENTITY_BATCH_ID)) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(currentBatch),
      });
      return;
    }
    if (request.method() === "PUT" && url.includes("/items/")) {
      const payload = request.postDataJSON() as {
        action: string;
        identity?: string | null;
        reason?: string | null;
        failure_tags?: string[];
      };
      const updatedItem = {
        ...currentBatch.items[0],
        decision: {
          ...currentBatch.items[0].decision,
          status:
            payload.action === "accept_proposal" ? "accepted" : "corrected",
          identity:
            payload.action === "accept_proposal"
              ? (currentBatch.items[0].proposal?.candidates[0]?.card ?? null)
              : (payload.identity ?? null),
          reason: payload.reason ?? null,
          failure_tags: payload.failure_tags ?? [],
          reviewer: "web-operator",
          updated_at_utc: "2026-09-02T10:01:00Z",
        },
      };
      currentBatch = {
        ...currentBatch,
        revision: currentBatch.revision + 1,
        summary: {
          ...currentBatch.summary,
          pending_items: 0,
          decided_items: 1,
          accepted_items: 1,
        },
        items: [updatedItem],
      };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(currentBatch),
      });
      return;
    }
    if (request.method() === "POST" && url.endsWith("/complete")) {
      currentBatch = {
        ...currentBatch,
        revision: currentBatch.revision + 1,
        review_state: "completed",
        reviewer: "web-operator",
        completed_at_utc: "2026-09-02T10:02:00Z",
        publication: {
          version_id: "visual-card-identity-review-published",
          version_digest: "a".repeat(64),
          version_path: null,
          receipt_id: "receipt-visual-card-identity-published",
          receipt_digest: "b".repeat(64),
          receipt_path: null,
          input_draft_revision: currentBatch.revision,
          input_draft_digest: "c".repeat(64),
        },
        dataset: {
          schema_version: "visual-card-identity-dataset/v1",
          status: "eligible",
          dataset_version_id: "visual-card-identity-dataset-published",
          dataset_version_digest: "d".repeat(64),
          dataset_path: null,
          split_version_id: "visual-card-identity-split-published",
          split_version_digest: "e".repeat(64),
          split_path: null,
          artifact_index_id: "visual-card-identity-artifacts-published",
          artifact_index_digest: "f".repeat(64),
          artifact_index_path: null,
          lineage_path: null,
          lineage_digest: "1".repeat(64),
          sample_count: 1,
          excluded_count: 0,
          development_partition: "unassigned",
          blocker: null,
        },
      };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(currentBatch),
      });
      return;
    }
    if (request.method() === "POST" && url.endsWith("/revisions")) {
      currentBatch = {
        ...currentBatch,
        revision: currentBatch.revision + 1,
        review_state: "draft",
        reviewer: null,
        completed_at_utc: null,
        parent_version_id: "visual-card-identity-review-published",
        parent_version_digest: "a".repeat(64),
        publication: null,
        dataset: null,
      };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(currentBatch),
      });
      return;
    }
    await route.fulfill({
      contentType: "image/x-portable-pixmap",
      body: "P6\n1 1\n255\n\0\0\0",
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/identity-reviews/${IDENTITY_BATCH_ID}`);
  await expect(
    page.getByRole("heading", { name: "Visual card identities" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "CLUBS_NINE", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Accept proposal/ }).click();
  await expect(page.getByRole("heading", { name: "Accepted" })).toBeVisible();
  await page.getByRole("button", { name: "Complete identity review" }).click();
  await expect(page.getByText(/Completed by web-operator/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start a new revision" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByText("Source context")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});

test.beforeEach(async ({ page }) => {
  let cardEventReview = cardEventReviewResourceResponse();
  let cardEventReviewCollection = {
    schema_version: "cardevent-review-collection/v1",
    recording_id: CARD_EVENT_RECORDING_ID,
    current_review_id: null,
    draft_review_id: null,
    latest_completed_review_id: null,
    reviews: [],
  };
  const recordingSummary = {
    recording_id: emptyRecordingDetail.recording_id,
    source_asset_id: emptyRecordingDetail.source_asset_id,
    video_id: emptyRecordingDetail.video_id,
    session_id: emptyRecordingDetail.session_id,
    state: emptyRecordingDetail.state,
    source_sha256: emptyRecordingDetail.source_sha256,
    received_at: emptyRecordingDetail.received_at,
    round_id: emptyRecordingDetail.round_id,
    card_event_review_state: "not_started",
    card_event_event_count: 0,
    development_partition: "unassigned",
    evidence_package_ids: [],
    analyses: [],
    can_start_analysis: true,
    analysis_blocker: null,
  };
  await page.route("**/v1/recordings", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ recordings: [recordingSummary] }),
    });
  });
  await page.route("**/v1/recordings/**", async (route) => {
    const url = route.request().url();
    if (
      url.endsWith(`/recordings/${CARD_EVENT_RECORDING_ID}/card-event-reviews`)
    ) {
      if (route.request().method() === "POST") {
        cardEventReview = cardEventReviewResourceResponse();
        cardEventReviewCollection = {
          ...cardEventReviewCollection,
          current_review_id: cardEventReview.review_id,
          draft_review_id: cardEventReview.review_id,
          reviews: [cardEventReviewListItem(cardEventReview)],
        };
        await route.fulfill({
          contentType: "application/json",
          status: 201,
          body: JSON.stringify(cardEventReview),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(cardEventReviewCollection),
      });
      return;
    }
    if (url.endsWith("/card-event-reviews")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...cardEventReviewCollection,
          recording_id: emptyRecordingDetail.recording_id,
        }),
      });
      return;
    }
    if (route.request().method() === "POST") {
      await route.fulfill({
        contentType: "application/json",
        status: 202,
        body: JSON.stringify(resolvedStatus),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        url.includes(`/recordings/${CARD_EVENT_RECORDING_ID}`)
          ? cardEventRecording
          : url.includes(`/recordings/${RECORDING_ID}`)
            ? recordingDetailWithAnalysis
            : emptyRecordingDetail,
      ),
    });
  });
  await page.route("**/v1/card-event-reviews/**", async (route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "PATCH" && url.includes("/events/")) {
      const payload = request.postDataJSON() as {
        action: string;
        effective_time_s?: number;
      };
      const eventId = decodeURIComponent(url.split("/").pop() ?? "");
      const event = cardEventReview.events.find(
        (candidate) => candidate.event_id === eventId,
      );
      if (event === undefined) {
        await route.fulfill({ status: 404, body: "Not found" });
        return;
      }
      const changedEvent = {
        ...event,
        ...(payload.action === "accept"
          ? { state: "reviewed", confidence: "confirmed" }
          : payload.action === "dismiss"
            ? { state: "dismissed", confidence: "ignore" }
            : payload.action === "undo"
              ? { state: "proposed", confidence: "proposed" }
              : payload.action === "retime"
                ? { effective_time_s: payload.effective_time_s }
                : {}),
      };
      cardEventReview = {
        ...cardEventReview,
        draft_revision: cardEventReview.draft_revision + 1,
        events: cardEventReview.events.map((candidate) =>
          candidate.event_id === eventId ? changedEvent : candidate,
        ),
      };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "cardevent-review-event/v1",
          review_id: cardEventReview.review_id,
          draft_revision: cardEventReview.draft_revision,
          changed_event: changedEvent,
          event_counts: {
            reviewed: cardEventReview.events.filter(
              (candidate) => candidate.state === "reviewed",
            ).length,
            proposed: cardEventReview.events.filter(
              (candidate) => candidate.state === "proposed",
            ).length,
            dismissed: cardEventReview.events.filter(
              (candidate) => candidate.state === "dismissed",
            ).length,
          },
          completion_blockers: [],
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.endsWith("/events")) {
      const payload = request.postDataJSON() as {
        effective_time_s: number;
        type: string;
        confidence: string;
        notes: string | null;
      };
      const changedEvent = {
        event_id: `cardevent-event-manual-${cardEventReview.draft_revision + 1}`,
        effective_time_s: payload.effective_time_s,
        type: payload.type,
        confidence: payload.confidence,
        notes: payload.notes,
        state: "reviewed",
        origin: "manual",
        proposal: null,
      };
      cardEventReview = {
        ...cardEventReview,
        draft_revision: cardEventReview.draft_revision + 1,
        events: [...cardEventReview.events, changedEvent],
      };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "cardevent-review-event/v1",
          review_id: cardEventReview.review_id,
          draft_revision: cardEventReview.draft_revision,
          changed_event: changedEvent,
          event_counts: { reviewed: 1, proposed: 2, dismissed: 0 },
          completion_blockers: ["proposed_events"],
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(cardEventReview),
    });
  });
  await page.route("**/v1/round-analyses/**", async (route) => {
    const fixture = new URL(page.url()).searchParams.get("fixture");
    const variants = {
      ambiguous: { status: ambiguousStatus, timeline: ambiguousTimeline },
      incomplete: { status: incompleteStatus, timeline: incompleteTimeline },
      impossible: { status: impossibleStatus, timeline: impossibleTimeline },
    } as const;
    const selected =
      fixture === null ? null : variants[fixture as keyof typeof variants];
    const status = selected?.status ?? resolvedStatus;
    const timeline = selected?.timeline ?? resolvedTimeline;
    if (
      route.request().method() === "POST" &&
      route.request().url().includes("/counterfactuals")
    ) {
      const counterfactual =
        new URL(page.url()).searchParams.get("counterfactual") === "unchanged"
          ? unchangedCounterfactualResponse
          : changedCounterfactualResponse;
      await route.fulfill({
        contentType: "application/json",
        status: 201,
        body: JSON.stringify(counterfactual),
      });
      return;
    }
    if (route.request().url().endsWith("/timeline")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(timeline),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(status),
    });
  });
});

test("opens a recording detail page from the catalog", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Open recording" }).click();

  await expect(page).toHaveURL("/recordings/recording-detail-1");
  await expect(
    page.getByRole("heading", { name: "Recording details" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Source recording recording-detail-1"),
  ).toHaveAttribute("src", "/v1/repository-bundles/recording-detail-1/video");
  await expect(
    page.getByRole("heading", { name: "Card events" }),
  ).toBeVisible();
  await expect(
    page.getByText("No CardEvent review has been started."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Training use" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Round analyses" }),
  ).toBeVisible();
});

test("lists and opens a CardEvent review from the recording page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/recordings/${CARD_EVENT_RECORDING_ID}`);

  await expect(page.getByText("No CardEvent reviews yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add review" })).toBeVisible();
  await page.getByRole("button", { name: "Add review" }).click();

  await expect(page).toHaveURL("/card-event-reviews/cardevent-review-1");
  await expect(
    page.getByRole("heading", { name: "CardEvent review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Draft review" }),
  ).toBeVisible();
  await expect(
    page.getByLabel(`Source recording ${CARD_EVENT_RECORDING_ID}`),
  ).toBeVisible();
  await expect(page.getByText("2 events").first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
});

test("runs twenty queued CardEvent decisions without waiting between inputs", async ({
  page,
}) => {
  const events = Array.from({ length: 20 }, (_, index) => ({
    event_id: `cardevent-event-${index + 1}`,
    effective_time_s: (index + 1) * 0.5,
    type: "card_played",
    confidence: "proposed",
    notes: null,
    state: "proposed",
    origin: "model",
    proposal: {
      proposal_id: `proposal-${index + 1}`,
      proposal_generator_run_id: `run-${index + 1}`,
      proposal_time_s: (index + 1) * 0.5,
      probability: 0.9,
      model_bundle_id: "model-card-events",
      execution_platform: "local",
    },
  }));
  let current = cardEventReviewResourceResponse(events);
  const commands: Array<{ action: string; expected_revision: number }> = [];
  await page.route("**/v1/card-event-reviews/**", async (route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "GET") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(current),
      });
      return;
    }
    const payload = request.postDataJSON() as {
      action: string;
      expected_revision: number;
    };
    const eventId = decodeURIComponent(url.split("/").pop() ?? "");
    const changedEvent = {
      ...current.events.find((event) => event.event_id === eventId)!,
      state: payload.action === "accept" ? "reviewed" : "dismissed",
      confidence: payload.action === "accept" ? "confirmed" : "ignore",
    };
    commands.push({
      action: payload.action,
      expected_revision: payload.expected_revision,
    });
    current = {
      ...current,
      draft_revision: current.draft_revision + 1,
      events: current.events.map((event) =>
        event.event_id === eventId ? changedEvent : event,
      ),
    };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "cardevent-review-event/v1",
        review_id: current.review_id,
        draft_revision: current.draft_revision,
        changed_event: changedEvent,
        event_counts: { reviewed: 20, proposed: 0, dismissed: 0 },
        completion_blockers: [],
      }),
    });
  });

  await page.goto(`/card-event-reviews/${current.review_id}`);
  await expect(
    page.getByRole("heading", { name: "Draft review" }),
  ).toBeVisible();
  for (let index = 0; index < 20; index += 1) {
    await page.keyboard.press("Alt+ArrowRight");
    await page.keyboard.press(index % 2 === 0 ? "A" : "D");
  }
  await expect(page.getByText("20 queued")).not.toBeVisible();
  await expect.poll(() => commands.length).toBe(20);
  expect(commands).toEqual(
    Array.from({ length: 20 }, (_, index) => ({
      action: index % 2 === 0 ? "accept" : "dismiss",
      expected_revision: index,
    })),
  );
  await expect(page.getByText("Saved").first()).toBeVisible();
});

test("keeps the unified CardEvent controls usable with pointer input", async ({
  page,
}) => {
  await page.goto("/card-event-reviews/cardevent-review-1");
  await expect(
    page.getByRole("heading", { name: "Draft review" }),
  ).toBeVisible();
  const rows = page.locator("tbody tr");
  await rows
    .nth(0)
    .getByRole("button", { name: /Accept/ })
    .click();
  await rows
    .nth(1)
    .getByRole("button", { name: /Dismiss/ })
    .click();
  await expect(page.getByText("Reviewed").last()).toBeVisible();
  await expect(page.getByText("Dismissed").last()).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Nudge \+1 frame/ }),
  ).toBeVisible();
});

test("shows completed reviews and their draft revisions on the recording page", async ({
  page,
}) => {
  const completed = cardEventReviewResourceResponse(
    [
      {
        event_id: "cardevent-event-completed",
        effective_time_s: 1.5,
        type: "card_played",
        confidence: "confirmed",
        notes: null,
        state: "reviewed",
        origin: "manual",
        proposal: null,
      },
    ],
    {
      review_id: "cardevent-review-completed",
      review_url: "/card-event-reviews/cardevent-review-completed",
      review_state: "completed",
      reviewer: "operator",
      completed_at: "2026-09-01T08:00:00Z",
      completed_version_id: "cardevent-reviewed-version-1",
      completed_version_digest: "c".repeat(64),
      reviewed_annotation_digest: "d".repeat(64),
      proposal_decision_digest: "e".repeat(64),
      completion_receipt_id: "receipt-cardevent-review-1",
      full_video_acknowledged: true,
    },
  );
  const revision = cardEventReviewResourceResponse([], {
    review_id: "cardevent-review-revision",
    review_url: "/card-event-reviews/cardevent-review-revision",
    parent_review_id: completed.review_id,
    parent_version_id: completed.completed_version_id,
    parent_digest: completed.completed_version_digest,
  });
  await page.route(
    `**/v1/recordings/${CARD_EVENT_RECORDING_ID}/card-event-reviews`,
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "cardevent-review-collection/v1",
          recording_id: CARD_EVENT_RECORDING_ID,
          current_review_id: completed.review_id,
          draft_review_id: revision.review_id,
          latest_completed_review_id: completed.review_id,
          reviews: [
            cardEventReviewListItem(revision),
            cardEventReviewListItem(completed),
          ],
        }),
      });
    },
  );
  await page.route("**/v1/card-event-reviews/**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        route.request().url().includes(completed.review_id)
          ? completed
          : revision,
      ),
    });
  });

  await page.goto(`/recordings/${CARD_EVENT_RECORDING_ID}`);

  await expect(
    page.getByText(
      /Revision of cardevent-review-completed · draft by operator/,
    ),
  ).toBeVisible();
  await expect(page.getByText(/Annotated by operator on/)).toBeVisible();
  await page.getByRole("link", { name: "Open review" }).click();

  await expect(page).toHaveURL(
    "/card-event-reviews/cardevent-review-completed",
  );
  await expect(
    page.getByRole("heading", { name: "Completed review" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "This completed version is read-only to preserve its lineage. Start a revision below to correct the annotations; the recording remains unchanged.",
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Correct annotations" }).click();
  await expect(page).toHaveURL("/card-event-reviews/cardevent-review-revision");
  await expect(
    page.getByRole("heading", { name: "Draft review" }),
  ).toBeVisible();
});

test("renders a resolved analysis in synchronized desktop columns", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}`);

  await expect(page.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Table observation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Reconstruction hypothesis" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("option", { name: /observation-001/ })
      .getByRole("group", { name: "Counterfactual" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Open event details for event 1" })
    .click();
  const frameDialog = page.getByRole("dialog", { name: /Event 1/ });
  await expect(frameDialog).toBeVisible();
  await expect(
    frameDialog.getByRole("img", {
      name: "Enlarged evidence frame for event 1",
    }),
  ).toHaveCount(1);
  await expect(
    frameDialog.getByLabel("Evidence video snippet for event 1"),
  ).toHaveCount(1);
  await expect(
    frameDialog.getByLabel("Full recording for event 1 in detail view"),
  ).toHaveCount(1);
  await expect(frameDialog.getByText("Diamonds Jack")).toBeVisible();
  await frameDialog
    .getByRole("button", { name: "Close event details" })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("listbox").locator(":scope > li")).toHaveCount(2);
  await expect(page.getByText("No central frame available")).toBeVisible();

  const rowStyle = await page
    .getByRole("option", { name: /observation-001/ })
    .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
  expect(rowStyle.split(" ")).toHaveLength(3);

  const scriptSource = await page
    .locator('script[type="module"]')
    .getAttribute("src");
  expect(scriptSource).toMatch(/^\/assets\/index-[^/]+\.js$/);
});

test("restores deep links and moves the selected row with keyboard navigation", async ({
  page,
}) => {
  await page.goto(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&row=observation-002&hypothesis=2`,
  );

  const selectedRow = page.getByRole("option", {
    name: /observation-002/,
    selected: true,
  });
  await expect(selectedRow).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Hypothesis" })).toHaveValue(
    "2",
  );
  await expect(
    page.getByRole("option", { name: /observation-002/, selected: true }),
  ).toContainText("Hearts Ten");

  await selectedRow.press("ArrowUp");

  await expect(page).toHaveURL(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&hypothesis=2&row=observation-001`,
  );
  await expect(
    page.getByRole("option", { name: /observation-001/, selected: true }),
  ).toBeVisible();

  await expect(page.getByText("Clubs Nine").first()).toBeVisible();
});

test("submits a direct card identity correction", async ({ page }) => {
  let postedPayload: Record<string, unknown> | null = null;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/counterfactuals")
    ) {
      postedPayload = request.postDataJSON() as Record<string, unknown>;
    }
  });

  await page.goto(`/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}`);
  await page
    .getByRole("combobox", {
      name: "Correct classification for observation-002-card-01",
    })
    .selectOption("CLUBS_TEN");
  await expect(page.getByText(/Derived input uses Clubs Ten/)).toBeVisible();
  await page.getByRole("button", { name: "Run counterfactual" }).click();

  await expect
    .poll(() => postedPayload)
    .toMatchObject({
      card_identity_overrides: [
        {
          observation_id: "observation-002",
          observed_card_id: "observation-002-card-01",
          card: "CLUBS_TEN",
        },
      ],
    });
});

test("explains failure states and stacks the timeline at the narrow test width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&fixture=incomplete`,
  );

  await expect(page.getByText("Incomplete input")).toBeVisible();
  await expect(page.getByText("No retained hypotheses.")).toBeVisible();
  await expect(page.getByText("Missing Frame:")).toBeVisible();

  const rowDisplay = await page
    .getByRole("option", { name: /observation-001/ })
    .evaluate((element) => getComputedStyle(element).display);
  expect(rowDisplay).toBe("block");

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(0);
  await expect(page.getByText("Raw reconstruction-result JSON")).toBeVisible();
});

test("shows retained alternatives and search truncation as text cues", async ({
  page,
}) => {
  await page.goto(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&fixture=ambiguous`,
  );

  await expect(
    page.getByText(/This result is ambiguous\. Each retained hypothesis/),
  ).toBeVisible();
  await expect(page.getByText("Search Truncated:")).toBeVisible();
  await expect(page.getByText("Player 01 · Clubs Nine")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Jump to observation-001" }),
  ).toBeVisible();
});

test("runs a changed counterfactual and marks the derived differences", async ({
  page,
}) => {
  await page.goto(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&counterfactual=changed`,
  );

  await expect(
    page.getByRole("heading", { name: "Counterfactual run" }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Exclude observation observation-001" })
    .check();

  const statusBar = page.getByRole("status", {
    name: "Counterfactual status",
  });
  await expect(statusBar).toContainText("1 unapplied counterfactual change");
  await expect(statusBar).toHaveCSS("position", "fixed");
  await statusBar.getByRole("button", { name: "Apply now" }).click();

  await expect(
    page.getByRole("heading", { name: "Baseline versus counterfactual" }),
  ).toBeVisible();
  await expect(statusBar).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Changed observations and cards" }),
  ).toBeVisible();
  await expect(
    page.getByText("Changed", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Clubs Nine").last()).toBeVisible();
  await expect(
    page.getByText(
      "Search truncation makes this comparison incomplete. The displayed hypotheses may not include every legal sequence.",
    ),
  ).toBeVisible();
});

test("shows stable no-change markers for an unchanged counterfactual", async ({
  page,
}) => {
  await page.goto(
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&counterfactual=unchanged`,
  );

  await page
    .getByRole("checkbox", { name: "Exclude observation observation-001" })
    .check();
  await page.getByRole("button", { name: "Run counterfactual" }).click();

  await expect(page.getByText("No card-play changes.")).toBeVisible();
  await expect(
    page.getByText("No selected or ignored source actions changed."),
  ).toBeVisible();
  await expect(page.getByText("No focused decisions changed.")).toBeVisible();
});
