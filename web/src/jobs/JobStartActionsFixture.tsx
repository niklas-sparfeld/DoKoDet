import { useState } from "react";
import { createRoot } from "react-dom/client";
import { PipelineLineageDrawer } from "../pipeline/PipelineLineageDrawer";
import type { PipelineLineageGraph } from "../pipeline/pipelineLineageSelection";
import { JobStateProvider } from "./JobState";
import { JobsDrawer } from "./JobsDrawer";
import { JobStartActions } from "./JobStartActions";
import "../index.css";
import "./jobs.css";

const graph: PipelineLineageGraph = {
  schema_version: "pipeline-lineage-graph/v1",
  nodes: [
    {
      node_id: "events-node",
      name: "Fixture events",
      content_type: "events",
      source: { recording_id: "fixture-recording" },
      head_revision_id: "events-r1",
    },
  ],
  revisions: [
    {
      node_id: "events-node",
      revision_id: "events-r1",
      content_sha256: "a".repeat(64),
      created_at: "2026-11-07T10:00:00Z",
    },
  ],
  runs: [],
  artifacts: [],
  edges: [],
};

function Fixture() {
  const [lineageOpen, setLineageOpen] = useState(false);
  return (
    <JobStateProvider>
      <JobsDrawer />
      <div
        style={{
          minHeight: "100dvh",
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(17rem, 22rem)",
        }}
      >
        <main aria-label="Workspace center" style={{ padding: "2rem" }}>
          <h1>Workspace center</h1>
          <p>Center remains available after the launch form closes.</p>
        </main>
        <aside
          style={{
            padding: "1rem",
            display: "grid",
            alignContent: "start",
            gap: "1rem",
          }}
        >
          <button
            type="button"
            aria-expanded={lineageOpen}
            aria-controls="fixture-lineage-drawer"
            onClick={() => setLineageOpen((open) => !open)}
          >
            {lineageOpen ? "Hide lineage" : "Show lineage"}
          </button>
          {lineageOpen ? (
            <PipelineLineageDrawer
              id="fixture-lineage-drawer"
              graph={graph}
              graphError={null}
              selection={null}
              onSelect={() => undefined}
              onCopy={async () => undefined}
            />
          ) : null}
          <JobStartActions
            actions={[
              {
                id: "fixture-action",
                label: "Run fixture action",
                description: "Opening this form does not start work.",
                expectedOutput: "One fresh fixture result.",
                sections: [
                  {
                    title: "Inputs",
                    content: (
                      <label>
                        Model
                        <input defaultValue="Fixture model" />
                      </label>
                    ),
                  },
                  {
                    title: "Options",
                    content: (
                      <div>
                        {Array.from({ length: 24 }, (_, index) => (
                          <p key={index}>Option {index + 1}</p>
                        ))}
                      </div>
                    ),
                  },
                ],
              },
            ]}
          />
        </aside>
      </div>
    </JobStateProvider>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
