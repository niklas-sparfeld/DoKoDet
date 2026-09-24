import {
  WORKBENCH_DISABLED_REASONS,
  type WorkbenchEditTool,
  type WorkbenchLayer,
  type WorkbenchViewpoint,
} from "./VisibleCardReviewWorkbenchState";

export type WorkbenchGuidanceTarget = {
  kind: "viewpoint" | "layer" | "tool";
  id: WorkbenchViewpoint | WorkbenchLayer | WorkbenchEditTool;
  label: string;
  reason: string;
};

export type WorkbenchGuidanceStep = {
  title: string;
  description: string;
  actionLabel?: string;
  action?: () => void;
  dismissOnAction?: boolean;
};

export type WorkbenchGuidance = {
  title: string;
  description: string;
  steps: readonly WorkbenchGuidanceStep[];
};

export type WorkbenchGuidanceCallbacks = {
  onStartProposal?: () => void;
  onStartMappingPreview?: () => void;
  onSelectTool?: (tool: WorkbenchEditTool) => void;
};

export function createWorkbenchGuidance(
  target: WorkbenchGuidanceTarget,
  callbacks: WorkbenchGuidanceCallbacks = {},
): WorkbenchGuidance {
  if (target.reason === WORKBENCH_DISABLED_REASONS.noCalibration) {
    return {
      title: `${target.label} needs a table-plane calibration`,
      description:
        "This view becomes available after the proposed card scene has a valid table-plane calibration.",
      steps: [
        {
          title: "Create proposed card scenes",
          description:
            "Run the proposed card-scene processor from the inspector. It creates the card scene and its initial table mapping.",
          actionLabel: "Create proposed card scenes",
          action: callbacks.onStartProposal,
        },
        {
          title: "Start the calibration preview",
          description:
            "When the proposal is ready, start the calibration preview in the inspector. Review the anchors before you apply the calibration.",
          actionLabel: "Start calibration preview",
          action: callbacks.onStartMappingPreview,
        },
        {
          title: "Return to this control",
          description:
            "After the calibration is available, click this control again to open the rectified view, mapping diagnostics, or virtual-card editor.",
        },
      ],
    };
  }

  if (target.reason === WORKBENCH_DISABLED_REASONS.noSourceFrame) {
    return {
      title: `${target.label} needs a resolved source frame`,
      description:
        "This control works on frame pixels. Select a resolved frame in the Timeline Rail first.",
      steps: [
        {
          title: "Select a resolved frame",
          description:
            "Choose a frame with a source image. The control will be available as soon as the frame is loaded.",
        },
      ],
    };
  }

  if (target.reason === WORKBENCH_DISABLED_REASONS.noVisibleRegions) {
    return {
      title: "There are no visible regions in this frame",
      description:
        "Add or review a visible region before you show the visible-region layer.",
      steps: [
        {
          title: "Open visible-region editing",
          description:
            "Use the visible-region editor to add a card polygon. The layer will appear after the first region exists.",
          actionLabel: "Open Visible regions",
          action: callbacks.onSelectTool
            ? () => callbacks.onSelectTool?.("visible_regions")
            : undefined,
          dismissOnAction: true,
        },
      ],
    };
  }

  if (target.reason === WORKBENCH_DISABLED_REASONS.noIgnoreRegions) {
    return {
      title: "There are no ignore regions in this frame",
      description:
        "Create an ignore region in the visible-region editor before you show this layer.",
      steps: [
        {
          title: "Draw an ignore region",
          description:
            "Open visible-region editing, then use Draw ignore region on the Timeline Rail.",
          actionLabel: "Open Visible regions",
          action: callbacks.onSelectTool
            ? () => callbacks.onSelectTool?.("visible_regions")
            : undefined,
          dismissOnAction: true,
        },
      ],
    };
  }

  if (target.reason === WORKBENCH_DISABLED_REASONS.noSuggestions) {
    return {
      title: "There are no detector suggestions in this frame",
      description:
        "Select a frame with detector suggestions, or create a new proposal from the inspector.",
      steps: [
        {
          title: "Choose the next source",
          description:
            "The suggestions layer is only shown for frames that contain detector output.",
        },
      ],
    };
  }

  return {
    title: `${target.label} is not available yet`,
    description: target.reason,
    steps: [
      {
        title: "Resolve the prerequisite",
        description: target.reason,
      },
    ],
  };
}
