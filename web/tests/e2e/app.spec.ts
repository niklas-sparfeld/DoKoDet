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

function cardEventReviewResponse(
  events: Array<Record<string, unknown>> = [],
  proposals = [cardEventProposalOne, cardEventProposalTwo],
  revision = 0,
  overrides: Record<string, unknown> = {},
) {
  return {
    annotation: {
      schema_version: "cardevent-annotation/v2",
      video: "card-events.mov",
      events,
    },
    completed_at: null,
    completed_version_digest: null,
    completed_version_id: null,
    completion_receipt_id: null,
    draft_digest: "a".repeat(64),
    draft_revision: revision,
    full_video_acknowledged: false,
    parent_digest: null,
    parent_version_id: null,
    proposals,
    proposal_decision_digest: null,
    recording_id: CARD_EVENT_RECORDING_ID,
    reviewed_annotation_digest: null,
    review_state: revision === 0 ? "not_started" : "draft",
    reviewer: null,
    schema_version: "cardevent-review/v1",
    source_asset_id: "source-card-events",
    source_sha256: "b".repeat(64),
    video: "card-events.mov",
    ...overrides,
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

test.beforeEach(async ({ page }) => {
  let cardEventReview = cardEventReviewResponse();
  const recordingSummary = {
    recording_id: emptyRecordingDetail.recording_id,
    source_asset_id: emptyRecordingDetail.source_asset_id,
    video_id: emptyRecordingDetail.video_id,
    session_id: emptyRecordingDetail.session_id,
    state: emptyRecordingDetail.state,
    source_sha256: emptyRecordingDetail.source_sha256,
    received_at: emptyRecordingDetail.received_at,
    round_id: emptyRecordingDetail.round_id,
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
      url.includes(`/recordings/${CARD_EVENT_RECORDING_ID}/card-event-review`)
    ) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON() as {
          annotation: { events: Array<Record<string, unknown>> };
          proposals: Array<{ proposal_id: string; decision: string }>;
          full_video_acknowledged: boolean;
        };
        const events = [...body.annotation.events];
        for (const proposal of [cardEventProposalOne, cardEventProposalTwo]) {
          const decision = body.proposals.find(
            (item) => item.proposal_id === proposal.proposal_id,
          )?.decision;
          if (
            decision === "accepted" &&
            !events.some((event) => event.time_s === proposal.time_s)
          ) {
            events.push({
              time_s: proposal.time_s,
              type: "card_played",
              confidence: "confirmed",
            });
          }
        }
        cardEventReview = cardEventReviewResponse(
          events.sort(
            (first, second) => Number(first.time_s) - Number(second.time_s),
          ),
          [cardEventProposalOne, cardEventProposalTwo].map((proposal) => ({
            ...proposal,
            decision:
              body.proposals.find(
                (item) => item.proposal_id === proposal.proposal_id,
              )?.decision ?? "undecided",
          })),
          cardEventReview.draft_revision + 1,
          { full_video_acknowledged: body.full_video_acknowledged },
        );
      }
      if (route.request().method() === "POST" && url.endsWith("/complete")) {
        const body = route.request().postDataJSON() as {
          reviewer: string;
          full_video_acknowledged: boolean;
        };
        cardEventReview = cardEventReviewResponse(
          cardEventReview.annotation.events as Array<Record<string, unknown>>,
          cardEventReview.proposals,
          cardEventReview.draft_revision,
          {
            review_state: "completed",
            full_video_acknowledged: body.full_video_acknowledged,
            reviewer: body.reviewer,
            completed_at: "2026-09-01T08:00:00Z",
            completed_version_id: "cardevent-reviewed-version-1",
            completed_version_digest: "c".repeat(64),
            reviewed_annotation_digest: "d".repeat(64),
            proposal_decision_digest: "e".repeat(64),
            completion_receipt_id: "receipt-cardevent-review-1",
          },
        );
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(cardEventReview),
        });
        return;
      }
      if (route.request().method() === "POST" && url.endsWith("/revisions")) {
        const body = route.request().postDataJSON() as {
          parent_version_id: string;
        };
        cardEventReview = cardEventReviewResponse(
          cardEventReview.annotation.events as Array<Record<string, unknown>>,
          cardEventReview.proposals,
          cardEventReview.draft_revision + 1,
          {
            review_state: "draft",
            full_video_acknowledged: false,
            reviewer: null,
            completed_at: null,
            completed_version_id: null,
            completed_version_digest: null,
            reviewed_annotation_digest: null,
            proposal_decision_digest: null,
            completion_receipt_id: null,
            parent_version_id: body.parent_version_id,
            parent_digest: "c".repeat(64),
          },
        );
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(cardEventReview),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(cardEventReview),
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

test("edits and persists CardEvent events and proposal decisions in the browser", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/recordings/${CARD_EVENT_RECORDING_ID}`);

  const video = page.getByLabel(`Source recording ${CARD_EVENT_RECORDING_ID}`);
  await expect(video).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add event at playhead" }),
  ).toBeVisible();

  await video.evaluate((element) => {
    const source = element as HTMLVideoElement;
    source.currentTime = 2;
    source.dispatchEvent(new Event("timeupdate"));
  });
  await expect(page.getByText(/Playhead 0:02\.000/)).toBeVisible();
  await page.getByRole("button", { name: "Add event at playhead" }).click();
  await page.getByRole("button", { name: "Nudge +1 frame" }).click();
  await page
    .getByLabel("Event type for selected event")
    .selectOption("card_moved");
  const notes = page.getByLabel("Notes for selected event");
  await notes.fill("Moved to the table");
  await notes.press("Tab");
  await expect(page.getByText("Moved to the table")).toBeVisible();

  await page.getByRole("button", { name: "Remove selected event" }).click();
  await expect(
    page.getByText("Event removed. You can undo this action."),
  ).toBeVisible();

  const firstProposal = page.getByRole("listitem", {
    name: /Proposal at 0:01\.500 seconds/,
  });
  await firstProposal.getByRole("button", { name: "Accept proposal" }).click();
  await expect(firstProposal).toContainText("Accepted");
  const secondProposal = page.getByRole("listitem", {
    name: /Proposal at 0:03\.000 seconds/,
  });
  await secondProposal
    .getByRole("button", { name: "Dismiss proposal" })
    .click();
  await expect(secondProposal).toContainText("Dismissed");

  await page.setViewportSize({ width: 390, height: 844 });
  const horizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  );
  expect(horizontalOverflow).toBe(false);
});

test("completes a CardEvent review and starts an immutable revision", async ({
  page,
}) => {
  await page.goto(`/recordings/${CARD_EVENT_RECORDING_ID}`);

  const video = page.getByLabel(`Source recording ${CARD_EVENT_RECORDING_ID}`);
  await expect(video).toBeVisible();
  await video.evaluate((element) => {
    const source = element as HTMLVideoElement;
    Object.defineProperty(source, "duration", {
      configurable: true,
      value: 12.5,
    });
    Object.defineProperty(source, "currentTime", {
      configurable: true,
      value: 12.5,
      writable: true,
    });
    source.dispatchEvent(new Event("loadedmetadata"));
    source.dispatchEvent(new Event("timeupdate"));
  });

  const acknowledgement = page.getByRole("checkbox");
  await expect(acknowledgement).toBeEnabled();
  await acknowledgement.check();
  await page
    .getByRole("listitem", { name: /Proposal at 0:01\.500 seconds/ })
    .getByRole("button", { name: "Accept proposal" })
    .click();
  await page
    .getByRole("listitem", { name: /Proposal at 0:03\.000 seconds/ })
    .getByRole("button", { name: "Dismiss proposal" })
    .click();
  await page.getByRole("textbox", { name: "Reviewer" }).fill("operator");

  const completeButton = page.getByRole("button", {
    name: "Complete full recording review",
  });
  await expect(completeButton).toBeEnabled();
  await completeButton.click();
  await expect(
    page.getByRole("heading", { name: "Reviewed annotation" }),
  ).toBeVisible();
  await expect(
    page.getByText("cardevent-reviewed-version-1", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No current training-use blocker."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Start a new revision" }).click();
  await expect(
    page.getByRole("button", { name: "Complete full recording review" }),
  ).toBeVisible();
  await expect(
    page.getByText(/The completed version remains unchanged/),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Complete the full recording CardEvent review before training use.",
    ),
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
