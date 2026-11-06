import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { App } from "../App";

const job = {
  id: "job-1",
  label: "Fixture job",
  type: "fixture",
  state: "running",
  parent_id: null,
  schema_version: "backend-job/v1",
  capabilities: {
    cancel: { allowed: true },
    retry: { allowed: false },
    reorder: { allowed: true },
  },
  context: {},
  correlation_id: null,
  coverage: null,
  created_at: "2026-01-01T00:00:00Z",
  creator: null,
  failure: null,
  finished_at: null,
  idempotency_key: "key",
  implementation: {},
  inputs: [],
  phase: "work",
  request: {},
  request_hash: "hash",
  results: [],
  retry_of: null,
  revision: 1,
  started_at: "2026-01-01T00:00:00Z",
  steps: [],
  updated_at: "2026-01-01T00:00:00Z",
  waiting_reason: null,
  warnings: [],
  worker_owner: null,
};

it("keeps the Jobs drawer available on recording routes and exposes keyboard controls", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            String(input).startsWith("/api/jobs?")
              ? {
                  items: [job],
                  next_cursor: null,
                  groups: [{ group_id: "job-1", child_job_ids: ["job-1"] }],
                  queue_revision: 1,
                }
              : { recordings: [] },
          ),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    ),
  );
  window.history.pushState({}, "", "/");
  render(<App />);
  const toggle = await screen.findByRole("button", { name: /Jobs/ });
  expect(toggle).toHaveTextContent("1");
  await userEvent.setup().click(toggle);
  expect(
    await screen.findByRole("complementary", { name: "Jobs" }),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: "Fixture job" })).toHaveAttribute(
    "href",
    "/jobs/job-1",
  );
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Enable queue reordering" }));
  expect(
    screen.getByRole("button", { name: "Move Fixture job up" }),
  ).toBeDisabled();
  await userEvent.setup().keyboard("{Escape}");
  expect(toggle).toHaveFocus();
  vi.unstubAllGlobals();
});
