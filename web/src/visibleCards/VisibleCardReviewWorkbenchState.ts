import type { Candidate, EditableFrame } from "./PipelineVisibleCardTypes";

export const WORKBENCH_VIEWPOINTS = ["camera", "rectified"] as const;
export type WorkbenchViewpoint = (typeof WORKBENCH_VIEWPOINTS)[number];

export const WORKBENCH_LAYERS = [
  "visible_regions",
  "virtual_cards",
  "ignore_regions",
  "suggestions",
  "mapping",
] as const;
export type WorkbenchLayer = (typeof WORKBENCH_LAYERS)[number];

export const WORKBENCH_EDIT_TOOLS = [
  "visible_regions",
  "virtual_cards",
  "mapping",
] as const;
export type WorkbenchEditTool = (typeof WORKBENCH_EDIT_TOOLS)[number];

export const WORKBENCH_SELECTION_TYPES = [
  "visible_card",
  "polygon",
  "ignore_region",
  "virtual_card",
  "calibration_anchor",
] as const;
export type WorkbenchSelectionType = (typeof WORKBENCH_SELECTION_TYPES)[number];

export type WorkbenchSelection =
  | { type: "visible_card"; id: string }
  | { type: "polygon"; id: string; polygonIndex: number }
  | { type: "ignore_region"; id: string }
  | { type: "virtual_card"; id: string }
  | { type: "calibration_anchor"; id: string };

export type WorkbenchFrameCapabilities = {
  frameId: string;
  hasSourceFrame: boolean;
  hasVisibleRegions: boolean;
  hasCardScene: boolean;
  hasCalibration: boolean;
  hasProposals: boolean;
  hasIgnoreRegions: boolean;
  readOnly: boolean;
};

export type WorkbenchPreferences = {
  viewpoint: WorkbenchViewpoint;
  enabledLayers: WorkbenchLayer[];
  activeTool: WorkbenchEditTool;
};

export type WorkbenchGesture = {
  kind: "edit" | "pan" | "zoom";
  tool: WorkbenchEditTool | null;
  pointerId: number | null;
};

export type WorkbenchViewport = {
  zoom: number;
  pan: { x: number; y: number };
};

export type VisibleCardReviewWorkbenchState = WorkbenchPreferences & {
  frameId: string;
  capabilities: WorkbenchFrameCapabilities;
  selection: WorkbenchSelection | null;
  visualFocus: boolean;
  gesture: WorkbenchGesture | null;
  viewport: WorkbenchViewport;
};

export type WorkbenchAction =
  | { type: "toggle_viewpoint" }
  | { type: "toggle_layer"; layer: WorkbenchLayer }
  | { type: "select_tool"; tool: WorkbenchEditTool }
  | { type: "select"; selection: WorkbenchSelection }
  | { type: "clear_selection" }
  | { type: "begin_gesture"; gesture: WorkbenchGesture }
  | { type: "cancel_gesture" }
  | { type: "commit_gesture" }
  | { type: "refresh_capabilities"; capabilities: WorkbenchFrameCapabilities }
  | { type: "navigate_frame"; capabilities: WorkbenchFrameCapabilities }
  | { type: "restore_preferences"; preferences: WorkbenchPreferences }
  | { type: "set_viewport"; viewport: WorkbenchViewport }
  | { type: "reset_viewport" };

export type WorkbenchControlAvailability = {
  available: boolean;
  disabledReason: string | null;
};

export type WorkbenchToolAvailability = WorkbenchControlAvailability & {
  mutationsAllowed: boolean;
  mutationDisabledReason: string | null;
};

export type WorkbenchAvailability = {
  viewpoints: Record<WorkbenchViewpoint, WorkbenchControlAvailability>;
  layers: Record<WorkbenchLayer, WorkbenchControlAvailability>;
  tools: Record<WorkbenchEditTool, WorkbenchToolAvailability>;
};

export const WORKBENCH_LAYER_DRAW_ORDER = [
  "mapping",
  "ignore_regions",
  "suggestions",
  "virtual_cards",
  "visible_regions",
] as const satisfies readonly WorkbenchLayer[];

export const WORKBENCH_HIT_TEST_PRIORITY = [
  "visible_regions",
  "virtual_cards",
  "ignore_regions",
  "suggestions",
  "mapping",
] as const satisfies readonly WorkbenchLayer[];

