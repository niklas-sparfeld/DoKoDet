import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import {
  pipelineRevision,
  pipelineStage,
} from "../test/recordingPipelineFixtures";
import { LegacyEventParentLink } from "./LegacyEventParentLink";

describe("legacy event parent link", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens one exact converted parent after matching its saved digest", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          event_sets: [
            {
              set_id: "events-a",
              version: "v1",
              provenance: {
                source_metadata: { legacy_revision_id: "legacy-event-a" },
                source_content_sha256: "a".repeat(64),
              },
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ content_sha256: "a".repeat(64) }),
      });
    vi.stubGlobal("fetch", fetchMock);
    const stage = pipelineStage("visible_cards", {
      selected_completed_reference: { node_id: "cards", revision_id: "rev1" },
      input_options: [
        pipelineRevision("rev1", {
          node_id: "cards",
          node_revision_id: "rev1",
          content_type: "visible_cards",
          coverage: { event_revision_id: "legacy-event-a" },
        }),
      ],
    });

    render(<LegacyEventParentLink recordingId="rec-1" stage={stage} />);

    const link = await screen.findByRole("link", {
      name: "Open exact event parent events-a@v1",
    });
    expect(link).toHaveAttribute(
      "href",
      "/recordings/rec-1/event-sets?set=events-a&version=v1",
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports duplicate provenance without choosing a version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          event_sets: [
            {
              set_id: "events-a",
              version: "v1",
              provenance: {
                source_metadata: { legacy_revision_id: "legacy-event-a" },
              },
            },
            {
              set_id: "events-b",
              version: "v2",
              provenance: {
                source_metadata: { legacy_revision_id: "legacy-event-a" },
              },
            },
          ],
        }),
      }),
    );
    const stage = pipelineStage("visible_cards", {
      selected_generated: { node_id: "cards", revision_id: "rev1" },
      input_options: [
        pipelineRevision("rev1", {
          node_id: "cards",
          node_revision_id: "rev1",
          content_type: "visible_cards",
          coverage: { event_revision_id: "legacy-event-a" },
        }),
      ],
    });

    render(<LegacyEventParentLink recordingId="rec-1" stage={stage} />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Exact event parent is ambiguous.",
      ),
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("uses a direct saved event-set reference before legacy provenance", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content_sha256: "c".repeat(64) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const stage = pipelineStage("visible_cards", {
      selected_completed_reference: { node_id: "cards", revision_id: "rev1" },
      input_options: [
        pipelineRevision("rev1", {
          node_id: "cards",
          node_revision_id: "rev1",
          content_type: "visible_cards",
          coverage: {
            event_revision_id: "legacy-event-a",
            event_set_ref: {
              set_id: "events-direct",
              version: "v2",
              content_sha256: "c".repeat(64),
            },
          },
        }),
      ],
    });

    render(<LegacyEventParentLink recordingId="rec-1" stage={stage} />);

    expect(
      await screen.findByRole("link", {
        name: "Open exact event parent events-direct@v2",
      }),
    ).toHaveAttribute(
      "href",
      "/recordings/rec-1/event-sets?set=events-direct&version=v2",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("events-direct/versions/v2");
  });

  it("reports missing provenance for a selected output", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ event_sets: [] }),
      }),
    );
    const stage = pipelineStage("visible_cards", {
      selected_completed_reference: { node_id: "cards", revision_id: "rev1" },
      input_options: [
        pipelineRevision("rev1", {
          node_id: "cards",
          node_revision_id: "rev1",
          content_type: "visible_cards",
          coverage: {},
        }),
      ],
    });

    render(<LegacyEventParentLink recordingId="rec-1" stage={stage} />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Exact event parent provenance is missing.",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
