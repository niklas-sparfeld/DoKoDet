import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { useCallback, useEffect, useState } from "react";

import type {
  PipelineComparisonResponse,
  PipelineWorkspaceStage,
} from "../api/client";
import {
  readPipelineUrlState,
  type PipelineUrlState,
} from "./recordingPipelineUrl";
import { ComparisonInspectorControls, ComparisonView } from "./ComparisonView";

const RECORDING_ID = "comparison-recording";
const OUTCOMES: PipelineComparisonResponse["items"][number]["outcome"][] = [
  "match",
  "miss",
  "extra",
  "disagreement",
  "failure",
  "empty",
  "not_reviewed",
  "unpaired_input",
];

function stage(
  key: PipelineComparisonResponse["content_type"],
): PipelineWorkspaceStage {
  const runs = [
    run("run-new", ["input-1"], "2026-09-06T12:00:00Z"),
    run("run-old", ["input-1"], "2026-09-06T11:00:00Z"),
    run("run-third", ["input-1"], "2026-09-06T10:00:00Z"),
  ];
  return {
    key,
    processor_key: `${key}-processor`,
    processor_type: `${key}-processor`,
    output_content_type: key,
    has_maintained_reference: true,
    state: "complete",
    input_options: [
      {
        revision_id: "reference-1",
        content_type: key === "events" ? "events" : key,
        origin: "manual",
        completion_state: "complete",
        coverage_state: "complete",
        display_label: "Reviewed reference",
        content_sha256: "a".repeat(64),
        input_revision_ids: [],
        producer: {},
        coverage: {},
        created_at: "2026-09-06T10:00:00Z",
      },
    ],
    selection_revision: 1,
    selected_generated_revision_id: "run-new-output",
    selected_completed_reference_revision_id: "reference-1",
    runs,
    analyses: [],
    compatible_input_sets: [],
    reference: {
      state: "complete",
      draft_revision: 1,
      selected_completion: "reference-1",
      source_revision_id: "input-1",
      coverage: { kind: "full" },
      coverage_state: "complete",
      affected_count: 0,
      updated_at: "2026-09-06T10:00:00Z",
    },
    can_run: false,
    run_blockers: [],
    can_review: false,
    review_blockers: [],
    comparable_run_ids: runs.map((item) => item.run_id),
  };
}

function run(
  runId: string,
  inputRevisionIds: string[],
  createdAt: string,
): PipelineWorkspaceStage["runs"][number] {
  return {
    run_id: runId,
    status: "complete",
    attempt: 1,
    request: {},
    state: {},
    input_revision_ids: inputRevisionIds,
    implementation: { name: "fixture", version: runId },
    model: null,
    configuration: {},
    extraction_policy: {},
    crop_policy: null,
    output_revision_ids: [`${runId}-output`],
    created_at: createdAt,
    started_at: createdAt,
    completed_at: createdAt,
    updated_at: createdAt,
    progress: { completed: 1, total: 1 },
    failure: null,
    failed_item_count: 0,
  };
}

function comparison(
  contentType: PipelineComparisonResponse["content_type"],
  mode: PipelineComparisonResponse["mode"] = "paired_processor",
): PipelineComparisonResponse {
  const policy =
    contentType === "events"
      ? {
          policy_id: "event-timing/v1",
          kind: "event_timing" as const,
          anchor: "start_us" as const,
          tolerance_us: 50_000,
        }
      : {
          policy_id: `${contentType}-geometry/v1`,
          kind:
            contentType === "visible_cards"
              ? ("visible_card_geometry" as const)
              : ("visual_identity_geometry" as const),
          iou_threshold: 0.5,
          derived_box_policy: "bounding_box" as const,
        };
  return {
    schema_version: "pipeline-comparison/v1",
    comparison_id: `comparison-${contentType}`,
    recording_id: RECORDING_ID,
    content_type: contentType,
    mode,
    algorithm_version: "pipeline-comparison.v2",
    left: side("run-new", "run-new-output"),
    right: side("run-old", "run-old-output"),
    reference: {
      revision_id: "reference-1",
      input_revision_ids: ["input-1"],
      content_sha256: "a".repeat(64),
      origin: "manual",
    },
    scope: {
      reviewed: [{ start_us: 0, end_us: 2_000_000 }],
      common_covered: [{ start_us: 0, end_us: 2_000_000 }],
      left_only: [],
      right_only: [],
      reviewed_frame_identities: [],
      common_frame_identities: [],
      left_only_frame_identities: [],
      right_only_frame_identities: [],
    },
    matching_policy: policy,
    counts: {
      left: counts(),
      right: counts(),
    },
    metrics: {
      left: metrics(),
      right: metrics(),
    },
    paired_delta: mode === "paired_processor" ? metrics() : null,
    items: OUTCOMES.map((outcome, index) => ({
      item_id: `${contentType}-item-${index}`,
      side: index % 2 === 0 ? "left" : "right",
      outcome,
      source_time_us: (index + 1) * 100_000,
      event_type:
        contentType === "events"
          ? "card_played"
          : contentType === "visible_cards"
            ? "visible_card"
            : "visual_identity",
      reference_event_id: null,
      run_event_id: null,
      reference_event: null,
      run_event: null,
      delta_us: null,
      source_links: {
        derived_view: `/api/recordings/${RECORDING_ID}/pipeline/derived-views/exact-event/${(index + 1) * 100_000}`,
      },
      frame_identity: null,
      reference_card_id: `reference-card-${index}`,
      run_card_id: `run-card-${index}`,
      reference_card: null,
      run_card: null,
      iou: contentType === "events" ? null : 0.5,
      reference_identity:
        contentType === "visual_identities" ? "CLUBS_NINE" : null,
      run_identity: contentType === "visual_identities" ? "SPADES_ACE" : null,
      reference_candidates:
        contentType === "visual_identities"
          ? [{ identity: "CLUBS_NINE" }]
          : null,
      run_candidates:
        contentType === "visual_identities"
          ? [{ identity: "SPADES_ACE" }]
          : null,
    })),
  };
}

