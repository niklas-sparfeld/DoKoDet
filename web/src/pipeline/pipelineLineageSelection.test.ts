import { describe, expect, it } from "vitest";

import {
  decodeLineageSelection,
  encodeLineageSelection,
  resolveLineageCandidates,
  validateLineageSelection,
  type PipelineLineageGraph,
  type PipelineLineageSelection,
} from "./pipelineLineageSelection";

const graph: PipelineLineageGraph = {
  schema_version: "pipeline-lineage-graph/v1",
  nodes: [
    {
      node_id: "events-a",
      name: "A",
      content_type: "events",
      source: {},
      head_revision_id: "e1",
    },
    {
      node_id: "events-b",
      name: "B",
      content_type: "events",
      source: {},
      head_revision_id: "e2",
    },
    {
      node_id: "visible-a",
      name: "A",
      content_type: "visible_cards",
      source: {},
      head_revision_id: "v1",
    },
    {
      node_id: "visible-b",
      name: "B",
      content_type: "visible_cards",
      source: {},
      head_revision_id: "v2",
    },
    {
      node_id: "identity-a",
      name: "A",
      content_type: "visual_identities",
      source: {},
      head_revision_id: "i1",
    },
  ],
  revisions: [
    {
      node_id: "events-a",
      revision_id: "e1",
      content_sha256: "a",
      created_at: "now",
    },
    {
      node_id: "events-b",
      revision_id: "e2",
      content_sha256: "b",
      created_at: "now",
    },
    {
      node_id: "visible-a",
      revision_id: "v1",
      content_sha256: "c",
      created_at: "now",
    },
    {
      node_id: "visible-a",
      revision_id: "v2-history",
      content_sha256: "f",
      created_at: "then",
    },
    {
      node_id: "visible-b",
      revision_id: "v2",
      content_sha256: "d",
      created_at: "now",
    },
    {
      node_id: "identity-a",
      revision_id: "i1",
      content_sha256: "e",
      created_at: "now",
    },
  ],
  runs: [],
  artifacts: [],
  edges: [
    {
      kind: "used",
      from: ["revision", "events-a", "e1"],
      to: ["run", "run-multi"],
    },
    {
      kind: "used",
      from: ["revision", "events-b", "e2"],
      to: ["run", "run-multi"],
    },
    {
      kind: "produced",
      from: ["run", "run-multi"],
      to: ["revision", "visible-a", "v1"],
    },
    {
      kind: "used",
      from: ["revision", "events-a", "e1"],
      to: ["run", "run-alt"],
    },
    {
      kind: "produced",
      from: ["run", "run-alt"],
      to: ["revision", "visible-b", "v2"],
    },
    {
      kind: "used",
      from: ["revision", "visible-a", "v1"],
      to: ["run", "identity-run"],
    },
    {
      kind: "produced",
      from: ["run", "identity-run"],
      to: ["revision", "identity-a", "i1"],
    },
    {
      kind: "revised",
      from: ["revision", "visible-a", "v1"],
      to: ["revision", "visible-a", "v2-history"],
    },
  ],
};

describe("pipeline lineage selection", () => {
  it("round-trips exact historical selections in a URL value", () => {
    const selection: PipelineLineageSelection = {
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        events: { node_id: "events-a", revision_id: "e1" },
        visible_cards: { node_id: "visible-a", revision_id: "v1" },
      },
    };

    expect(decodeLineageSelection(encodeLineageSelection(selection))).toEqual(
      selection,
    );
    expect(decodeLineageSelection("{bad json")).toBeNull();
  });

  it("keeps invalid explicit revisions invalid instead of choosing a replacement", () => {
    const stale: PipelineLineageSelection = {
      schema_version: "pipeline-lineage-selection/v1",
      selected: {
        visible_cards: { node_id: "visible-a", revision_id: "deleted" },
      },
    };

    expect(validateLineageSelection(stale, graph)).toEqual([
      "visible_cards:visible-a:deleted",
    ]);
  });

  it("reports a unique descendant and supports ancestor navigation", () => {
    expect(
      resolveLineageCandidates(
        graph,
        { node_id: "visible-a", revision_id: "v1" },
        "visual_identities",
        "descendants",
      ),
    ).toEqual({
      state: "unique",
      candidates: [{ node_id: "identity-a", revision_id: "i1" }],
    });
    expect(
      resolveLineageCandidates(
        graph,
        { node_id: "identity-a", revision_id: "i1" },
        "visible_cards",
        "ancestors",
      ),
    ).toEqual({
      state: "unique",
      candidates: [{ node_id: "visible-a", revision_id: "v1" }],
    });
  });

  it("does not guess when alternative runs produce multiple descendants", () => {
    expect(
      resolveLineageCandidates(
        graph,
        { node_id: "events-a", revision_id: "e1" },
        "visible_cards",
        "descendants",
      ),
    ).toEqual({
      state: "ambiguous",
      candidates: [
        { node_id: "visible-a", revision_id: "v1" },
        { node_id: "visible-a", revision_id: "v2-history" },
        { node_id: "visible-b", revision_id: "v2" },
      ],
    });
  });

  it("returns an empty step when no related revision exists", () => {
    expect(
      resolveLineageCandidates(
        graph,
        { node_id: "events-b", revision_id: "e2" },
        "table_observations",
        "descendants",
      ),
    ).toEqual({ state: "empty", candidates: [] });
  });
});
