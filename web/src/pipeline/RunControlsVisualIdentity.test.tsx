import { afterEach, describe, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@testing-library/react";
import { option, runResponse, stage } from "./runControlsTestFixtures";
import { RunControls } from "./RunControls";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RunControls visual-identity launches and history", () => {
  it("uses polygon crop policies for visual identity runs", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
      selected_completed_reference_revision_id: "visible-reviewed",
      input_options: [
        {
          ...option("visible-generated"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
        {
          ...option("visible-reviewed"),
          content_type: "visible_cards",
          origin: "manual",
          producer: { kind: "human" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["node-revision-visible-generated"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
    });
    const identities = stage("visual_identities");

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      ).toBeEnabled(),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      "reviewed_virtual_card:node-revision-visible-reviewed",
    );
    expect(
      screen.queryByRole("option", { name: "Predicted visible region" }),
    ).not.toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Crop policy" }),
      "raw_rectangular",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST"),
      ).toBeDefined(),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "node-visible-reviewed",
          revision_id: "node-revision-visible-reviewed",
          revision_policy: "current_head",
        },
        crop_input_kind: "reviewed_virtual_card",
        crop_policy: {
          policy_id: "raw_rectangular",
          output_encoding: "ppm",
        },
      },
    });

    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      ).toBeEnabled(),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      "gemini_polygon:node-revision-visible-generated",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toHaveLength(2),
    );
    const postCalls = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCalls[1]?.[1]?.body))).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "node-visible-generated",
          revision_id: "node-revision-visible-generated",
          revision_policy: "current_head",
        },
        crop_input_kind: "gemini_polygon",
        configuration: { provider: "local" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });
  it("lists exact proposed scene revisions and requires a choice when several exist", async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      if (String(input).endsWith("/visual-identities/proposed-crop-inputs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              recording_id: "recording-run-controls",
              inputs: [
                {
                  node_id: "proposal-node-one",
                  revision_id: "proposal-one",
                  created_at: "2026-11-03T00:00:00Z",
                  proposal_data_digest: "a".repeat(64),
                  detector_revision_id: "detector-one",
                  calibration_revision_id: "calibration-one",
                  supported_frame_count: 2,
                  unsupported_frame_count: 1,
                },
                {
                  node_id: "proposal-node-two",
                  revision_id: "proposal-two",
                  created_at: "2026-11-04T00:00:00Z",
                  proposal_data_digest: "b".repeat(64),
                  detector_revision_id: "detector-two",
                  calibration_revision_id: "calibration-two",
                  supported_frame_count: 4,
                  unsupported_frame_count: 0,
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify(runResponse("identity-proposal")), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-proposal")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards");
    const identities = stage("visual_identities");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    expect(
      within(screen.getByRole("dialog")).getByText(
        /classification creates processor outcomes; a person reviews and accepts or rejects identities separately/i,
      ),
    ).toBeInTheDocument();
    const selector = screen.getByRole("combobox", {
      name: "Exact crop geometry revision",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /proposal-two/ }),
      ).toBeInTheDocument(),
    );
    expect(selector).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    ).toBeDisabled();
    await userEvent.selectOptions(
      selector,
      "proposed_virtual_cards:proposal-two",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const body = JSON.parse(
      String(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]
          ?.body,
      ),
    );
    expect(body).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "proposal-node-two",
          revision_id: "proposal-two",
          revision_policy: "historical",
        },
        crop_input_kind: "proposed_virtual_cards",
        configuration: { provider: "local" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
    expect(body.request.visible_card_revision_id).toBeUndefined();
    const postCalls = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(postCalls.map(([input]) => String(input))).toEqual([
      "/api/recordings/recording-run-controls/pipeline/visual-identities",
    ]);
  });
  it("invalidates a crop policy when the selected geometry source changes", async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-geometry")), {
          status: init?.method === "POST" ? 202 : 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      selected_completed_reference_revision_id: "visible-reviewed",
      input_options: [
        {
          ...option("visible-generated"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
        {
          ...option("visible-reviewed"),
          content_type: "visible_cards",
          origin: "manual",
          producer: { kind: "human" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["node-revision-visible-generated"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
    });
    const identities = stage("visual_identities");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      ).toBeEnabled(),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      "reviewed_virtual_card:node-revision-visible-reviewed",
    );
    expect(screen.getByRole("combobox", { name: "Crop policy" })).toHaveValue(
      "oracle_visible_region",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
      "gemini_polygon:node-revision-visible-generated",
    );
    expect(screen.getByRole("combobox", { name: "Crop policy" })).toHaveValue(
      "predicted_visible_region",
    );
    expect(
      screen.queryByRole("option", { name: "Reviewed visible region" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Classifier provider" }),
    ).toHaveValue("local");
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "node-visible-generated",
          revision_id: "node-revision-visible-generated",
        },
        crop_input_kind: "gemini_polygon",
        crop_policy: { policy_id: "predicted_visible_region" },
        configuration: { provider: "local" },
      },
    });
  });
  it("preselects one crop input and requires an explicit choice when several exist", async () => {
    const oneInput = stage("visible_cards", {
      input_options: [
        {
          ...option("gemini-only"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["gemini-only"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
    });
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-run-1")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const identities = stage("visual_identities");
    const { rerender } = render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[oneInput, identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    expect(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
    ).toHaveValue("gemini_polygon:node-revision-gemini-only");

    const twoInputs = stage("visible_cards", {
      input_options: [
        ...oneInput.input_options,
        {
          ...option("rfdetr-one"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "rfdetr-run" },
        },
      ],
      runs: [
        ...oneInput.runs,
        {
          run_id: "rfdetr-run",
          output_revision_ids: ["node-revision-rfdetr-one"],
          configuration: { provider: "local-rfdetr-segmentation" },
          request: { configuration: { provider: "local-rfdetr-segmentation" } },
        },
      ],
    });
    rerender(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[twoInputs, identities]}
        onRefresh={async () => undefined}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: "Exact crop geometry revision" }),
    ).toHaveValue("");
    expect(
      screen.getByRole("option", { name: /Generated · RF-DETR/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    ).toBeDisabled();
    await waitFor(() =>
      expect(
        screen.getByText(/multiple inputs require an explicit choice/i),
      ).toBeInTheDocument(),
    );
  });
  it("uses the local classifier with the generated RF-DETR crop input", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(runResponse("identity-local")), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const visible = stage("visible_cards", {
      input_options: [
        {
          ...option("rfdetr-one"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "rfdetr-run" },
        },
      ],
      runs: [
        {
          run_id: "rfdetr-run",
          output_revision_ids: ["node-revision-rfdetr-one"],
          configuration: { provider: "local-rfdetr-segmentation" },
          request: { configuration: { provider: "local-rfdetr-segmentation" } },
        },
      ],
    });
    const identities = stage("visual_identities");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Classifier provider" }),
      "local",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Start classify visual identities" }),
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.find(([, init]) => init?.method === "POST"),
      ).toBeDefined(),
    );
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      request: {
        input_node_ref: {
          node_id: "node-rfdetr-one",
          revision_id: "node-revision-rfdetr-one",
          revision_policy: "current_head",
        },
        crop_input_kind: "rfdetr_segment",
        configuration: { provider: "local" },
        crop_policy: {
          policy_id: "predicted_visible_region",
          output_encoding: "ppm",
        },
      },
    });
  });
  it("explains why reviewed virtual-card input is unavailable", async () => {
    const visible = stage("visible_cards", {
      input_options: [
        {
          ...option("generated-visible"),
          content_type: "visible_cards",
          producer: { kind: "processor", run_id: "gemini-run" },
        },
      ],
      runs: [
        {
          run_id: "gemini-run",
          output_revision_ids: ["generated-visible"],
          configuration: { provider: "gemini" },
          request: { configuration: { provider: "gemini" } },
        },
      ],
    });
    const identities = stage("visual_identities");
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[visible, identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Classify visual identities…" }),
    );
    expect(
      screen.getByText(
        /Reviewed virtual-card input unavailable: complete a maintained visible-card reference\./,
      ),
    ).toBeInTheDocument();
  });
  it("keeps the exact crop-input lineage visible for a historical run", async () => {
    const identityRun = {
      run_id: "identity-history",
      status: "complete",
      attempt: 1,
      request: {
        crop_input: {
          input_kind: "reviewed_virtual_card",
          source_revision_id: "visible-review-17",
          items: Array.from({ length: 12 }, (_, index) => ({
            card_id: `card-${index}`,
          })),
        },
        crop_policy: { policy_id: "oracle_visible_region" },
      },
      state: {},
      input_revision_ids: ["visible-review-17"],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: {},
      crop_policy: { policy_id: "oracle_visible_region" },
      output_revision_ids: [],
      created_at: "2026-09-25T00:00:00Z",
      started_at: null,
      completed_at: null,
      updated_at: "2026-09-25T00:00:00Z",
      progress: { completed: 12, total: 12 },
      failure: null,
      failed_item_count: 0,
    };
    const identities = stage("visual_identities", { runs: [identityRun] });
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={identities}
        stages={[stage("visible_cards"), identities]}
        onRefresh={async () => undefined}
      />,
    );
    await userEvent.click(screen.getByText("Retained runs and actual inputs"));
    expect(
      screen.getByText(
        "Reviewed virtual cards · source visible-review-17 · 12 crop inputs · policy oracle_visible_region",
      ),
    ).toBeInTheDocument();
  });
  it("does not offer retired RF-DETR cascade variants", () => {
    const events = stage("events", {
      selected_generated_revision_id: "events-generated",
    });
    const visible = stage("visible_cards", {
      selected_generated_revision_id: "visible-generated",
    });

    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={visible}
        stages={[events, visible]}
        onRefresh={async () => undefined}
      />,
    );

    expect(screen.queryByRole("option", { name: /cascade/i })).toBeNull();
  });
  it("keeps legacy failed history without inventing a job link", async () => {
    const retainedRun = {
      run_id: "failed-run",
      status: "failed" as const,
      attempt: 1,
      request: {
        run_id: "failed-run",
        input_revision_ids: [],
        implementation: { name: "fixture", version: "v1" },
        model: null,
        configuration: {},
        extraction_policy: { policy_id: "exact-event/v1" },
        crop_policy: null,
      },
      state: {},
      input_revision_ids: [],
      implementation: { name: "fixture", version: "v1" },
      model: null,
      configuration: {},
      extraction_policy: { policy_id: "exact-event/v1" },
      crop_policy: null,
      output_revision_ids: [],
      created_at: "2026-09-06T00:00:00Z",
      started_at: "2026-09-06T00:00:00Z",
      completed_at: "2026-09-06T00:00:01Z",
      updated_at: "2026-09-06T00:00:01Z",
      progress: { completed: 1, total: 2 },
      failure: { code: "provider_failed", message: "fixture failed" },
      failed_item_count: 0,
    };
    render(
      <RunControls
        recordingId="recording-run-controls"
        stage={stage("events", { runs: [retainedRun] })}
        stages={[stage("events", { runs: [retainedRun] })]}
        onRefresh={async () => undefined}
      />,
    );

    const history = screen.getByText("Retained runs and actual inputs");
    await userEvent.click(history);
    expect(
      within(screen.getByRole("list")).queryByRole("link", {
        name: "View job",
      }),
    ).toBeNull();
  });
});
