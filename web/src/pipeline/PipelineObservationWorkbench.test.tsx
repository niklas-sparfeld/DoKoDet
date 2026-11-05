import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineObservationWorkbench } from "./PipelineObservationWorkbench";
import type { PipelineWorkspaceStage } from "../api/client";

const stage = {
  key: "table_observations",
  runs: [],
} as unknown as PipelineWorkspaceStage;

describe("PipelineObservationWorkbench", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
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
      ),
    );
  });

  it("opens the exact node revision and keeps an invalid deep link unselected", async () => {
    render(
      <PipelineObservationWorkbench
        recordingId="recording-1"
        stage={stage}
        selectedItemId="missing-observation"
        selectedNode={{ nodeId: "observations", revisionId: "r1" }}
        onSelectNodeObservation={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "The requested observation is not present in this revision. No other observation was selected.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /obs-1/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText(/Revision r1/)).toBeInTheDocument();
  });

  it("selects an observation by its exact item ID and source time", async () => {
    const onSelect = vi.fn();
    render(
      <PipelineObservationWorkbench
        recordingId="recording-1"
        stage={stage}
        selectedItemId={null}
        selectedNode={{ nodeId: "observations", revisionId: "r1" }}
        onSelectNodeObservation={onSelect}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /obs-1/ }));
    await waitFor(() =>
      expect(onSelect).toHaveBeenCalledWith("obs-1", 123_000),
    );
  });
});
