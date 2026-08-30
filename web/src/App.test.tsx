import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import {
  ANALYSIS_ID,
  ambiguousStatus,
  ambiguousTimeline,
  impossibleStatus,
  impossibleTimeline,
  incompleteStatus,
  incompleteTimeline,
  resolvedStatus,
  resolvedTimeline,
} from "./test/roundAnalysisFixture";
import type { RoundAnalysisStatus, RoundAnalysisTimeline } from "./api/client";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the frontend foundation shell", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Round analysis timeline" }),
    ).toBeInTheDocument();
  });

  it("loads a resolved analysis into synchronized timeline columns", async () => {
    window.history.pushState({}, "", `/round-analyses/${ANALYSIS_ID}`);
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path.endsWith("/timeline")) {
        return Promise.resolve(
          new Response(JSON.stringify(resolvedTimeline), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(resolvedStatus), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(screen.getByText("Loading analysis…")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Evidence" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("heading", { name: "Table observation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Reconstruction hypothesis" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Diamonds Jack")).toBeInTheDocument();
    expect(screen.getByText("Hearts Ten")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Hypothesis comparison" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Focused decisions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Jump to observation-001" }),
    ).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Jump to observation-001" }),
    );
    expect(window.location.search).toBe("?hypothesis=1&row=observation-001");
    await user.click(screen.getByText("Score details for hypothesis rank 1"));
    expect(screen.getByText("Action contributions")).toBeInTheDocument();
    await user.click(screen.getByText("Engine diagnostics"));
    expect(screen.getByText("Search Nodes")).toBeInTheDocument();
    await user.click(screen.getByText("Raw table-observation JSON"));
    expect(document.body.textContent).toContain(
      '"observation_id": "observation-001"',
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Hypothesis" }),
      "2",
    );
    expect(window.location.search).toBe("?hypothesis=2&row=observation-001");
    expect(
      screen.getByRole("progressbar", { name: "Diamonds Jack confidence" }),
    ).toHaveValue(0.75);
    expect(screen.getByText("Clubs Nine")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("restores deep-linked row and hypothesis and moves rows with the keyboard", async () => {
    window.history.pushState(
      {},
      "",
      `/round-analyses/${ANALYSIS_ID}?row=observation-002&hypothesis=2`,
    );
    const fetchMock = vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).endsWith("/timeline")
              ? resolvedTimeline
              : resolvedStatus,
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const user = userEvent.setup();
    const selectedRow = await screen.findByRole("option", {
      name: /observation-002/,
      selected: true,
    });
    expect(selectedRow).toHaveAccessibleName(/observation-002/);
    expect(screen.getByRole("combobox", { name: "Hypothesis" })).toHaveValue(
      "2",
    );
    expect(screen.getByText("Clubs Nine")).toBeInTheDocument();

    await user.click(selectedRow);
    await user.keyboard("{ArrowUp}");

    expect(window.location.search).toBe("?hypothesis=2&row=observation-001");
    expect(
      screen.getByRole("option", { name: /observation-001/, selected: true }),
    ).toBeInTheDocument();
  });

  it.each([
    [
      "ambiguous",
      ambiguousTimeline,
      ambiguousStatus,
      "This result is ambiguous",
    ],
    ["incomplete", incompleteTimeline, incompleteStatus, "Incomplete input"],
    ["impossible", impossibleTimeline, impossibleStatus, "Impossible input"],
  ] as const)(
    "explains the %s terminal result without implying ground truth",
    async (_name, timeline, status, expectedText) => {
      stubTimeline(timeline, status);
      render(<App />);

      await waitFor(() =>
        expect(screen.getByText(new RegExp(expectedText))).toBeInTheDocument(),
      );
      expect(screen.getByText("Engine diagnostics")).toBeInTheDocument();
      expect(
        screen.getByText("Raw reconstruction-result JSON"),
      ).toBeInTheDocument();
      if (timeline.hypotheses.length === 0) {
        expect(screen.getByText("No retained hypotheses.")).toBeInTheDocument();
      }
    },
  );
});

function stubTimeline(
  timeline: RoundAnalysisTimeline,
  status: RoundAnalysisStatus,
) {
  window.history.pushState({}, "", `/round-analyses/${ANALYSIS_ID}`);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).endsWith("/timeline") ? timeline : status,
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    ),
  );
}
