import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Toast } from "./Toast";

afterEach(() => {
  vi.useRealTimers();
});

describe("Toast", () => {
  it("can be closed with its close button", () => {
    render(<Toast message="Saved" />);

    fireEvent.click(screen.getByRole("button", { name: "Close notification" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("disappears automatically after ten seconds", () => {
    vi.useFakeTimers();
    render(<Toast message="Saved" />);

    act(() => {
      vi.advanceTimersByTime(9_999);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