export const WORKBENCH_COMMAND_GROUPS = [
  "view",
  "show",
  "edit",
  "selection_actions",
  "frame_decision",
] as const;

export const WORKBENCH_SELECTION_ACTIONS = {
  visible_regions: [
    "add_visible_card",
    "add_polygon",
    "remove_polygon",
    "draw_ignore_region",
    "convert_to_ignore_region",
    "copy_ignore_regions",
    "delete_selection",
    "restore_suggestion",
  ],
  virtual_cards: [
    "add_virtual_card",
    "accept_card",
    "reject_card",
    "accept_remaining_cards",
    "remove_card",
    "bring_forward",
    "send_backward",
    "restore_proposed_scene",
  ],
  mapping: [
    "accept_anchor",
    "adjust_anchor",
    "pin_anchor",
    "exclude_anchor",
    "start_mapping_preview",
    "discard_mapping_preview",
    "apply_mapping",
  ],
} as const satisfies Record<WorkbenchEditTool, readonly string[]>;

export const WORKBENCH_DISABLED_REASONS = {
  noSourceFrame: "No resolved source frame is available.",
  noCalibration:
    "A valid table-plane calibration is required for this control.",
  noVisibleRegions: "This frame has no visible-region polygons.",
  noIgnoreRegions: "This frame has no reviewed ignore regions.",
  noSuggestions: "This frame has no detector suggestions.",
  readOnly: "Generated visible-card results are read-only.",
  incompatibleSelection: "The current selection does not belong to this tool.",
  shortcutFocus:
    "Canvas shortcuts are available only when the review surface has focus.",
} as const;

export const WORKBENCH_MUTATION_SHORTCUTS = {
  visible_regions: ["n", "i", "delete", "backspace"],
  virtual_cards: ["arrowleft", "arrowright", "arrowup", "arrowdown", "r"],
  mapping: ["d", "x", "y"],
} as const satisfies Record<WorkbenchEditTool, readonly string[]>;

export const WORKBENCH_VIEWPORT_KEYBOARD_SHORTCUTS = {
  pan_left: "alt+arrowleft",
  pan_right: "alt+arrowright",
  pan_up: "alt+arrowup",
  pan_down: "alt+arrowdown",
  zoom_in: "+",
  zoom_out: "-",
  reset: "0",
} as const;

export const WORKBENCH_NARROW_BREAKPOINT_PX = 800;

export type WorkbenchCommandBarLayout = {
  mode: "inline" | "scroll";
  groupsWrap: boolean;
  surfacePriority: "primary";
};

export type WorkbenchShortcutFocus =
  "surface" | "command_bar" | "input" | "dialog" | "inspector";

export type WorkbenchViewportShortcut =
  | "pan_left"
  | "pan_right"
  | "pan_up"
  | "pan_down"
  | "zoom_in"
  | "zoom_out"
  | "reset";

const EMPTY_VIEWPORT: WorkbenchViewport = { zoom: 1, pan: { x: 0, y: 0 } };

export function createVisibleCardReviewWorkbenchState(
  capabilities: WorkbenchFrameCapabilities,
  preferences?: Partial<WorkbenchPreferences>,
): VisibleCardReviewWorkbenchState {
  const defaults = defaultPreferences(capabilities);
  const normalized = normalizePreferences(capabilities, {
    ...defaults,
    ...preferences,
  });
  return {
    ...normalized,
    frameId: capabilities.frameId,
    capabilities,
    selection: null,
    visualFocus: false,
    gesture: null,
    viewport: cloneViewport(EMPTY_VIEWPORT),
  };
}

