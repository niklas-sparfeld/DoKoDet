import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";

import { App } from "./App";
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
} from "./test/roundAnalysisFixture";
import type { RoundAnalysisStatus, RoundAnalysisTimeline } from "./api/client";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the recording catalog", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify({ recordings: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recordings" }),
    ).toBeInTheDocument();
  });

  it("opens a recording detail page with source playback and stable empty states", async () => {
    window.history.pushState({}, "", "/recordings/recording-detail-1");
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedStatus), {
            status: 202,
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

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Recording details" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Source recording recording-detail-1"),
    ).toHaveAttribute("src", "/v1/repository-bundles/recording-detail-1/video");
    expect(
      screen.getByRole("heading", { name: "Card events" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No CardEvent review has been started."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Training use" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Select the CardEvent task before reviewing this recording.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Round analyses" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No analyses have been started. This does not block CardEvent review.",
      ),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Start new analysis" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/recordings/recording-detail-1/round-analyses",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      `Analysis ${resolvedStatus.analysis_id} was queued.`,
    );
  });

  it("previews and starts a visible-card batch from the recording workspace", async () => {
    const recordingId = "recording-detail-1";
    window.history.pushState({}, "", `/recordings/${recordingId}`);
    const preview = {
      schema_version: "visible-card-review-preview/v1",
      recording_id: recordingId,
      batch_id: null,
      request_digest: "b".repeat(64),
      preview_digest: "c".repeat(64),
      source_asset_id: "source-detail-1",
      source_sha256: "a".repeat(64),
      source_lineage_group: "source-detail-1",
      task_enrollment_id: "enrollment-table-evidence-1",
      task_enrollment_selected: true,
      source_permission: "training_only",
      allowed_uses: ["training"],
      card_event_review_version_id: "cardevent-version-1",
      card_event_review_version_digest: "d".repeat(64),
      card_event_annotation_digest: "e".repeat(64),
      selected_event_count: 2,
      development_partition: "train",
      detector: {
        bundle_id: "fixture-visible-card-detector",
        bundle_digest: "f".repeat(64),
        model: "fixture-model",
        provider: "local",
        provider_version: "fixture-provider-v1",
        preprocessing: "fixture",
        confidence_threshold: 0.8,
        input_size: 224,
      },
      validation: { valid: true, blockers: [] },
    };
    const readiness = {
      schema_version: "visible-card-review-readiness/v1",
      recording_id: recordingId,
      state: "ready",
      message: "Ready to prepare visible-card frames.",
      blocker: null,
      selected_event_count: 2,
      batch: null,
      preview_digest: preview.preview_digest,
    };
    const batch = {
      schema_version: "visible-card-review-batch/v1",
      batch_id: "visible-card-batch-0123456789abcdef01234567",
      recording_id: recordingId,
      request_digest: preview.request_digest,
      status: "preparing",
      created_at_utc: "2026-09-01T07:20:46Z",
      updated_at_utc: "2026-09-01T07:20:46Z",
      detector: preview.detector,
      progress: {
        phase: "extracting_frames",
        total_items: 2,
        frames_extracted: 0,
        finder_completed: 0,
        failed_items: 0,
      },
      items: [],
      failures: [],
      queue_schema_version: "visible-card-review-queue/v1",
      queue_digest: null,
    };
    const readinessPath = `/v1/recordings/${recordingId}/visible-card-review`;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = String(input);
      if (path === `${readinessPath}/preview`) {
        return Promise.resolve(
          new Response(JSON.stringify(preview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path === `${readinessPath}/batches`) {
        return Promise.resolve(
          new Response(JSON.stringify(batch), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path === readinessPath) {
        return Promise.resolve(
          new Response(JSON.stringify(readiness), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedStatus), {
            status: 202,
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

    render(<App />);

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", {
        name: "Preview visible-card batch",
      }),
    );
    expect(await screen.findByText("Creation preview")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Create visible-card batch" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `${readinessPath}/batches`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            preview_digest: preview.preview_digest,
            request_digest: preview.request_digest,
          }),
        }),
      ),
    );
    expect(await screen.findByText("Preparing frames.")).toBeInTheDocument();
    expect(screen.getAllByText("0/2")).toHaveLength(2);
  });

  it("previews and confirms a development partition assignment", async () => {
    window.history.pushState({}, "", "/recordings/recording-detail-1");
    const recording = {
      ...emptyRecordingDetail,
      training_use: {
        ...emptyRecordingDetail.training_use,
        eligibility: "eligible",
        blocker: null,
        active_split_version_id: "cardevent-development-split-initial",
        active_split_digest: "b".repeat(64),
        development_group_keys: [
          ["session_id", "session-detail-1"],
          ["source_lineage", "source-detail-1"],
        ],
      },
      next_action: "Assign a development partition",
    };
    const preview = {
      schema_version: "cardevent-development-split-preview/v1",
      task: "cardevent_event_detection",
      recording_id: recording.recording_id,
      destination: "train",
      active_split_version_id: "cardevent-development-split-initial",
      active_split_digest: "b".repeat(64),
      affected_group_keys: [["session_id", "session-detail-1"]],
      affected_recordings: [
        {
          recording_id: recording.recording_id,
          source_asset_id: recording.source_asset_id,
          source_sha256: recording.source_sha256,
          current_partition: "unassigned",
          group_keys: [["session_id", "session-detail-1"]],
        },
      ],
      validation: { valid: true, blockers: [] },
      current_counts: { train: 0, validation: 0, unassigned: 1, test: 0 },
      proposed_counts: { train: 1, validation: 0, unassigned: 0, test: 0 },
      preview_digest: "c".repeat(64),
    };
    const applied = {
      schema_version: "cardevent-development-split-apply/v1",
      task: "cardevent_event_detection",
      recording_id: recording.recording_id,
      destination: "train",
      affected_recordings: preview.affected_recordings,
      split_version_id: "cardevent-development-split-next",
      split_version_digest: "d".repeat(64),
      receipt_id: "receipt-cardevent-development-split-next",
      receipt_digest: "e".repeat(64),
      partitions: {
        train: [recording.recording_id],
        validation: [],
        unassigned: [],
        test: [],
      },
      counts: { train: 1, validation: 0, unassigned: 0, test: 0 },
    };
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const path = String(input);
      if (path.endsWith("/preview")) {
        return Promise.resolve(
          new Response(JSON.stringify(preview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/apply")) {
        return Promise.resolve(
          new Response(JSON.stringify(applied), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedStatus), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(recording), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const user = userEvent.setup();
    await user.type(
      await screen.findByRole("textbox", { name: "Partition operator" }),
      "operator",
    );
    await user.click(
      screen.getByRole("button", { name: "Preview assignment" }),
    );
    expect(await screen.findByText("Affected group")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Confirm assignment to Train" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "receipt-cardevent-development-split-next",
    );
    expect(screen.getAllByText("Train").length).toBeGreaterThan(0);
  });

  it("starts an analysis and links existing analyses for a recording", async () => {
    const recording = {
      recording_id: "recording-1",
      source_asset_id: "source-1",
      video_id: "video-1",
      session_id: "550e8400-e29b-41d4-a716-446655440034",
      state: "complete",
      source_sha256: "a".repeat(64),
      received_at: "2026-09-01T07:20:46Z",
      round_id: "round-1",
      card_event_review_state: "completed",
      card_event_event_count: 2,
      development_partition: "train",
      evidence_package_ids: ["550e8400-e29b-41d4-a716-446655440035"],
      analyses: [
        {
          analysis_id: ANALYSIS_ID,
          recording_id: "recording-1",
          round_id: "round-1",
          state: "complete",
          total_evidence_packages: 1,
          completed_evidence_packages: 1,
          result_status: "resolved",
          error: null,
          created_at: "2026-09-01T07:21:00Z",
          started_at: "2026-09-01T07:21:00Z",
          completed_at: "2026-09-01T07:21:01Z",
        },
      ],
      can_start_analysis: true,
      analysis_blocker: null,
    };
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedStatus), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ recordings: [recording] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Open timeline")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open recording" }),
    ).toHaveAttribute("href", "/recordings/recording-1");
    expect(
      screen.getByText("CardEvent review").parentElement,
    ).toHaveTextContent("Completed · 2 events");
    expect(
      screen.getByText("Development partition").parentElement,
    ).toHaveTextContent("Train");
    expect(screen.getByText("Result:")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Start new analysis" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/recordings/recording-1/round-analyses",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      `Analysis ${resolvedStatus.analysis_id} was queued.`,
    );
  });

  it("loads a resolved analysis into synchronized timeline columns", async () => {
    window.history.pushState(
      {},
      "",
      `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}`,
    );
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path === `/v1/recordings/${RECORDING_ID}`) {
        return Promise.resolve(
          new Response(JSON.stringify(recordingDetailWithAnalysis), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/timeline")) {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedTimeline), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(resolvedStatus), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Evidence" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Selected analysis")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Clear selection" }),
    ).toHaveAttribute("href", `/recordings/${RECORDING_ID}`);
    expect(
      screen.getByRole("heading", { name: "Table observation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Reconstruction hypothesis" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Diagnostic comparison")).not.toBeInTheDocument();
    const counterfactualGroups = screen.getAllByRole("group", {
      name: "Counterfactual",
    });
    expect(counterfactualGroups).toHaveLength(2);
    expect(
      screen
        .getByRole("option", { name: /observation-001/ })
        .querySelector("fieldset"),
    ).toBe(counterfactualGroups[0]);
    expect(screen.getAllByText("Diamonds Jack").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Hearts Ten").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: "Hypothesis comparison" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Focused decisions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Jump to observation-001" }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Jump to observation-001" }),
    );
    expect(window.location.search).toBe(
      `?analysis=${ANALYSIS_ID}&hypothesis=1&row=observation-001`,
    );
    await user.click(screen.getByText("Score details for hypothesis rank 1"));
    expect(screen.getByText("Action contributions")).toBeInTheDocument();
    await user.click(screen.getByText("Engine diagnostics"));
    expect(screen.getByText("Search Nodes")).toBeInTheDocument();
    await user.click(screen.getByText("Raw table-observation JSON"));
    expect(document.body.textContent).toContain(
      '"observation_id": "observation-001"',
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Hypothesis" }),
      "2",
    );
    expect(window.location.search).toBe(
      `?analysis=${ANALYSIS_ID}&hypothesis=2&row=observation-001`,
    );
    expect(
      screen.getByRole("progressbar", { name: "Diamonds Jack confidence" }),
    ).toHaveValue(0.75);
    expect(screen.getAllByText("Clubs Nine").length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("keeps rendering when a timeline response omits the recording descriptor", async () => {
    const timelineWithoutRecordingDescriptor = {
      ...resolvedTimeline,
    } as Record<string, unknown>;
    delete timelineWithoutRecordingDescriptor.recording_video;
    stubTimeline(
      timelineWithoutRecordingDescriptor as unknown as RoundAnalysisTimeline,
      resolvedStatus,
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Full recording" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Full recording for event 1")).toHaveAttribute(
      "src",
      "/v1/repository-bundles/recording-0033/video",
    );
  });

  it.each([
    ["active", "analyzing_evidence", "Analyzing Evidence"],
    ["failed", "failed", "Failed"],
  ] as const)(
    "nests %s analysis status in the recording workspace",
    async (_name, state, expectedStatus) => {
      const analysisId = `${ANALYSIS_ID}-${state}`;
      const detail = {
        ...recordingDetailWithAnalysis,
        analyses: [
          {
            ...recordingDetailWithAnalysis.analyses[0],
            analysis_id: analysisId,
            state,
            completed_evidence_packages: state === "failed" ? 1 : 0,
            result_status: null,
            error: state === "failed" ? "Fixture analysis failed." : null,
          },
        ],
      };
      const status: RoundAnalysisStatus = {
        ...resolvedStatus,
        analysis_id: analysisId,
        state,
        completed_evidence_packages: state === "failed" ? 1 : 0,
        result: null,
        error: state === "failed" ? "Fixture analysis failed." : null,
      };
      window.history.pushState(
        {},
        "",
        `/recordings/${RECORDING_ID}?analysis=${analysisId}`,
      );
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>((input) => {
          const path = String(input);
          const response =
            path === `/v1/recordings/${RECORDING_ID}` ? detail : status;
          return Promise.resolve(
            new Response(JSON.stringify(response), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }),
      );

      render(<App />);

      expect(await screen.findByText(expectedStatus)).toBeInTheDocument();
      expect(screen.getByText("Selected analysis")).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Clear selection" }),
      ).toHaveAttribute("href", `/recordings/${RECORDING_ID}`);
    },
  );

  it("opens event details with media and card probabilities", async () => {
    stubTimeline(resolvedTimeline, resolvedStatus);
    render(<App />);

    const user = userEvent.setup();
    const frameButton = await screen.findByRole("button", {
      name: "Open event details for event 1",
    });
    await user.click(frameButton);

    const dialog = screen.getByRole("dialog", { name: /Event 1/ });
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Enlarged evidence frame for event 1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Evidence video snippet for event 1"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Full recording for event 1 in detail view"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Diamonds Jack")).toBeInTheDocument();
    expect(within(dialog).getByText("75%")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close event details" }),
    ).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(frameButton).toHaveFocus();
  });

  it("shows the full recording and seeks to the selected event time", async () => {
    stubTimeline(resolvedTimeline, resolvedStatus);
    render(<App />);

    const video = await screen.findByLabelText("Full recording for event 1");
    Object.defineProperty(video, "duration", {
      configurable: true,
      value: 2,
    });
    Object.defineProperty(video, "readyState", {
      configurable: true,
      value: 1,
    });

    video.dispatchEvent(new Event("loadedmetadata"));

    expect(video).toHaveAttribute("src", resolvedTimeline.recording_video.url);
    expect((video as HTMLVideoElement).currentTime).toBe(1);

    const user = userEvent.setup();
    await user.click(screen.getByRole("option", { name: /observation-002/ }));

    expect(screen.getByLabelText("Full recording for event 2")).toBe(video);
    await waitFor(() =>
      expect((video as HTMLVideoElement).currentTime).toBe(2),
    );
  });

  it("allows a direct card identity correction outside analyzer candidates", async () => {
    const fetchMock = stubTimelineWithCounterfactual(
      resolvedTimeline,
      resolvedStatus,
      changedCounterfactualResponse,
    );
    render(<App />);

    const user = userEvent.setup();
    const identitySelect = await screen.findByRole("combobox", {
      name: "Correct classification for observation-002-card-01",
    });
    await user.selectOptions(identitySelect, "CLUBS_TEN");

    expect(identitySelect).toHaveValue("CLUBS_TEN");
    expect(
      screen.getByText(/Derived input uses Clubs Ten/),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Run counterfactual" }),
    );

    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall).toBeDefined();
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      card_identity_overrides: [
        {
          observation_id: "observation-002",
          observed_card_id: "observation-002-card-01",
          card: "CLUBS_TEN",
        },
      ],
    });
  });

  it("runs a changed counterfactual and marks baseline differences", async () => {
    stubTimelineWithCounterfactual(
      resolvedTimeline,
      resolvedStatus,
      changedCounterfactualResponse,
    );
    render(<App />);

    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Evidence" });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Exclude observation observation-001",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Run counterfactual" }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Baseline versus counterfactual",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Changed observations and cards"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Changed card plays" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Changed").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "Search truncation makes this comparison incomplete. The displayed hypotheses may not include every legal sequence.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 baseline decision.*0 counterfactual decision/),
    ).toBeInTheDocument();
  });

  it("keeps pending counterfactual changes reachable in a fixed status bar", async () => {
    const fetchMock = stubTimelineWithCounterfactual(
      resolvedTimeline,
      resolvedStatus,
      changedCounterfactualResponse,
    );
    render(<App />);

    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Evidence" });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Exclude observation observation-001",
      }),
    );

    const statusBar = screen.getByRole("status", {
      name: "Counterfactual status",
    });
    expect(statusBar).toHaveTextContent("1 unapplied counterfactual change");
    const applyButton = screen.getByRole("button", { name: "Apply now" });
    expect(applyButton).toBeInTheDocument();

    await user.click(applyButton);

    expect(
      await screen.findByRole("heading", {
        name: "Baseline versus counterfactual",
      }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
    ).toBe(true);
  });

  it("shows stable no-change states for an unchanged counterfactual", async () => {
    stubTimelineWithCounterfactual(
      resolvedTimeline,
      resolvedStatus,
      unchangedCounterfactualResponse,
    );
    render(<App />);

    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Evidence" });
    await user.click(
      screen.getByRole("checkbox", {
        name: "Exclude observation observation-001",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Run counterfactual" }),
    );

    await screen.findByRole("heading", {
      name: "Baseline versus counterfactual",
    });
    expect(screen.getByText("No card-play changes.")).toBeInTheDocument();
    expect(
      screen.getByText("No selected or ignored source actions changed."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No focused decisions changed."),
    ).toBeInTheDocument();
  });

  it("restores deep-linked row and hypothesis and moves rows with the keyboard", async () => {
    window.history.pushState(
      {},
      "",
      `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}&row=observation-002&hypothesis=2`,
    );
    const fetchMock = vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input) === `/v1/recordings/${RECORDING_ID}`
              ? recordingDetailWithAnalysis
              : String(input).endsWith("/timeline")
                ? resolvedTimeline
                : resolvedStatus,
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const user = userEvent.setup();
    const selectedRow = await screen.findByRole("option", {
      name: /observation-002/,
      selected: true,
    });
    expect(selectedRow).toHaveAccessibleName(/observation-002/);
    expect(screen.getByRole("combobox", { name: "Hypothesis" })).toHaveValue(
      "2",
    );
    expect(screen.getAllByText("Clubs Nine").length).toBeGreaterThan(0);

    await user.click(selectedRow);
    await user.keyboard("{ArrowUp}");

    expect(window.location.search).toBe(
      `?analysis=${ANALYSIS_ID}&hypothesis=2&row=observation-001`,
    );
    expect(
      screen.getByRole("option", { name: /observation-001/, selected: true }),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "ambiguous",
      ambiguousTimeline,
      ambiguousStatus,
      "This result is ambiguous",
    ],
    ["incomplete", incompleteTimeline, incompleteStatus, "Incomplete input"],
    ["impossible", impossibleTimeline, impossibleStatus, "Impossible input"],
  ] as const)(
    "explains the %s terminal result without implying ground truth",
    async (_name, timeline, status, expectedText) => {
      stubTimeline(timeline, status);
      render(<App />);

      await waitFor(() =>
        expect(screen.getByText(new RegExp(expectedText))).toBeInTheDocument(),
      );
      expect(screen.getByText("Engine diagnostics")).toBeInTheDocument();
      expect(
        screen.getByText("Raw reconstruction-result JSON"),
      ).toBeInTheDocument();
      if (timeline.hypotheses.length === 0) {
        expect(screen.getByText("No retained hypotheses.")).toBeInTheDocument();
      }
    },
  );
});

function stubTimeline(
  timeline: RoundAnalysisTimeline,
  status: RoundAnalysisStatus,
) {
  window.history.pushState(
    {},
    "",
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}`,
  );
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input) => {
      const path = String(input);
      const response =
        path === `/v1/recordings/${RECORDING_ID}`
          ? recordingDetailWithAnalysis
          : path.endsWith("/timeline")
            ? timeline
            : status;
      return Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

function stubTimelineWithCounterfactual(
  timeline: RoundAnalysisTimeline,
  status: RoundAnalysisStatus,
  counterfactual: typeof changedCounterfactualResponse,
): ReturnType<typeof vi.fn<typeof fetch>> {
  window.history.pushState(
    {},
    "",
    `/recordings/${RECORDING_ID}?analysis=${ANALYSIS_ID}`,
  );
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    if (init?.method === "POST") {
      return Promise.resolve(
        new Response(JSON.stringify(counterfactual), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.resolve(
      new Response(
        JSON.stringify(
          String(input) === `/v1/recordings/${RECORDING_ID}`
            ? recordingDetailWithAnalysis
            : String(input).endsWith("/timeline")
              ? timeline
              : status,
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
