import userEvent from "@testing-library/user-event";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProfileControl } from "./ProfileControl";
import { PROFILE_NAME_STORAGE_KEY } from "./profile";

describe("ProfileControl", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it("persists a trimmed name and updates every mounted control", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ProfileControl />
        <ProfileControl />
      </>,
    );

    await user.click(
      screen.getAllByRole("button", { name: "Set profile name" })[0],
    );
    await user.type(screen.getByLabelText("Name or ID"), "  Ada Lovelace  ");
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    expect(window.localStorage.getItem(PROFILE_NAME_STORAGE_KEY)).toBe(
      "Ada Lovelace",
    );
    expect(
      screen.getAllByRole("button", { name: "Profile: Ada Lovelace" }),
    ).toHaveLength(2);
  });
});
