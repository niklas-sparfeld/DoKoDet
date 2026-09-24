import { afterEach, describe, expect, it } from "vitest";

import {
  readPipelineEditorUrlState,
  updatePipelineUrl,
} from "./PipelineVisibleCardUrl";

describe("visible-card editor URL helpers", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/recordings/one/visible-cards");
  });

  it("reads an item and only accepts unsigned integer timestamps", () => {
    window.history.replaceState(
      {},
      "",
      "/recordings/one/visible-cards?item=frame-2&t_us=1250",
    );
    expect(readPipelineEditorUrlState()).toEqual({
      item: "frame-2",
      tUs: 1250,
    });

    window.history.replaceState(
      {},
      "",
      "/recordings/one/visible-cards?item=frame-2&t_us=-1",
    );
    expect(readPipelineEditorUrlState().tUs).toBeNull();
  });

  it("updates selected values and removes values set to null", () => {
    window.history.replaceState(
      {},
      "",
      "/recordings/one/visible-cards?item=old&t_us=10&keep=yes",
    );
    updatePipelineUrl({ item: "new", t_us: null });
    expect(window.location.pathname).toBe("/recordings/one/visible-cards");
    expect(new URLSearchParams(window.location.search)).toEqual(
      new URLSearchParams("item=new&keep=yes"),
    );
  });
});
