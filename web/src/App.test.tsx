import { render, screen, waitFor } from "@testing-library/react";

import { App } from "./App";

describe("App", () => {
  it("renders the frontend foundation shell", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Round analysis timeline" }),
    ).toBeInTheDocument();
  });

  it("loads the typed analysis smoke view from the entry route", async () => {
    window.history.pushState(
      {},
      "",
      "/round-analyses/550e8400-e29b-41d4-a716-446655440033",
    );
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const path = String(input);
      if (path.endsWith("/timeline")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              analysis_id: "550e8400-e29b-41d4-a716-446655440033",
              reconstruction_status: "resolved",
              rows: [{}, {}],
              hypotheses: [{}],
              warnings: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            analysis_id: "550e8400-e29b-41d4-a716-446655440033",
            recording_id: "recording-0033",
            round_id: "round-0033",
            session_id: "550e8400-e29b-41d4-a716-446655440034",
            state: "complete",
            total_evidence_packages: 2,
            completed_evidence_packages: 2,
            result: {},
            error: null,
            created_at: "2026-08-30T12:00:00Z",
            started_at: "2026-08-30T12:00:01Z",
            completed_at: "2026-08-30T12:00:02Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(screen.getByText("Loading analysis…")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("Timeline API connected")).toBeInTheDocument(),
    );
    expect(screen.getByText(/2 evidence rows/)).toBeInTheDocument();
    expect(screen.getByText(/1 retained hypothesis/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });
});
