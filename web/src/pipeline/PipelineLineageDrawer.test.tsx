import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipelineLineageDrawer } from "./PipelineLineageDrawer";
import type {
  PipelineLineageGraph,
  PipelineLineageSelection,
} from "./pipelineLineageSelection";

const graph: PipelineLineageGraph = {
  schema_version: "pipeline-lineage-graph/v1",
  nodes: [
    {
      node_id: "event-original",
      name: "First pass",
      content_type: "events",
      source: { recording_id: "recording-1" },
      head_revision_id: "event-r2",
    },
    {
      node_id: "event-copy",
      name: "Corrected pass",
      content_type: "events",
      source: { recording_id: "recording-1" },
      head_revision_id: "event-copy-r1",
    },
    {
      node_id: "observations",
      name: "Assembly",
      content_type: "table_observations",
      source: { recording_id: "recording-1" },
      head_revision_id: "observation-r1",
    },
  ],
  revisions: [
    revision("event-original", "event-r1", "2026-11-01T10:00:00Z"),
    revision("event-original", "event-r2", "2026-11-02T10:00:00Z"),
    revision("event-copy", "event-copy-r1", "2026-11-03T10:00:00Z"),
    revision("observations", "observation-r1", "2026-11-04T10:00:00Z"),
  ],
  runs: [
    { run_id: "assemble-run" },
    { run_id: "analysis-run", run_kind: "analysis", status: "complete" },
  ],
  artifacts: [],
  edges: [
    {
      kind: "revised",
      from: ["revision", "event-original", "event-r1"],
      to: ["revision", "event-original", "event-r2"],
    },
    {
      kind: "copied",
      from: ["revision", "event-original", "event-r2"],
      to: ["revision", "event-copy", "event-copy-r1"],
    },
    {
      kind: "used",
      role: "event_timeline",
      from: ["revision", "event-original", "event-r2"],
      to: ["run", "assemble-run"],
    },
    {
      kind: "used",
      role: "visible_cards",
      from: ["revision", "cards", "cards-r4"],
      to: ["run", "assemble-run"],
    },
    {
      kind: "produced",
      role: "output",
      from: ["run", "assemble-run"],
      to: ["revision", "observations", "observation-r1"],
    },
    {
      kind: "used",
      role: "observations",
      from: ["revision", "observations", "observation-r1"],
      to: ["run", "analysis-run"],
    },
    {
      kind: "used",
      role: "events",
      from: ["revision", "event-original", "event-r2"],
      to: ["run", "analysis-run"],
    },
  ],
};

describe("PipelineLineageDrawer", () => {
  it("aligns data sets, labels copy and process sources, and selects an exact revision", async () => {
    const onSelect = vi.fn();
    const onCopy = vi.fn().mockResolvedValue(undefined);
    const selection: PipelineLineageSelection = {
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        visible_cards: { node_id: "cards", revision_id: "cards-r4" },
      },
    };
    render(
      <PipelineLineageDrawer
        id="lineage"
        graph={graph}
        graphError={null}
        selection={selection}
        onSelect={onSelect}
        onCopy={onCopy}
      />,
    );

    const eventColumn = screen.getByRole("region", {
      name: "Events lineage",
    });
    expect(within(eventColumn).getByText("First pass")).toBeInTheDocument();
    expect(within(eventColumn).getByText("Corrected pass")).toBeInTheDocument();
    expect(screen.getByText("Copy source")).toBeInTheDocument();
    expect(screen.getAllByText("Processor input")).toHaveLength(2);
    expect(screen.getByText("event_timeline")).toBeInTheDocument();
    expect(screen.getByText("visible_cards")).toBeInTheDocument();
    expect(screen.getByText("observations")).toBeInTheDocument();
    expect(screen.getByText("Analysis analysis-run")).toBeInTheDocument();
    expect(screen.getAllByText("Analysis input")).toHaveLength(2);

    fireEvent.click(
      within(eventColumn).getByRole("button", { name: "r event-r1" }),
    );
    expect(onSelect).toHaveBeenCalledWith({
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        visible_cards: { node_id: "cards", revision_id: "cards-r4" },
        events: { node_id: "event-original", revision_id: "event-r1" },
      },
    });
    fireEvent.click(
      within(eventColumn).getByRole("button", { name: "r event-copy-r1" }),
    );
    expect(onSelect).toHaveBeenLastCalledWith({
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        visible_cards: { node_id: "cards", revision_id: "cards-r4" },
        events: { node_id: "event-copy", revision_id: "event-copy-r1" },
      },
    });
    await act(async () => {
      fireEvent.click(
        within(eventColumn).getAllByRole("button", { name: "Create copy" })[0],
      );
    });
    expect(onCopy).toHaveBeenCalledWith("events", "event-original", "event-r2");
  });

  it("keeps revision history collapsed until requested", () => {
    render(
      <PipelineLineageDrawer
        id="lineage"
        graph={graph}
        graphError={null}
        selection={null}
        onSelect={vi.fn()}
        onCopy={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    const history = screen.getByText("History (2)").closest("details");
    expect(history).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("History (2)"));
    expect(history).toHaveAttribute("open");
  });

  it("selects an exact analysis from the lineage drawer", () => {
    const onSelectAnalysis = vi.fn();
    render(
      <PipelineLineageDrawer
        id="lineage"
        graph={graph}
        graphError={null}
        selection={null}
        onSelect={vi.fn()}
        onCopy={vi.fn().mockResolvedValue(undefined)}
        onSelectAnalysis={onSelectAnalysis}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Analysis analysis-run" }),
    );
    expect(onSelectAnalysis).toHaveBeenCalledWith("analysis-run");
  });
});

function revision(nodeId: string, revisionId: string, createdAt: string) {
  return {
    node_id: nodeId,
    revision_id: revisionId,
    content_sha256: "abcdef0123456789",
    created_at: createdAt,
  };
}
