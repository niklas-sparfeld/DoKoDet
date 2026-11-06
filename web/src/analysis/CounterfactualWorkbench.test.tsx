import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { resolvedTimeline } from "../test/roundAnalysisFixture";
import { CounterfactualWorkbench } from "./CounterfactualWorkbench";

afterEach(() => vi.unstubAllGlobals());

it("submits a managed counterfactual and links to its shared job", async () => {
  const fetchMock = vi.fn(
    async (url: RequestInfo | URL, init?: RequestInit) => {
      if (url === "/api/jobs" && init?.method === "POST") {
        return new Response(JSON.stringify({ id: "job-1", state: "queued" }), {
          status: 202,
        });
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(
    <CounterfactualWorkbench timeline={resolvedTimeline}>
      {(controller) => (
        <>
          <button
            onClick={() =>
              controller.setCardIdentity(
                "observation-001",
                "observation-001-card-01",
                "CLUBS_NINE",
              )
            }
          >
            Change
          </button>
          <button onClick={() => void controller.runCounterfactual()}>
            Run
          </button>
          {controller.jobId ? (
            <a href={`/jobs/${controller.jobId}`}>View job</a>
          ) : null}
        </>
      )}
    </CounterfactualWorkbench>,
  );
  await user.click(screen.getByRole("button", { name: "Change" }));
  await user.click(screen.getByRole("button", { name: "Run" }));
  expect(await screen.findByRole("link", { name: "View job" })).toHaveAttribute(
    "href",
    "/jobs/job-1",
  );
  const [jobUrl, init] = fetchMock.mock.calls[0]!;
  expect(jobUrl).toBe("/api/jobs");
  const submitted = JSON.parse(String(init?.body));
  expect(submitted.type).toBe("counterfactual");
  expect(submitted.context.analysis_id).toBe(resolvedTimeline.analysis_id);
  expect(submitted.request.card_identity_overrides).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
