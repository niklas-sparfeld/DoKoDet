import { describe, expect, it } from "vitest";

import {
  WORKBENCH_COMMAND_GROUPS,
  WORKBENCH_DISABLED_REASONS,
  WORKBENCH_HIT_TEST_PRIORITY,
  WORKBENCH_SELECTION_ACTIONS,
  commandBarLayoutForWidth,
  createVisibleCardReviewWorkbenchState,
  getWorkbenchAvailability,
  getWorkbenchPreferences,
  visibleCardReviewWorkbenchReducer,
  workbenchShortcutOwner,
  workbenchViewportShortcut,
  type WorkbenchFrameCapabilities,
} from "./VisibleCardReviewWorkbenchState";

function capabilities(
  overrides: Partial<WorkbenchFrameCapabilities> = {},
): WorkbenchFrameCapabilities {
  return {
    frameId: "frame-1",
    hasSourceFrame: true,
    hasVisibleRegions: true,
    hasCardScene: true,
    hasCalibration: true,
    hasProposals: true,
    hasIgnoreRegions: true,
    readOnly: false,
    ...overrides,
  };
}

describe("visible-card review workbench state", () => {
  it("freezes the hit-test and command-bar contracts", () => {
    expect(WORKBENCH_HIT_TEST_PRIORITY).toEqual([
      "visible_regions",
      "virtual_cards",
      "ignore_regions",
      "suggestions",
      "mapping",
    ]);
    expect(WORKBENCH_COMMAND_GROUPS).toEqual([
      "view",
      "show",
      "edit",
      "selection_actions",
      "frame_decision",
    ]);
    expect(WORKBENCH_SELECTION_ACTIONS.visible_regions).toContain(
      "draw_ignore_region",
    );
    expect(WORKBENCH_SELECTION_ACTIONS.virtual_cards).toContain("accept_card");
    expect(WORKBENCH_SELECTION_ACTIONS.mapping).toContain("accept_anchor");
  });

  it("defaults a calibrated card scene to Rectified and virtual-card review", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());

    expect(state.viewpoint).toBe("rectified");
    expect(state.activeTool).toBe("virtual_cards");
    expect(state.enabledLayers).toEqual([
      "visible_regions",
      "virtual_cards",
      "ignore_regions",
      "suggestions",
    ]);
  });

  it("explains unsupported Rectified, Virtual cards, and Mapping states", () => {
    const availability = getWorkbenchAvailability(
      capabilities({ hasCalibration: false, hasCardScene: false }),
    );

    expect(availability.viewpoints.rectified).toEqual({
      available: false,
      disabledReason: WORKBENCH_DISABLED_REASONS.noCalibration,
    });
    expect(availability.layers.virtual_cards.available).toBe(false);
    expect(availability.tools.virtual_cards.disabledReason).toBe(
      WORKBENCH_DISABLED_REASONS.noCalibration,
    );
    expect(availability.tools.mapping.disabledReason).toBe(
      WORKBENCH_DISABLED_REASONS.noCalibration,
    );
  });

  it("keeps Virtual cards and Mapping available when calibration exists without a card scene", () => {
    const state = createVisibleCardReviewWorkbenchState(
      capabilities({ hasCardScene: false }),
    );
    const availability = getWorkbenchAvailability(state.capabilities);
    const virtualCards = visibleCardReviewWorkbenchReducer(state, {
      type: "select_tool",
      tool: "virtual_cards",
    });

    expect(availability.tools.virtual_cards.available).toBe(true);
    expect(availability.tools.mapping.available).toBe(true);
    expect(virtualCards.activeTool).toBe("virtual_cards");
  });

  it("falls back to Camera and visible-region inspection when the source frame is unavailable", () => {
    const state = createVisibleCardReviewWorkbenchState(
      capabilities({ hasSourceFrame: false }),
    );

    expect(state.viewpoint).toBe("camera");
    expect(state.activeTool).toBe("visible_regions");
    expect(
      getWorkbenchAvailability(state.capabilities).viewpoints.camera,
    ).toEqual({
      available: false,
      disabledReason: WORKBENCH_DISABLED_REASONS.noSourceFrame,
    });
  });

  it("keeps read-only tools and layers inspectable while blocking edit gestures", () => {
    const state = createVisibleCardReviewWorkbenchState(
      capabilities({ readOnly: true }),
    );
    const selected = visibleCardReviewWorkbenchReducer(state, {
      type: "select",
      selection: { type: "virtual_card", id: "card-1" },
    });
    const attemptedEdit = visibleCardReviewWorkbenchReducer(selected, {
      type: "begin_gesture",
      gesture: { kind: "edit", tool: "virtual_cards", pointerId: 1 },
    });

    expect(selected.selection).toEqual({ type: "virtual_card", id: "card-1" });
    expect(attemptedEdit.gesture).toBeNull();
    expect(
      getWorkbenchAvailability(capabilities({ readOnly: true })).tools
        .virtual_cards.mutationDisabledReason,
    ).toBe(WORKBENCH_DISABLED_REASONS.readOnly);
  });

  it("keeps selection separate from layer visibility and cancels gestures on tool changes", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());
    const visibleRegionTool = visibleCardReviewWorkbenchReducer(state, {
      type: "select_tool",
      tool: "visible_regions",
    });
    const selected = visibleCardReviewWorkbenchReducer(visibleRegionTool, {
      type: "select",
      selection: { type: "visible_card", id: "card-1" },
    });
    const gesturing = visibleCardReviewWorkbenchReducer(selected, {
      type: "begin_gesture",
      gesture: { kind: "edit", tool: "visible_regions", pointerId: 2 },
    });
    const hidden = visibleCardReviewWorkbenchReducer(gesturing, {
      type: "toggle_layer",
      layer: "visible_regions",
    });
    const switched = visibleCardReviewWorkbenchReducer(hidden, {
      type: "select_tool",
      tool: "mapping",
    });

    expect(gesturing.gesture).not.toBeNull();
    expect(hidden.selection).toEqual({ type: "visible_card", id: "card-1" });
    expect(hidden.visualFocus).toBe(false);
    expect(switched.selection).toBeNull();
    expect(switched.gesture).toBeNull();
  });

  it("preselects only the view layer that belongs to the active editor", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());

    const visibleRegions = visibleCardReviewWorkbenchReducer(state, {
      type: "select_tool",
      tool: "visible_regions",
    });
    const virtualCards = visibleCardReviewWorkbenchReducer(visibleRegions, {
      type: "select_tool",
      tool: "virtual_cards",
    });
    const mapping = visibleCardReviewWorkbenchReducer(virtualCards, {
      type: "select_tool",
      tool: "mapping",
    });

    expect(visibleRegions.enabledLayers).toEqual(["visible_regions"]);
    expect(virtualCards.enabledLayers).toEqual(["virtual_cards"]);
    expect(mapping.enabledLayers).toEqual(["mapping"]);
  });

  it("toggles the single viewpoint control without writing geometry", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());
    const gesturing = visibleCardReviewWorkbenchReducer(state, {
      type: "begin_gesture",
      gesture: { kind: "pan", tool: null, pointerId: 4 },
    });
    const next = visibleCardReviewWorkbenchReducer(gesturing, {
      type: "toggle_viewpoint",
    });

    expect(next.viewpoint).toBe("camera");
    expect(next.gesture).toBeNull();
    expect(next.viewports).toEqual(state.viewports);
    expect(next.selection).toBeNull();
  });

  it("keeps zoom and pan independent for Camera and Rectified viewpoints", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());
    const rectified = visibleCardReviewWorkbenchReducer(state, {
      type: "set_viewport",
      viewport: { zoom: 2, pan: { x: 12, y: -8 } },
    });
    const camera = visibleCardReviewWorkbenchReducer(rectified, {
      type: "toggle_viewpoint",
    });
    const cameraAdjusted = visibleCardReviewWorkbenchReducer(camera, {
      type: "set_viewport",
      viewport: { zoom: 1.5, pan: { x: -4, y: 6 } },
    });
    const restored = visibleCardReviewWorkbenchReducer(cameraAdjusted, {
      type: "toggle_viewpoint",
    });

    expect(cameraAdjusted.viewports).toEqual({
      camera: { zoom: 1.5, pan: { x: -4, y: 6 } },
      rectified: { zoom: 2, pan: { x: 12, y: -8 } },
    });
    expect(restored.viewpoint).toBe("rectified");
    expect(restored.viewports.rectified).toEqual({
      zoom: 2,
      pan: { x: 12, y: -8 },
    });
  });

  it("preserves layer and edit-mode preferences when a frame has no elements", () => {
    const state = createVisibleCardReviewWorkbenchState(capabilities());
    const prepared = visibleCardReviewWorkbenchReducer(state, {
      type: "select_tool",
      tool: "mapping",
    });
    const navigated = visibleCardReviewWorkbenchReducer(prepared, {
      type: "navigate_frame",
      capabilities: capabilities({
        frameId: "frame-2",
        hasCalibration: false,
        hasCardScene: false,
        hasVisibleRegions: true,
        hasIgnoreRegions: false,
      }),
    });

    expect(getWorkbenchPreferences(navigated)).toEqual({
      viewpoint: "camera",
      enabledLayers: ["mapping"],
      activeTool: "mapping",
    });
    expect(navigated.frameId).toBe("frame-2");
    expect(navigated.selection).toBeNull();
    expect(navigated.gesture).toBeNull();
  });

  it("scopes mutating shortcuts to the active tool and keeps viewport shortcuts surface-only", () => {
    expect(workbenchShortcutOwner("N", "visible_regions", "surface")).toBe(
      "visible_regions",
    );
    expect(workbenchShortcutOwner("N", "virtual_cards", "surface")).toBeNull();
    expect(workbenchShortcutOwner("R", "virtual_cards", "surface")).toBe(
      "virtual_cards",
    );
    expect(workbenchShortcutOwner("D", "mapping", "surface")).toBe("mapping");
    expect(workbenchShortcutOwner("D", "mapping", "input")).toBeNull();
    expect(workbenchShortcutOwner("Escape", "mapping", "surface")).toBe(
      "shared",
    );

    expect(
      workbenchViewportShortcut({ key: "ArrowLeft", altKey: true }, "surface"),
    ).toBe("pan_left");
    expect(workbenchViewportShortcut({ key: "+" }, "surface")).toBe("zoom_in");
    expect(workbenchViewportShortcut({ key: "0" }, "inspector")).toBeNull();
  });

  it("uses an inline command bar on wide layouts and a scrollable bar on narrow layouts", () => {
    expect(commandBarLayoutForWidth(1280)).toEqual({
      mode: "inline",
      groupsWrap: true,
      surfacePriority: "primary",
    });
    expect(commandBarLayoutForWidth(390)).toEqual({
      mode: "scroll",
      groupsWrap: false,
      surfacePriority: "primary",
    });
  });
});
