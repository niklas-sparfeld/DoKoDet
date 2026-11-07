import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { resolvedTimeline } from "../test/roundAnalysisFixture";
import { JobStateProvider } from "../jobs/JobState";
import { CounterfactualWorkbench } from "./CounterfactualWorkbench";

afterEach(() => vi.unstubAllGlobals());

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderWorkbench() {
  return render(
    <JobStateProvider>
      <aside>
        <div data-analysis-inspector-slot="action" />
      </aside>
      <CounterfactualWorkbench timeline={resolvedTimeline}>
        {(controller) => (
          <button
            disabled={controller.uncertain}
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
        )}
      </CounterfactualWorkbench>
    </JobStateProvider>,
  );
}

it("starts one exact counterfactual from the Actions modal and links the shared job", async () => {
  const fetchMock = vi.fn(
    async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).startsWith("/api/jobs?") && init?.method !== "POST")
        return jsonResponse({
          items: [],
          next_cursor: null,
          groups: [],
          queue_revision: 1,
        });
      if (url === "/api/jobs" && init?.method === "POST")
        return jsonResponse({ id: "job-1", state: "queued" }, 202);
      throw new Error(`Unexpected request: ${String(url)}`);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderWorkbench();

  await user.click(screen.getByRole("button", { name: "Change" }));
  await user.click(
    screen.getByRole("button", { name: "Calculate counterfactual…" }),
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText(resolvedTimeline.analysis_id)).toBeInTheDocument();
  expect(
    screen.getByText(resolvedTimeline.artifact_hashes.input_sha256),
  ).toBeInTheDocument();
  expect(
    screen.getByText(resolvedTimeline.artifact_hashes.result_sha256),
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
  ).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  await user.click(
    screen.getByRole("button", { name: "Calculate counterfactual…" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Start calculate counterfactual" }),
  );
  await screen.findByRole("link", { name: "job-1" });

  const posts = fetchMock.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(posts).toHaveLength(1);
  const [jobUrl, init] = posts[0]!;
  expect(jobUrl).toBe("/api/jobs");
  const submitted = JSON.parse(String(init?.body));
  expect(submitted.type).toBe("counterfactual");
  expect(submitted.context.analysis_id).toBe(resolvedTimeline.analysis_id);
  expect(submitted.request.source_input_sha256).toBe(
    resolvedTimeline.artifact_hashes.input_sha256,
  );
  expect(submitted.request.source_result_sha256).toBe(
    resolvedTimeline.artifact_hashes.result_sha256,
  );
  expect(submitted.request.card_identity_overrides).toEqual([
    {
      observation_id: "observation-001",
      observed_card_id: "observation-001-card-01",
      card: "CLUBS_NINE",
    },
  ]);
  expect(new Headers(init?.headers).get("Idempotency-Key")).toBeTruthy();
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(
        ([url, options]) =>
          String(url).startsWith("/api/jobs?") && options?.method !== "POST",
      ).length,
    ).toBeGreaterThanOrEqual(2),
  );
});

it("retries uncertain acceptance with the same frozen request and key", async () => {
  let postCount = 0;
  const fetchMock = vi.fn(
    async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url).startsWith("/api/jobs?") && init?.method !== "POST")
        return jsonResponse({
          items: [],
          next_cursor: null,
          groups: [],
          queue_revision: 1,
        });
      if (url === "/api/jobs" && init?.method === "POST") {
        postCount += 1;
        if (postCount === 1) throw new TypeError("connection lost");
        return jsonResponse({ id: "job-2", state: "queued" }, 202);
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderWorkbench();
  await user.click(screen.getByRole("button", { name: "Change" }));
  await user.click(
    screen.getByRole("button", { name: "Calculate counterfactual…" }),
  );
  const start = () =>
    user.click(
      screen.getByRole("button", { name: "Start calculate counterfactual" }),
    );
  await start();
  expect(
    await screen.findByText(/Acceptance is uncertain/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Change" })).toBeDisabled();
  await start();
  await screen.findByRole("link", { name: "job-2" });

  const posts = fetchMock.mock.calls.filter(
    ([, init]) => init?.method === "POST",
  );
  expect(posts).toHaveLength(2);
  expect(posts[0]?.[1]?.body).toBe(posts[1]?.[1]?.body);
  expect(new Headers(posts[0]?.[1]?.headers).get("Idempotency-Key")).toBe(
    new Headers(posts[1]?.[1]?.headers).get("Idempotency-Key"),
  );
});
