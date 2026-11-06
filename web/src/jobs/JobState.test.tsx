import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobStateProvider, useJobState } from "./JobState";

function Consumer({ name }: { name: string }) {
  const { jobs, refresh } = useJobState();
  return (
    <section aria-label={name}>
      <button onClick={() => void refresh()}>Refresh {name}</button>
      {jobs.map((job) => (
        <span key={job.id}>{job.label}</span>
      ))}
    </section>
  );
}

const list = (label: string) =>
  new Response(
    JSON.stringify({
      items: [{ id: label, label, state: "running" }],
      next_cursor: null,
      groups: [],
      queue_revision: 1,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );

describe("app job state owner", () => {
  it("shares one polling result across consumers and ignores late stale responses", async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    let calls = 0;
    const fetcher = vi.fn<typeof fetch>(() => {
      calls += 1;
      if (calls === 1)
        return new Promise((resolve) => {
          resolveFirst = resolve;
        });
      return Promise.resolve(list("newer"));
    });
    vi.stubGlobal("fetch", fetcher);
    const view = render(
      <JobStateProvider>
        <Consumer name="one" />
        <Consumer name="two" />
      </JobStateProvider>,
    );
    await waitFor(() => expect(calls).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh one" }));
    await screen.findAllByText("newer");
    await act(async () => {
      resolveFirst?.(list("stale"));
    });
    expect(screen.getAllByText("newer")).toHaveLength(2);
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
    view.unmount();
  });
});
