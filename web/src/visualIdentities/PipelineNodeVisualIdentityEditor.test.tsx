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
        crop_input_provenance: {
          input_kind: "reviewed_visible_card",
          manifest_digest: "b".repeat(64),
          source_revision_id: "visible-r3",
          source_revision_digest: "c".repeat(64),
          source_node_id: "visible-node",
          source_node_revision_id: "visible-r3",
        },
        crop_identity: {
          status: "usable",
          image_sha256: "a".repeat(64),
          crop_policy: "oracle_visible_region",
        },
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

  it("includes the review policy for identity and data-set decisions", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisualIdentityEditor
        recordingId="recording-1"
        nodeId="identities"
        revisionId="r1"
        selectionItemId="card-1"
        selectionTimeUs={250_000}
        sourceSha256={"d".repeat(64)}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Accept identity" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(
      JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body)).evidence.policy,
    ).toBe("visual-identity-review/v1");
    fireEvent.click(screen.getByRole("button", { name: "Accept data set" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
    expect(
      JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body)).evidence.policy,
    ).toBe("visual-identity-review/v1");
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
        selectionTimeUs={250_000}
        sourceSha256={"d".repeat(64)}
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
    expect(body.content.outcomes[0]?.crop_input_provenance).toEqual(
      revision.content.outcomes[0]?.crop_input_provenance,
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

  it("shows frozen crop lineage and supports keyboard candidate classification", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(revision))
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisualIdentityEditor
        recordingId="recording-1"
        nodeId="identities"
        revisionId="r1"
        selectionItemId="card-1"
        selectionTimeUs={250_000}
        sourceSha256={"d".repeat(64)}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText("oracle_visible_region"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("visible-r3")).toHaveLength(2);
    const choices = screen.getByRole("region", {
      name: "Identity classification choices",
    });
    fireEvent.keyDown(choices, { key: "1" });
    const editor = screen.getByLabelText(
      "Identity outcome JSON",
    ) as HTMLTextAreaElement;
    expect(JSON.parse(editor.value).candidates).toEqual([
      { identity: "CLUBS_ACE", probability: 1 },
    ]);
  });

  it("does not reveal a previous crop when selection changes before the new crop loads", async () => {
    const second = {
      ...revision.content.outcomes[0]!,
      card_id: "card-2",
      frame_identity: { requested_time_us: 500_000, frame_index: 2 },
      crop_identity: {
        status: "usable",
        image_sha256: "e".repeat(64),
        crop_policy: "raw_rectangular",
      },
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          ...revision,
          content: {
            ...revision.content,
            outcomes: [...revision.content.outcomes, second],
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse([]));
    render(
      <PipelineNodeVisualIdentityEditor
        recordingId="recording-1"
        nodeId="identities"
        revisionId="r1"
        selectionItemId="card-1"
        selectionTimeUs={250_000}
        sourceSha256={"d".repeat(64)}
        onPositionChange={vi.fn()}
        onRevisionChange={vi.fn()}
      />,
    );
    const oldCrop = await screen.findByAltText(
      "Frozen processor input crop for card-1",
    );
    fireEvent.load(oldCrop);
    fireEvent.click(screen.getByRole("button", { name: /card-2/ }));
    const currentCrop = await screen.findByAltText(
      "Frozen processor input crop for card-2",
    );
    fireEvent.load(oldCrop);
    expect(currentCrop).not.toHaveStyle({ display: "block" });
  });
});