export function visibleCardReviewWorkbenchReducer(
  state: VisibleCardReviewWorkbenchState,
  action: WorkbenchAction,
): VisibleCardReviewWorkbenchState {
  switch (action.type) {
    case "toggle_viewpoint": {
      const nextViewpoint =
        state.viewpoint === "camera" ? "rectified" : "camera";
      const availability = getWorkbenchAvailability(state.capabilities);
      if (!availability.viewpoints[nextViewpoint].available) return state;
      return {
        ...state,
        viewpoint: nextViewpoint,
        gesture: null,
      };
    }
    case "toggle_layer": {
      const availability = getWorkbenchAvailability(state.capabilities);
      if (!availability.layers[action.layer].available) return state;
      const isEnabled = state.enabledLayers.includes(action.layer);
      const enabledLayers = isEnabled
        ? state.enabledLayers.filter((layer) => layer !== action.layer)
        : [...state.enabledLayers, action.layer];
      const hidesSelection =
        isEnabled &&
        state.selection !== null &&
        layerForSelection(state.selection) === action.layer;
      return {
        ...state,
        enabledLayers,
        visualFocus: hidesSelection ? false : state.visualFocus,
      };
    }
    case "select_tool": {
      const availability = getWorkbenchAvailability(state.capabilities);
      if (!availability.tools[action.tool].available) return state;
      const selection = isSelectionCompatible(action.tool, state.selection)
        ? state.selection
        : null;
      return {
        ...state,
        activeTool: action.tool,
        selection,
        visualFocus: selection === null ? false : state.visualFocus,
        gesture: null,
      };
    }
    case "select": {
      if (!isSelectionAvailable(action.selection, state)) return state;
      return {
        ...state,
        selection: action.selection,
        visualFocus: true,
      };
    }
    case "clear_selection":
      return { ...state, selection: null, visualFocus: false };
    case "begin_gesture": {
      if (action.gesture.kind === "edit") {
        const toolAvailability = getWorkbenchAvailability(state.capabilities)
          .tools[state.activeTool];
        if (!toolAvailability.mutationsAllowed) return state;
        if (action.gesture.tool !== state.activeTool) return state;
      }
      return { ...state, gesture: cloneGesture(action.gesture) };
    }
    case "cancel_gesture":
    case "commit_gesture":
      return state.gesture === null ? state : { ...state, gesture: null };
    case "navigate_frame": {
      const preferences = normalizePreferences(action.capabilities, {
        viewpoint: state.viewpoint,
        enabledLayers: state.enabledLayers,
        activeTool: state.activeTool,
      });
      return {
        ...state,
        ...preferences,
        frameId: action.capabilities.frameId,
        capabilities: action.capabilities,
        selection: null,
        visualFocus: false,
        gesture: null,
        viewport: cloneViewport(EMPTY_VIEWPORT),
      };
    }
    case "refresh_capabilities": {
      const enabledLayers: WorkbenchLayer[] = [
        ...state.enabledLayers,
        ...(state.capabilities.hasVisibleRegions ||
        !action.capabilities.hasVisibleRegions
          ? []
          : (["visible_regions"] as const)),
        ...(state.capabilities.hasIgnoreRegions ||
        !action.capabilities.hasIgnoreRegions
          ? []
          : (["ignore_regions"] as const)),
      ];
      const preferences = normalizePreferences(action.capabilities, {
        viewpoint: state.viewpoint,
        enabledLayers,
        activeTool: state.activeTool,
      });
      return {
        ...state,
        ...preferences,
        capabilities: action.capabilities,
        selection:
          state.selection !== null &&
          isSelectionAvailable(state.selection, {
            ...state,
            capabilities: action.capabilities,
          })
            ? state.selection
            : null,
        visualFocus: false,
      };
    }
    case "restore_preferences": {
      const preferences = normalizePreferences(
        state.capabilities,
        action.preferences,
      );
      return {
        ...state,
        ...preferences,
        selection: isSelectionCompatible(
          preferences.activeTool,
          state.selection,
        )
          ? state.selection
          : null,
        visualFocus: false,
        gesture: null,
      };
    }
    case "set_viewport":
      return { ...state, viewport: normalizeViewport(action.viewport) };
    case "reset_viewport":
      return { ...state, viewport: cloneViewport(EMPTY_VIEWPORT) };
  }
}

export function getWorkbenchPreferences(
  state: VisibleCardReviewWorkbenchState,
): WorkbenchPreferences {
  return {
    viewpoint: state.viewpoint,
    enabledLayers: [...state.enabledLayers],
    activeTool: state.activeTool,
  };
}

