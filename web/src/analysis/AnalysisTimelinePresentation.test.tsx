import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ResolvedTimeline } from "./AnalysisTimelinePresentation";
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
  });

  afterEach(() => {
    window.history.pushState({}, "", "/recordings/recording-0033");
  });

  it("keeps row and hypothesis selection synchronized with the URL", async () => {
    const user = userEvent.setup();

    render(<ResolvedTimeline timeline={resolvedTimeline} />);

    expect(screen.getByText("Selected observation-001")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next row →" }));

    expect(window.location.search).toBe("?hypothesis=1&row=observation-002");
    expect(screen.getByText("Selected observation-002")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Hypothesis"), "2");

    expect(window.location.search).toBe("?hypothesis=2&row=observation-002");
    expect(
      screen.getByText("Selected hypothesis").parentElement,
    ).toHaveTextContent("Rank 2");
  });

  it("opens evidence details with the source recording and evidence media", async () => {
    const user = userEvent.setup();

    render(<ResolvedTimeline timeline={resolvedTimeline} />);

    await user.click(
      screen.getByRole("button", { name: "Open event details for event 1" }),
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Event 1 · 1.000 s");
    expect(dialog).toHaveTextContent("Full recording");
    expect(dialog).toHaveTextContent("Evidence video");
    expect(
      within(dialog).getByRole("button", { name: "Close event details" }),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: "Close event details" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps counterfactual inputs attached to the selected observation", async () => {
    const user = userEvent.setup();

    render(<ResolvedTimeline timeline={resolvedTimeline} />);

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
