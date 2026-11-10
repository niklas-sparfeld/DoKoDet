import { render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import {
  pipelineRevision,
  pipelineStage,
} from "../test/recordingPipelineFixtures";
import { LegacyEventParentLink } from "./LegacyEventParentLink";

describe("legacy event parent link", () => {
  afterEach(() => vi.restoreAllMocks());

  it("hides the previous parent while a changed output lookup is pending", async () => {
    const outputResponse = (eventSetId: string) => ({
      ok: true,
      json: async () => ({
        event_sets: [
          {
            set_id: eventSetId,
            version: "v1",
            provenance: {
              source_metadata: { legacy_revision_id: `legacy-${eventSetId}` },
              source_content_sha256: "a".repeat(64),
            },
          },
        ],
      }),
    });
    const pendingList = deferred<{
      ok: boolean;
      json: () => Promise<{ event_sets: unknown[] }>;
    }>();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(outputResponse("events-a"))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ content_sha256: "a".repeat(64) }),
      })
      .mockReturnValueOnce(pendingList.promise)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ content_sha256: "a".repeat(64) }),
      });
    vi.stubGlobal("fetch", fetchMock);
    const firstStage = parentStage("legacy-events-a");
    const nextStage = parentStage("legacy-events-b");
    const { rerender } = render(
      <LegacyEventParentLink recordingId="rec-1" stage={firstStage} />,
    );

    expect(
      await screen.findByRole("link", {
        name: "Open exact event parent events-a@v1",
      }),
    ).toBeVisible();

    rerender(<LegacyEventParentLink recordingId="rec-1" stage={nextStage} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    pendingList.resolve(outputResponse("events-b"));
    expect(
      await screen.findByRole("link", {
        name: "Open exact event parent events-b@v1",
      }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: /events-a@v1/ })).toBeNull();
  });

  it("ignores a late parent response after switching recordings and outputs", async () => {
    const lateList = deferred<{
      ok: boolean;
      json: () => Promise<{ event_sets: unknown[] }>;
    }>();
    const currentList = deferred<{
      ok: boolean;
      json: () => Promise<{ event_sets: unknown[] }>;
    }>();
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/events-c/versions/v1"))
        return Promise.resolve({
          ok: true,
          json: async () => ({ content_sha256: "c".repeat(64) }),
        });
      if (url.includes("/rec-b/event-sets/"))
        return Promise.reject(new Error("The stale request is ignored."));
      if (url.endsWith("/rec-b/event-sets")) return lateList.promise;
      if (url.endsWith("/rec-c/event-sets")) return currentList.promise;
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(
      <LegacyEventParentLink
        recordingId="rec-b"
        stage={parentStage("legacy-b")}
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender(
      <LegacyEventParentLink
        recordingId="rec-c"
        stage={parentStage("legacy-c")}
      />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    lateList.resolve(parentList("events-b", "legacy-b", "b".repeat(64)));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/rec-b/event-sets"),
      ),
    );
    await Promise.resolve();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();

    currentList.resolve(parentList("events-c", "legacy-c", "c".repeat(64)));
    expect(
      await screen.findByRole("link", {
        name: "Open exact event parent events-c@v1",
      }),
    ).toHaveAttribute(
      "href",
      "/recordings/rec-c/event-sets?set=events-c&version=v1",
    );
    expect(screen.queryByRole("link", { name: /events-b@v1/ })).toBeNull();
  });

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

function parentStage(legacyRevisionId: string) {
  return pipelineStage("visible_cards", {
    selected_completed_reference: { node_id: "cards", revision_id: "rev1" },
    input_options: [
      pipelineRevision("rev1", {
        node_id: "cards",
        node_revision_id: "rev1",
        content_type: "visible_cards",
        coverage: { event_revision_id: legacyRevisionId },
      }),
    ],
  });
}

function parentList(
  setId: string,
  legacyRevisionId: string,
  contentSha256: string,
) {
  return {
    ok: true,
    json: async () => ({
      event_sets: [
        {
          set_id: setId,
          version: "v1",
          provenance: {
            source_metadata: { legacy_revision_id: legacyRevisionId },
            source_content_sha256: contentSha256,
          },
        },
      ],
    }),
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