export function getWorkbenchAvailability(
  capabilities: WorkbenchFrameCapabilities,
): WorkbenchAvailability {
  const source = capabilities.hasSourceFrame;
  const calibration = source && capabilities.hasCalibration;
  const editableReason = capabilities.readOnly
    ? WORKBENCH_DISABLED_REASONS.readOnly
    : null;
  return {
    viewpoints: {
      camera: control(
        source,
        source ? null : WORKBENCH_DISABLED_REASONS.noSourceFrame,
      ),
      rectified: control(
        calibration,
        calibration ? null : WORKBENCH_DISABLED_REASONS.noCalibration,
      ),
    },
    layers: {
      visible_regions: control(
        source && capabilities.hasVisibleRegions,
        source
          ? capabilities.hasVisibleRegions
            ? null
            : WORKBENCH_DISABLED_REASONS.noVisibleRegions
          : WORKBENCH_DISABLED_REASONS.noSourceFrame,
      ),
      virtual_cards: control(
        calibration,
        calibration ? null : WORKBENCH_DISABLED_REASONS.noCalibration,
      ),
      ignore_regions: control(
        source && capabilities.hasIgnoreRegions,
        source
          ? capabilities.hasIgnoreRegions
            ? null
            : WORKBENCH_DISABLED_REASONS.noIgnoreRegions
          : WORKBENCH_DISABLED_REASONS.noSourceFrame,
      ),
      suggestions: control(
        source && capabilities.hasProposals,
        source
          ? capabilities.hasProposals
            ? null
            : WORKBENCH_DISABLED_REASONS.noSuggestions
          : WORKBENCH_DISABLED_REASONS.noSourceFrame,
      ),
      mapping: control(
        calibration,
        calibration ? null : WORKBENCH_DISABLED_REASONS.noCalibration,
      ),
    },
    tools: {
      visible_regions: tool(
        source,
        source ? null : WORKBENCH_DISABLED_REASONS.noSourceFrame,
        editableReason,
      ),
      virtual_cards: tool(
        calibration,
        calibration ? null : WORKBENCH_DISABLED_REASONS.noCalibration,
        editableReason,
      ),
      mapping: tool(
        calibration,
        calibration ? null : WORKBENCH_DISABLED_REASONS.noCalibration,
        editableReason,
      ),
    },
  };
}

export function layerForSelection(
  selection: WorkbenchSelection,
): WorkbenchLayer {
  switch (selection.type) {
    case "visible_card":
    case "polygon":
      return "visible_regions";
    case "ignore_region":
      return "ignore_regions";
    case "virtual_card":
      return "virtual_cards";
    case "calibration_anchor":
      return "mapping";
  }
}

export function isSelectionCompatible(
  tool: WorkbenchEditTool,
  selection: WorkbenchSelection | null,
): boolean {
  if (selection === null) return true;
  if (tool === "visible_regions")
    return (
      selection.type === "visible_card" ||
      selection.type === "polygon" ||
      selection.type === "ignore_region"
    );
  if (tool === "virtual_cards") return selection.type === "virtual_card";
  return selection.type === "calibration_anchor";
}

export function commandBarLayoutForWidth(
  widthPx: number,
): WorkbenchCommandBarLayout {
  if (widthPx < WORKBENCH_NARROW_BREAKPOINT_PX) {
    return { mode: "scroll", groupsWrap: false, surfacePriority: "primary" };
  }
  return { mode: "inline", groupsWrap: true, surfacePriority: "primary" };
}

export function workbenchShortcutOwner(
  key: string,
  tool: WorkbenchEditTool,
  focus: WorkbenchShortcutFocus,
): WorkbenchEditTool | "shared" | null {
  if (focus !== "surface") return null;
  const normalizedKey = key.toLowerCase();
  if (normalizedKey === "escape") return "shared";
  const shortcuts: readonly string[] = WORKBENCH_MUTATION_SHORTCUTS[tool];
  return shortcuts.includes(normalizedKey) ? tool : null;
}

export function workbenchViewportShortcut(
  input: {
    key: string;
    altKey?: boolean;
    shiftKey?: boolean;
    ctrlKey?: boolean;
    metaKey?: boolean;
  },
  focus: WorkbenchShortcutFocus,
): WorkbenchViewportShortcut | null {
  if (focus !== "surface" || input.ctrlKey || input.metaKey) return null;
  const key = input.key.toLowerCase();
  if (input.altKey && key === "arrowleft") return "pan_left";
  if (input.altKey && key === "arrowright") return "pan_right";
  if (input.altKey && key === "arrowup") return "pan_up";
  if (input.altKey && key === "arrowdown") return "pan_down";
  if (!input.altKey && !input.shiftKey && (input.key === "+" || key === "="))
    return "zoom_in";
  if (!input.altKey && !input.shiftKey && (input.key === "-" || key === "_"))
    return "zoom_out";
  if (!input.altKey && !input.shiftKey && key === "0") return "reset";
  return null;
}