function side(
  runId: string,
  revisionId: string,
): PipelineComparisonResponse["left"] {
  return {
    run_id: runId,
    revision_id: revisionId,
    status: "complete",
    input_revision_ids: ["input-1"],
    content_sha256: "b".repeat(64),
    implementation: { name: "fixture", version: "v1" },
    model: null,
    configuration: {},
    extraction_policy: {},
    failure: null,
  };
}

function counts(): PipelineComparisonResponse["counts"]["left"] {
  return {
    reference_events: 1,
    run_events: 1,
    matches: 1,
    misses: 1,
    extras: 1,
    not_reviewed: 1,
    unpaired_input: 1,
    failures: 1,
  };
}

function metrics(): PipelineComparisonResponse["metrics"]["left"] {
  return {
    precision: 0.5,
    recall: 0.5,
    f1: 0.5,
    mean_error_us: 1_000,
    max_error_us: 2_000,
  };
}

function Harness({ stageValue }: { stageValue: PipelineWorkspaceStage }) {
  const [urlState, setUrlState] = useState<PipelineUrlState>(() =>
    readPipelineUrlState(window.location.search),
  );
  useEffect(() => {
    const update = () =>
      setUrlState(readPipelineUrlState(window.location.search));
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const [comparison, setComparison] =
    useState<PipelineComparisonResponse | null>(null);
  const [railItems, setRailItems] = useState<
    Array<{ itemId: string; timeUs: number | null }>
  >([]);
  const navigate = useCallback((path: string, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);
  return (
    <>
      <ComparisonInspectorControls
        recordingId={RECORDING_ID}
        stage={stageValue}
        urlState={urlState}
        onNavigate={navigate}
        comparison={comparison}
      />
      <ComparisonView
        recordingId={RECORDING_ID}
        stage={stageValue}
        durationUs={2_000_000}
        urlState={urlState}
        onNavigate={navigate}
        onComparisonChange={setComparison}
        onRailItemsChange={(items) =>
          setRailItems(
            items.map((item) => ({
              itemId: item.itemId,
              timeUs: item.timeRange?.startUs ?? null,
            })),
          )
        }
      />
      {railItems.map((item) => (
        <button
          key={item.itemId}
          type="button"
          aria-label={`Inspect ${item.itemId}`}
          onClick={() => {
            const params = new URLSearchParams(window.location.search);
            params.set("item", item.itemId);
            if (item.timeUs !== null) params.set("t_us", String(item.timeUs));
            navigate(`${window.location.pathname}?${params}`);
          }}
        >
          {item.itemId}
        </button>
      ))}
    </>
  );
}

describe("ComparisonView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it.each(["events", "visible_cards", "visual_identities"] as const)(
    "renders all %s outcomes and source actions",
    async (contentType) => {
      const response = comparison(contentType);
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>(() =>
          Promise.resolve(
            new Response(JSON.stringify(response), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          ),
        ),
      );
      const user = userEvent.setup();
      render(<Harness stageValue={stage(contentType)} />);

      await waitFor(() => {
        expect(window.location.search).toContain("left=run-new");
        expect(window.location.search).toContain("right=run-old");
      });
      expect(await screen.findByText("Matching policy")).toBeInTheDocument();
      expect(
        screen.queryByText("Source-ordered outcomes"),
      ).not.toBeInTheDocument();

      await user.click(
        screen.getByRole("button", { name: `Inspect ${contentType}-item-0` }),
      );
      expect(
        screen.getByRole("link", { name: "Open derived frame" }),
      ).toHaveAttribute("href", response.items[0].source_links.derived_view);
      if (contentType === "visual_identities") {
        expect(
          screen.getByRole("link", { name: "Open identity crop" }),
        ).toHaveAttribute(
          "href",
          "/api/recordings/comparison-recording/pipeline/derived-views/identity-crops/run-new-output/run-card-0",
        );
      }
      expect(window.location.search).toContain("t_us=100000");
    },
  );

  it("does not claim paired quality for an upstream experiment", async () => {
    const response = comparison("events", "upstream_experiment");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(JSON.stringify(response), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    render(<Harness stageValue={stage("events")} />);

    expect(
      await screen.findByText(
        "No paired quality claim for an upstream experiment.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps inspector selectors available when comparison fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              detail: { message: "The comparison fixture failed." },
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            },
          ),
        ),
      ),
    );
    render(<Harness stageValue={stage("events")} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The comparison fixture failed.",
    );
    expect(
      screen.getByRole("combobox", { name: "Left terminal run" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Right terminal run" }),
    ).toBeInTheDocument();
  });

  it("updates only comparison URL selections and restores them with history", async () => {
    const response = comparison("events");
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Harness stageValue={stage("events")} />);

    await waitFor(() =>
      expect(window.location.search).toContain("left=run-new"),
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Left terminal run" }),
      "run-third",
    );
    await waitFor(() =>
      expect(window.location.search).toContain("left=run-third"),
    );
    expect(window.location.search).toContain("right=run-old");
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "PUT"),
    ).toBe(false);

    window.history.back();
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Left terminal run" }),
      ).toHaveValue("run-new"),
    );
  });
});
