import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@testing-library/react";
import { JobStartActions, type JobStartAction } from "./JobStartActions";

const action: JobStartAction = {
  id: "detect",
  label: "Detect visible cards",
  description: "Create a fresh visible-card result from the selected input.",
  expectedOutput: "A new visible-card data revision.",
  sections: [
    {
      title: "Inputs",
      content: (
        <label>
          Model
          <input aria-label="Model" defaultValue="model-a" />
        </label>
      ),
    },
    {
      title: "Long form",
      content: (
        <div>
          {Array.from({ length: 20 }, (_, index) => (
            <p key={index}>Option {index + 1}</p>
          ))}
        </div>
      ),
    },
  ],
};

function Fixture() {
  return (
    <>
      <main aria-label="Workspace center">Center stays available</main>
      <aside aria-label="Lineage drawer">
        <button>Choose revision</button>
      </aside>
      <aside aria-label="Jobs drawer">
        <button>Open job details</button>
      </aside>
      <JobStartActions actions={[action]} />
    </>
  );
}

describe("JobStartActions", () => {
  it("opens from keyboard, traps focus, and returns focus on Escape", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    const launch = screen.getByRole("button", {
      name: "Detect visible cards…",
    });
    launch.focus();
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("dialog", { name: "Detect visible cards" });
    expect(
      within(dialog).getByRole("heading", { name: "Inputs" }),
    ).toBeVisible();
    expect(within(dialog).queryByRole("status")).not.toBeInTheDocument();
    expect(within(dialog).getByText("Option 20")).toBeVisible();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(
      within(dialog).getByRole("button", {
        name: "Start detect visible cards",
      }),
    ).toHaveFocus();
    expect(
      screen.getByRole("main", { name: "Workspace center" }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(launch).toHaveFocus();
  });

  it("keeps drawer controls and center usable with a scrollable modal", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    await user.click(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.querySelector("[class*='body']")).not.toBeNull();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(screen.getByRole("button", { name: "Choose revision" }));
    await user.click(screen.getByRole("button", { name: "Open job details" }));
    expect(screen.getByRole("main")).toBeVisible();
  });

  it("shows loading, validation and submitting states without starting on open or cancel", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(
      <JobStartActions
        actions={[action]}
        loading
        validationErrors={["Choose an exact revision."]}
        onStart={onStart}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Detect visible cards…" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading available choices",
    );
    expect(
      screen.getByRole("region", { name: "Fix these fields before starting" }),
    ).toHaveTextContent("Choose an exact revision.");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onStart).not.toHaveBeenCalled();
  });
});
