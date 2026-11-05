import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PipelineNodeVirtualSceneEditor } from "./PipelineNodeVirtualSceneEditor";

describe("PipelineNodeVirtualSceneEditor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("explains when an imported frame has no recorded geometry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) =>
        String(input).endsWith("/reviews")
          ? new Response("[]", { status: 200 })
          : new Response(
              JSON.stringify({
                node_id: "scene-node",
                name: "Imported scenes",
                content_type: "virtual_scenes",
                head_revision_id: "revision-1",
                revision_id: "revision-1",
                parent_revision_id: null,
                content: {
                  schema_version: "virtual-scene-data/v1",
                  frames: [
                    {
                      frame_id: "frame-1",
                      frame_identity: {},
                      calibration: {
                        revision_id: "cal-1",
                        digest: "a".repeat(64),
                      },
                      scene: null,
                      pile_regions: [],
                      ignore_regions: [],
                    },
                  ],
                },
                metadata: {
                  legacy_scenes: {
                    "frame-1": {
                      geometry_unavailable: true,
                      review: {
                        card_states: [{ card_id: "card-1", state: "rejected" }],
                        completion: {
                          state: "unusable",
                          reason: "Frame unusable",
                        },
                      },
                    },
                  },
                },
                created_at: "2026-11-05T00:00:00Z",
              }),
              { status: 200 },
            ),
      ),
    );
    render(
      <PipelineNodeVirtualSceneEditor
        recordingId="recording-1"
        nodeId="scene-node"
        revisionId="revision-1"
        selectionItemId="frame-1"
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        /Geometry was not available in the retained draft/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("card-1 · rejected")).toBeInTheDocument();
    expect(screen.getByText("Frame unusable")).toBeInTheDocument();
  });

  it("edits the selected scene revision and selects the protected copy", async () => {
    const content = {
      schema_version: "virtual-scene-data/v1",
      frames: [
        {
          frame_id: "frame-1",
          frame_identity: {
            requested_time_us: 1_200_000,
            width: 640,
            height: 480,
          },
          calibration: { revision_id: "cal-r4", digest: "a".repeat(64) },
          scene: {
            source_frame_id: "frame-1",
            calibration_revision_id: "cal-r4",
            calibration_digest: "a".repeat(64),
            poses: [
              { card_id: "card-1", center: [10, 20], rotation_degrees: 0 },
            ],
            stacking_order: { card_ids: ["card-1"] },
          },
          pile_regions: [],
          ignore_regions: [],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/reviews")) return new Response("[]", { status: 200 });
      if (url.endsWith("/revisions/revision-1"))
        return new Response(
          JSON.stringify({
            node_id: "scene-node",
            name: "Scene A",
            content_type: "virtual_scenes",
            head_revision_id: "revision-1",
            revision_id: "revision-1",
            parent_revision_id: null,
            content,
            metadata: {},
            created_at: "2026-11-05T00:00:00Z",
          }),
          { status: 200 },
        );
      if (url.endsWith("/edit")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          expected_revision_id: "revision-1",
          content: { frames: [{ calibration: { revision_id: "cal-r4" } }] },
        });
        return new Response(
          JSON.stringify({
            node_id: "scene-copy",
            revision_id: "copy-r1",
            copied: true,
            name: "Scene A copy",
          }),
          { status: 200 },
        );
      }
      return new Response("video", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onRevisionChange = vi.fn();
    render(
      <PipelineNodeVirtualSceneEditor
        recordingId="recording-1"
        nodeId="scene-node"
        revisionId="revision-1"
        selectionItemId="frame-1"
        onPositionChange={vi.fn()}
        onRevisionChange={onRevisionChange}
      />,
    );

    expect(
      await screen.findByText(/Calibration revision cal-r4/),
    ).toBeInTheDocument();
    const sceneJson = JSON.parse(
      (
        screen.getByRole("textbox", {
          name: "Scene JSON",
        }) as HTMLTextAreaElement
      ).value,
    );
    expect(sceneJson).toMatchObject({ calibration_revision_id: "cal-r4" });
    fireEvent.change(screen.getByRole("textbox", { name: "Scene JSON" }), {
      target: {
        value: JSON.stringify({
          ...sceneJson,
          poses: [{ ...sceneJson.poses[0], rotation_degrees: 15 }],
        }),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save scene" }));

    await waitFor(() =>
      expect(onRevisionChange).toHaveBeenCalledWith(
        "scene-node",
        "revision-1",
        "scene-copy",
        "copy-r1",
        "frame-1",
        1_200_000,
      ),
    );
    expect(
      await screen.findByText(/The original remains available in lineage/),
    ).toBeInTheDocument();
  });
});
