import { createRoot } from "react-dom/client";
import { JobStartActions } from "./JobStartActions";

function Fixture() {
  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) minmax(17rem, 22rem)",
      }}
    >
      <main aria-label="Workspace center" style={{ padding: "2rem" }}>
        <h1>Workspace center</h1>
        <p>Center remains available after the launch form closes.</p>
      </main>
      <aside
        style={{
          padding: "1rem",
          display: "grid",
          alignContent: "start",
          gap: "1rem",
        }}
      >
        <details open>
          <summary>Lineage drawer</summary>
          <button type="button">Choose revision</button>
        </details>
        <details open>
          <summary>Jobs drawer</summary>
          <button type="button">Open job details</button>
        </details>
        <JobStartActions
          actions={[
            {
              id: "fixture-action",
              label: "Run fixture action",
              description: "Opening this form does not start work.",
              expectedOutput: "One fresh fixture result.",
              sections: [
                {
                  title: "Inputs",
                  content: (
                    <label>
                      Model
                      <input defaultValue="Fixture model" />
                    </label>
                  ),
                },
                {
                  title: "Options",
                  content: (
                    <div>
                      {Array.from({ length: 24 }, (_, index) => (
                        <p key={index}>Option {index + 1}</p>
                      ))}
                    </div>
                  ),
                },
              ],
            },
          ]}
        />
      </aside>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
