import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import type { PipelineWorkspaceStage } from "../api/pipelineContracts";
import { resetWorkingAreaFrameCacheForTests } from "../workingArea/workingAreaFrame";

const stage = {
  key: "table_observations",
  runs: [],
} as unknown as PipelineWorkspaceStage;

function renderWorkbench(
  props: ComponentProps<typeof PipelineObservationWorkbench>,
) {
  return render(
    <>
      <div data-observation-inspector-slot />
      <div data-observation-rail-slot />
      <PipelineObservationWorkbench {...props} />
    </>,
  );
}

describe("PipelineObservationWorkbench", () => {
  beforeEach(() => {
    resetWorkingAreaFrameCacheForTests();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:observation");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        if (String(input).includes("/pipeline/derived-views/"))
          return Promise.resolve(
            new Response("frame", {
              status: 200,
              headers: {
                "X-DokoDetector-Source-Sha256": "a".repeat(64),
                "X-DokoDetector-Frame-Index": "0",
                "X-DokoDetector-Frame-Width": "640",
                "X-DokoDetector-Frame-Height": "480",
                "X-DokoDetector-Requested-Time-Us": "0",
                "X-DokoDetector-Frame-Time-Us": "0",
                ETag: `"${"b".repeat(64)}"`,
              },
            }),
          );
        return Promise.resolve(
          new Response(
            JSON.stringify({
              node_id: "observations",
              name: "Assembly",
              content_type: "table_observations",
              head_revision_id: "r1",
              revision_id: "r1",
              parent_revision_id: null,
              metadata: {},
              created_at: "2026-11-05T10:00:00Z",
              content: {
                schema_version: "table-observation-data/v1",
                observations: [
                  {
                    observation_id: "obs-1",
                    observed_at_ms: 123,
                    status: "observed",
                    cards: [{ card_id: "card-1" }],
                  },
                ],
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("opens the exact node revision and keeps an invalid deep link unselected", async () => {
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage,
      selectedItemId: "missing-observation",
      selectedTimeUs: null,
      selectedNode: { nodeId: "observations", revisionId: "r1" },
      onSelectNodeObservation: vi.fn(),
    });
    expect(
      await screen.findByText(
        "The selected observation is missing from this exact revision.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /obs-1/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText(/Revision r1/)).toBeInTheDocument();
  });

  it("keeps failed and partial processing attempts in the inspector", async () => {
    const failedStage = {
      key: "table_observations",
      runs: [
        {
          run_id: "failed-run",
          status: "failed",
          input_revision_ids: ["events-r1", "visible-r1"],
          failure: { message: "Source frame unavailable." },
          state: { items: [] },
        },
        {
          run_id: "partial-run",
          status: "partial",
          input_revision_ids: [],
          failure: null,
          state: { items: [] },
        },
      ],
    } as unknown as PipelineWorkspaceStage;
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage: failedStage,
      selectedItemId: null,
      selectedTimeUs: null,
      selectedNode: null,
    });

    const failures = await screen.findByLabelText(
      "Failed observation attempts",
    );
    expect(
      within(failures).getByText(/failed-run.*Source frame unavailable/),
    ).toBeInTheDocument();
    expect(
      within(failures).getByText(/partial-run · partial · inputs none/),
    ).toBeInTheDocument();
  });

  it("selects an interval without inventing an exact source frame time", async () => {
    const onSelect = vi.fn();
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage,
      selectedItemId: null,
      selectedTimeUs: null,
      selectedNode: { nodeId: "observations", revisionId: "r1" },
      onSelectNodeObservation: onSelect,
    });
    fireEvent.click(await screen.findByRole("button", { name: /obs-1/ }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith("obs-1", null));
  });

  it("distinguishes an observed zero-card result from insufficient evidence", async () => {
    const observation = (status: string) => ({
      observation_id: "obs-empty",
      observed_at_ms: 123,
      status,
      capabilities: ["identity_candidates"],
      cards: [],
    });
    const renderObservation = async (status: string) => {
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>((input) => {
          if (String(input).includes("/pipeline/derived-views/"))
            return Promise.resolve(
              new Response("frame", {
                status: 200,
                headers: {
                  "X-DokoDetector-Source-Sha256": "a".repeat(64),
                  "X-DokoDetector-Frame-Index": "0",
                  "X-DokoDetector-Frame-Width": "640",
                  "X-DokoDetector-Frame-Height": "480",
                  "X-DokoDetector-Requested-Time-Us": "123000",
                  "X-DokoDetector-Frame-Time-Us": "123000",
                  ETag: `"${"b".repeat(64)}"`,
                },
              }),
            );
          return Promise.resolve(
            new Response(
              JSON.stringify({
                node_id: "observations",
                name: "Assembly",
                content_type: "table_observations",
                head_revision_id: "r1",
                revision_id: "r1",
                parent_revision_id: null,
                metadata: {},
                created_at: "2026-11-05T10:00:00Z",
                content: {
                  schema_version: "table-observation-data/v1",
                  observations: [observation(status)],
                },
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          );
        }),
      );
      renderWorkbench({
        recordingId: "recording-1",
        sourceSha256: "a".repeat(64),
        stage,
        selectedItemId: "obs-empty",
        selectedTimeUs: 123_000,
        selectedNode: { nodeId: "observations", revisionId: "r1" },
      });
      return await screen.findByLabelText("Selected table observation");
    };

    const observed = await renderObservation("observed");
    expect(
      within(observed).getByText("This observation has zero observed cards."),
    ).toBeInTheDocument();
    expect(within(observed).getByText("observed")).toBeInTheDocument();
    cleanup();

    const insufficient = await renderObservation("insufficient_evidence");
    expect(
      within(insufficient).getByText(
        "This observation had insufficient evidence; zero cards is not reported.",
      ),
    ).toBeInTheDocument();
    expect(
      within(insufficient).getByText("insufficient_evidence"),
    ).toBeInTheDocument();
    cleanup();

    const failed = await renderObservation("failed");
    expect(
      within(failed).getByText(
        "This observation failed; zero cards is not reported.",
      ),
    ).toBeInTheDocument();
    expect(within(failed).getByText("failed")).toBeInTheDocument();
  });

  it("draws a card only when its linked exact source frame matches", async () => {
    const frameIdentity = {
      schema_version: "exact-event-frame/v1",
      source_video_sha256: "a".repeat(64),
      requested_time_us: 123_000,
      frame_index: 4,
      presentation_timestamp_us: 123_000,
      width: 640,
      height: 480,
      decoder_version: "fixture",
      transform_version: "fixture",
      output_encoding: "jpeg",
      content_type: "image/jpeg",
      image_sha256: "b".repeat(64),
      policy: "exact-event-frame/v1",
    };
    const observationRevision = {
      node_id: "observations",
      name: "Assembly",
      content_type: "table_observations",
      head_revision_id: "r1",
      revision_id: "r1",
      parent_revision_id: null,
      metadata: {},
      created_at: "2026-11-05T10:00:00Z",
      content: {
        schema_version: "table-observation-data/v1",
        observations: [
          {
            observation_id: "obs-1",
            observed_at_ms: 123,
            status: "observed",
            capabilities: ["identity_candidates"],
            cards: [{ observed_card_id: "card-1" }],
            diagnostics: { assembly: { event_id: "event-1" } },
          },
        ],
      },
    };
    const visibleRevision = {
      node_id: "visible",
      name: "Visible source",
      content_type: "visible_cards",
      head_revision_id: "v1",
      revision_id: "v1",
      parent_revision_id: null,
      metadata: {},
      created_at: "2026-11-05T10:00:00Z",
      content: {
        schema_version: "visible-card-data/v1",
        outcomes: [
          {
            event_id: "event-1",
            frame_identity: { ...frameIdentity },
            status: "detected",
            candidates: [
              {
                card_id: "card-1",
                geometry: {
                  polygons: [
                    [
                      { x: 100, y: 100 },
                      { x: 300, y: 100 },
                      { x: 300, y: 300 },
                    ],
                  ],
                },
              },
            ],
          },
        ],
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input) => {
        if (String(input).includes("/pipeline/derived-views/"))
          return Promise.resolve(
            new Response(new Blob(["still frame"]), {
              status: 200,
              headers: {
                "X-DokoDetector-Source-Sha256": "a".repeat(64),
                "X-DokoDetector-Frame-Index": "4",
                "X-DokoDetector-Frame-Width": "640",
                "X-DokoDetector-Frame-Height": "480",
                "X-DokoDetector-Requested-Time-Us": "123000",
                "X-DokoDetector-Frame-Time-Us": "123000",
                ETag: `"${"b".repeat(64)}"`,
              },
            }),
          );
        const body = String(input).includes("/nodes/visible")
          ? visibleRevision
          : observationRevision;
        return Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }),
    );
    const lineageGraph = {
      nodes: [
        {
          node_id: "observations",
          content_type: "table_observations",
          name: "Observations",
        },
        {
          node_id: "visible",
          content_type: "visible_cards",
          name: "Visible source",
        },
        {
          node_id: "visible-two",
          content_type: "visible_cards",
          name: "Alternate source",
        },
      ],
      edges: [
        {
          kind: "produced",
          from: ["run", "run-1"],
          to: ["revision", "observations", "r1"],
        },
        {
          kind: "used",
          from: ["revision", "visible", "v1"],
          to: ["run", "run-1"],
        },
        {
          kind: "used",
          from: ["revision", "visible-two", "v1"],
          to: ["run", "run-1"],
        },
      ],
      revisions: [],
    };
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage,
      selectedItemId: "obs-1",
      selectedTimeUs: 123_000,
      selectedNode: { nodeId: "observations", revisionId: "r1" },
      lineageGraph: lineageGraph as never,
    });
    const polygon = await screen.findByLabelText("Observed card source");
    expect(polygon).toBeInTheDocument();
    expect(await screen.findByLabelText("Spatial source")).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Alternate source/ }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Spatial source"), {
      target: { value: "visible-two:v1" },
    });
    expect(screen.getByLabelText("Spatial source")).toHaveValue(
      "visible-two:v1",
    );
    expect(screen.getByLabelText("Observed card source")).toBeInTheDocument();
    fireEvent.click(polygon);
    expect(polygon).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "card-1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    cleanup();
    observationRevision.content.observations[0].cards[0].observed_card_id =
      "unlinked-card";
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage,
      selectedItemId: "obs-1",
      selectedTimeUs: 123_000,
      selectedNode: { nodeId: "observations", revisionId: "r1" },
      lineageGraph: lineageGraph as never,
    });
    expect(
      screen.queryByLabelText("Observed card source"),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText(
        "Some observed cards have no exact spatial match. No geometry was drawn for those cards.",
      ),
    ).toBeInTheDocument();
    cleanup();

    observationRevision.content.observations[0].cards[0].observed_card_id =
      "card-1";
    visibleRevision.content.outcomes[0].frame_identity =
      null as unknown as typeof frameIdentity;
    const onSelect = vi.fn();
    renderWorkbench({
      recordingId: "recording-1",
      sourceSha256: "a".repeat(64),
      stage,
      selectedItemId: "obs-1",
      selectedTimeUs: 123_000,
      selectedNode: { nodeId: "observations", revisionId: "r1" },
      lineageGraph: lineageGraph as never,
      onSelectNodeObservation: onSelect,
    });
    expect(
      await screen.findByText(
        "This observation is interval evidence only. It has no exact source frame geometry.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Observed card source"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /obs-1/ }));
    expect(onSelect).toHaveBeenCalledWith("obs-1", null);
  });
});
