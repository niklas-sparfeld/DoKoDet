import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";
import {
  ANALYSIS_ID,
  resolvedStatus,
  resolvedTimeline,
} from "./test/roundAnalysisFixture";

describe("App", () => {
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

    const user = userEvent.setup();
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

    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
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
});
