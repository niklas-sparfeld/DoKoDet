import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineNodeVisualIdentityEditor } from "./PipelineNodeVisualIdentityEditor";

vi.mock("../profile/profile", () => ({
  useProfileName: () => "Review Person",
}));

const revision = {
  node_id: "identities",
  name: "Classifier output",
  content_type: "visual_identities",
  head_revision_id: "r1",
  revision_id: "r1",
  parent_revision_id: null,
  metadata: {},
  created_at: "2026-11-05T10:00:00Z",
  content: {
    schema_version: "visual-identity-data/v1",
    outcomes: [
      {
        card_id: "card-1",
        frame_identity: { requested_time_us: 250_000, frame_index: 1 },
        geometry: { x: 1 },
        crop_identity: { status: "usable", image_sha256: "a".repeat(64) },
        candidates: [{ identity: "CLUBS_ACE", probability: 0.8 }],
        status: "classified",
      },
    ],
  },
};
const jsonResponse = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

describe("PipelineNodeVisualIdentityEditor", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn().mockReturnValue("stable-key"),
    });
    vi.stubGlobal("fetch", vi.fn());
  });

  it("edits a classification without changing its crop source and selects the protected copy", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse({
          node_id: "copy-1",
          revision_id: "r2",
          copied: true,
          name: "Classifier output copy",
        }),
      );
    const onRevisionChange = vi.fn();
    render(
      <PipelineNodeVisualIdentityEditor
        recordingId="recording-1"
        nodeId="identities"
        revisionId="r1"
        selectionItemId="card-1"
        onPositionChange={vi.fn()}
        onRevisionChange={onRevisionChange}
      />,
    );
    const editor = await screen.findByLabelText("Identity outcome JSON");
    const edited = JSON.parse((editor as HTMLTextAreaElement).value) as Record<
      string,
      unknown
    >;
    edited.candidates = [{ identity: "HEARTS_ACE", probability: 1 }];
    fireEvent.change(editor, {
      target: { value: JSON.stringify(edited, null, 2) },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save identity correction" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const body = JSON.parse(
      (fetchMock.mock.calls[2]?.[1] as RequestInit).body as string,
    ) as { content: { outcomes: Array<Record<string, unknown>> } };
    expect(body.content.outcomes[0]?.candidates).toEqual([
      { identity: "HEARTS_ACE", probability: 1 },
    ]);
    expect(body.content.outcomes[0]?.crop_identity).toEqual(
      revision.content.outcomes[0]?.crop_identity,
    );
    expect(onRevisionChange).toHaveBeenCalledWith(
      "identities",
      "r1",
      "copy-1",
      "r2",
      "card-1",
      250_000,
    );
  });
});
