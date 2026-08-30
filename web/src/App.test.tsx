import { render, screen } from "@testing-library/react";

import { App } from "./App";

describe("App", () => {
  it("renders the frontend foundation shell", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Round analysis timeline" }),
    ).toBeInTheDocument();
  });
});