function defaultPreferences(
  capabilities: WorkbenchFrameCapabilities,
): WorkbenchPreferences {
  const hasRectifiedScene =
    capabilities.hasSourceFrame &&
    capabilities.hasCardScene &&
    capabilities.hasCalibration;
  const enabledLayers: WorkbenchLayer[] = [];
  if (capabilities.hasVisibleRegions) enabledLayers.push("visible_regions");
  if (hasRectifiedScene) enabledLayers.push("virtual_cards");
  if (capabilities.hasIgnoreRegions) enabledLayers.push("ignore_regions");
  if (capabilities.hasProposals) enabledLayers.push("suggestions");
  return {
    viewpoint: hasRectifiedScene ? "rectified" : "camera",
    enabledLayers,
    activeTool: hasRectifiedScene ? "virtual_cards" : "visible_regions",
  };
}

function normalizePreferences(
  capabilities: WorkbenchFrameCapabilities,
  preferences: WorkbenchPreferences,
): WorkbenchPreferences {
  const availability = getWorkbenchAvailability(capabilities);
  const fallback = defaultPreferences(capabilities);
  const viewpoint = availability.viewpoints[preferences.viewpoint].available
    ? preferences.viewpoint
    : fallback.viewpoint;
  const enabledLayers = uniqueLayers(preferences.enabledLayers).filter(
    (layer) => availability.layers[layer].available,
  );
  const activeTool = availability.tools[preferences.activeTool].available
    ? preferences.activeTool
    : fallback.activeTool;
  return { viewpoint, enabledLayers, activeTool };
}

function isSelectionAvailable(
  selection: WorkbenchSelection,
  state: VisibleCardReviewWorkbenchState,
): boolean {
  if (
    selection.type === "visible_card" &&
    !getWorkbenchAvailability(state.capabilities).layers.visible_regions
      .available
  ) {
    return (
      state.capabilities.hasProposals &&
      isSelectionCompatible(state.activeTool, selection)
    );
  }
  return (
    getWorkbenchAvailability(state.capabilities).layers[
      layerForSelection(selection)
    ].available && isSelectionCompatible(state.activeTool, selection)
  );
}

function uniqueLayers(layers: readonly WorkbenchLayer[]): WorkbenchLayer[] {
  return WORKBENCH_LAYERS.filter((layer) => layers.includes(layer));
}

function control(
  available: boolean,
  disabledReason: string | null,
): WorkbenchControlAvailability {
  return { available, disabledReason: available ? null : disabledReason };
}

function tool(
  available: boolean,
  disabledReason: string | null,
  mutationDisabledReason: string | null,
): WorkbenchToolAvailability {
  return {
    available,
    disabledReason: available ? null : disabledReason,
    mutationsAllowed: available && mutationDisabledReason === null,
    mutationDisabledReason: available ? mutationDisabledReason : disabledReason,
  };
}

function cloneGesture(gesture: WorkbenchGesture): WorkbenchGesture {
  return { ...gesture };
}

function cloneViewport(viewport: WorkbenchViewport): WorkbenchViewport {
  return { zoom: viewport.zoom, pan: { ...viewport.pan } };
}

function normalizeViewport(viewport: WorkbenchViewport): WorkbenchViewport {
  return {
    zoom:
      Number.isFinite(viewport.zoom) && viewport.zoom > 0 ? viewport.zoom : 1,
    pan: {
      x: Number.isFinite(viewport.pan.x) ? viewport.pan.x : 0,
      y: Number.isFinite(viewport.pan.y) ? viewport.pan.y : 0,
    },
  };
}

export function workbenchCapabilitiesFromFrame(
  frame: EditableFrame,
  readOnly: boolean,
  displayedCandidates: Candidate[] = frame.outcome.candidates,
): WorkbenchFrameCapabilities {
  return {
    frameId: frame.itemId,
    hasSourceFrame: frame.outcome.frame_identity !== null,
    hasVisibleRegions: displayedCandidates.some(
      (candidate) =>
        (candidate.geometry.visible_region?.polygons.length ?? 0) > 0,
    ),
    hasCardScene: frame.outcome.card_scene !== undefined,
    hasCalibration: frame.outcome.card_scene !== undefined,
    hasProposals: displayedCandidates.length > 0,
    hasIgnoreRegions: frame.outcome.ignored_regions.length > 0,
    readOnly,
  };
}
