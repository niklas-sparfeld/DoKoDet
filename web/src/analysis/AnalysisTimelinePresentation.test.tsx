import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResolvedTimeline } from "./AnalysisTimelinePresentation";
import { JobStateProvider } from "../jobs/JobState";
import type { RoundAnalysisTimeline } from "../api/analysisContracts";
import {
  buildDisplayRows,
  formatCardIdentity,
  formatDiagnosticValue,
  formatIdentifier,
  formatScore,
  formatTrickProgress,
} from "./analysisFormatting";
import { resolvedTimeline } from "../test/roundAnalysisFixture";

describe("analysis timeline presentation", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/recordings/recording-0033");
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              items: [],
              next_cursor: null,
              groups: [],
              queue_revision: 1,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
      ),
    );
  });

  afterEach(() => {
    window.history.pushState({}, "", "/recordings/recording-0033");
    vi.unstubAllGlobals();
  });

  function renderTimeline(timeline: RoundAnalysisTimeline) {
    return render(
      <JobStateProvider>
        <ResolvedTimeline timeline={timeline} />
      </JobStateProvider>,
    );
  }

  it("keeps row and hypothesis selection synchronized with the URL", async () => {
    const user = userEvent.setup();

    renderTimeline(resolvedTimeline);

    expect(screen.getByText("Selected observation-001")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next row →" }));

    expect(window.location.search).toBe(
      "?hypothesis=1&row=observation-002&t_us=2000000",
    );
    expect(screen.getByText("Selected observation-002")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Hypothesis"), "2");

    expect(window.location.search).toBe(
      "?t_us=2000000&hypothesis=2&row=observation-002",
    );
    expect(
      screen.getByText("Selected hypothesis").parentElement,
    ).toHaveTextContent("Rank 2");
  });

  it("selects exact evidence time and leaves inferred play time unchanged", async () => {
    const user = userEvent.setup();

    const timeline = {
      ...resolvedTimeline,
      inferred_plays: [
        {
          play_index: 1,
          player: "player-01",
          card: "CLUBS_NINE",
          position: "before" as const,
          before_observation_id: null,
          after_observation_id: "observation-001",
        },
      ],
    };
    renderTimeline(timeline);
    await user.click(
      screen.getByRole("button", {
        name: /Evidence · observation-002/,
      }),
    );
    expect(window.location.search).toContain("t_us=2000000");
    await user.click(
      screen.getByRole("button", { name: /Inferred play .* time unknown/ }),
    );
    expect(window.location.search).toContain("row=inferred-1");
    expect(window.location.search).toContain("t_us=2000000");
    expect(screen.queryByRole("video")).not.toBeInTheDocument();
  });

  it("restores the selected row and hypothesis from the URL", () => {
    window.history.pushState(
      {},
      "",
      "/recordings/recording-0033?row=observation-002&hypothesis=2&t_us=2000000",
    );

    renderTimeline(resolvedTimeline);

    expect(screen.getByText("Selected observation-002")).toBeInTheDocument();
    expect(screen.getByLabelText("Hypothesis")).toHaveValue("2");
    expect(
      screen.getByRole("button", { name: /Evidence · observation-002/ }),
    ).toHaveAttribute("aria-current", "true");
  });

  it("keeps counterfactual inputs attached to the selected observation", async () => {
    const user = userEvent.setup();

    renderTimeline(resolvedTimeline);

    const correction = screen.getByRole("combobox", {
      name: "Correct classification for observation-001-card-01",
    });
    await user.selectOptions(correction, "CLUBS_NINE");

    expect(correction).toHaveValue("CLUBS_NINE");
    expect(
      screen.getByText("1 unapplied counterfactual change"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Derived input uses Clubs Nine/),
    ).toBeInTheDocument();
  });

  it("shows pile footprints separately from cards and labels pile-only evidence", () => {
    const firstRow = resolvedTimeline.rows[0]!;
    const pileTimeline = {
      ...resolvedTimeline,
      rows: [
        {
          ...firstRow,
          table_observation: {
            ...firstRow.table_observation,
            schema_version: "table-observation/v2" as const,
            cards: [],
            piles: [
              {
                pile_id: "pile-01",
                geometry: {
                  kind: "pile-region/v1" as const,
                  polygons: [
                    [
                      { x: 100, y: 200 },
                      { x: 300, y: 200 },
                      { x: 200, y: 400 },
                    ],
                  ],
                },
                normalization: {
                  width: 1920,
                  height: 1080,
                  policy_id: "full-frame-0-1000/v1" as const,
                },
                source_candidates: [],
                grouped_candidates: [],
                grouped_card_states: [],
                grouped_scene_decision: null,
                origin: "reviewed" as const,
                confidence: null,
                model_lineage: null,
              },
            ],
          },
        },
        ...resolvedTimeline.rows.slice(1),
      ],
    };

    renderTimeline(pileTimeline);

    expect(
      screen.getByText(
        "No observed cards; pile evidence is listed separately.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "Observed piles" }).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("pile-01").length).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("img", {
        name: "Full-frame footprint for pile pile-01",
      }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "Location only; contents and card count are not inferred.",
      ).length,
    ).toBeGreaterThan(0);
  });
});

describe("analysis formatting and data readers", () => {
  it("formats identifiers, scores, diagnostics, and trick progress", () => {
    expect(formatCardIdentity("DIAMONDS_JACK")).toBe("Diamonds Jack");
    expect(formatIdentifier("search_truncated")).toBe("Search Truncated");
    expect(formatScore(-1.386294361)).toBe("-1.386");
    expect(formatDiagnosticValue({ search_nodes: 4 })).toContain(
      '"search_nodes": 4',
    );
    expect(formatTrickProgress(resolvedTimeline.hypotheses[0], undefined)).toBe(
      "1 tricks · no play selected",
    );
  });

  it("builds a stable display sequence from evidence rows", () => {
    const rows = buildDisplayRows(resolvedTimeline.rows, []);

    expect(rows.map((row) => row.id)).toEqual([
      "observation-001",
      "observation-002",
    ]);
    expect(rows[0]?.kind).toBe("evidence");
  });
});
