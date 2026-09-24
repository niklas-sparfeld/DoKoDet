import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@testing-library/react";

import type { EditableFrame } from "./PipelineVisibleCardTypes";
import {
  getWorkbenchAvailability,
  workbenchCapabilitiesFromFrame,
} from "./VisibleCardReviewWorkbenchState";
import {
  WorkbenchCommandBar,
  WorkbenchTimelineSelectionActions,
} from "./VisibleCardWorkbenchControls";
import { WorkbenchProposalColumn } from "./VisibleCardWorkbenchProposalPresentation";
import type {
  WorkbenchCommandBarViewModel,
  WorkbenchTimelineSelectionCallbacks,
  WorkbenchTimelineSelectionViewModel,
} from "./VisibleCardWorkbenchControls";

const frame: EditableFrame = {
  itemId: "event-1",
  baseItemId: null,
  reviewState: "pending",
  outcome: {
    event_id: "event-1",
    frame_identity: {
      requested_time_us: 400_000,
      frame_index: 4,
      presentation_timestamp_us: 400_000,
      width: 100,
      height: 100,
      image_sha256: "a".repeat(64),
    },
    status: "detected",
    candidates: [
      {
        card_id: "suggestion-1",
        geometry: {
          kind: "detector-box/v1",
          box_2d: { x_min: 30, y_min: 30, x_max: 70, y_max: 70 },
        },
        normalization: {},
        side: "unknown",
      },
    ],
    ignored_regions: [
      {
        region_id: "ignore-1",
        geometry: {
          kind: "reviewed-ignore-region/v1",
          polygons: [
            [
              { x: 5, y: 5 },
              { x: 15, y: 5 },
              { x: 15, y: 15 },
              { x: 5, y: 15 },
            ],
          ],
        },
        normalization: { width: 100, height: 100, policy_id: "test" },
        reason: "untidy_stack",
        source_candidates: [],
      },
    ],
    error: null,
  },
};

function commandBarViewModel(): WorkbenchCommandBarViewModel {
  const capabilities = workbenchCapabilitiesFromFrame(frame, true);
  return {
    viewpoint: "rectified",
    enabledLayers: ["ignore_regions", "suggestions"],
    activeTool: "virtual_cards",
    availability: getWorkbenchAvailability(capabilities),
    readOnly: true,
    enabledEditTools: ["visible_regions", "virtual_cards", "mapping"],
  };
}

function selectionViewModel(
  overrides: Partial<WorkbenchTimelineSelectionViewModel> = {},
): WorkbenchTimelineSelectionViewModel {
  return {
    activeTool: "visible_regions",
    selection: null,
    readOnly: false,
    selectedCandidateIds: [],
    editor: { cardId: "suggestion-1", polygonCount: 1, polygonIndex: 0 },
    sourceAvailable: true,
    canCopyIgnoreRegions: false,
    canRestoreSuggestion: false,
    scene: null,
    calibrationRefinement: null,
    mappingAnchors: [],
    mappingLoading: false,
    anchorCornerIndex: 0,
    numericAnchor: null,
    ...overrides,
  };
}

function selectionCallbacks(): WorkbenchTimelineSelectionCallbacks {
  return {
    onNumericChange: vi.fn(),
    onEmitNumeric: vi.fn(),
    onCardDecision: vi.fn(),
    onResolveRemaining: vi.fn(),
    onSceneAction: vi.fn(),
    onAction: vi.fn(),
  };
}

describe("visible-card workbench controls", () => {
  it("keeps missing-prerequisite controls clickable and explains the next steps", async () => {
    const user = userEvent.setup();
    render(
      <WorkbenchCommandBar
        viewModel={commandBarViewModel()}
        callbacks={{
          onToggleViewpoint: vi.fn(),
          onToggleLayer: vi.fn(),
          onSelectTool: vi.fn(),
        }}
      />,
    );

    const commandBar = screen.getByRole("toolbar", {
      name: "Workbench command bar",
    });
    expect(
      within(commandBar).getByRole("button", {
        name: "Viewpoint: Rectified. Switch to Camera",
      }),
    ).toBeEnabled();
    expect(
      within(commandBar).getByRole("button", { name: "Ignore regions" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(commandBar).getByRole("button", {
        name: "Edit Mapping diagnostics",
      }),
    ).toBeEnabled();
    expect(
      within(commandBar).getByRole("button", {
        name: "Edit Mapping diagnostics",
      }),
    ).toHaveAttribute(
      "title",
      "A valid table-plane calibration is required for this control.",
    );

    await user.click(
      within(commandBar).getByRole("button", {
        name: "Edit Mapping diagnostics",
      }),
    );
    expect(
      screen.getByRole("dialog", {
        name: "Mapping diagnostics needs a table-plane calibration",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
  });

  it("runs guidance actions and advances its prerequisite wizard", async () => {
    const onStartProposal = vi.fn();
    const onStartMappingPreview = vi.fn();
    const user = userEvent.setup();
    render(
      <WorkbenchCommandBar
        viewModel={commandBarViewModel()}
        callbacks={{
          onToggleViewpoint: vi.fn(),
          onToggleLayer: vi.fn(),
          onSelectTool: vi.fn(),
          onStartProposal,
          onStartMappingPreview,
        }}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Edit Mapping diagnostics" }),
    );
    expect(
      screen.getByRole("dialog", {
        name: "Mapping diagnostics needs a table-plane calibration",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Create proposed card scenes" }),
    );
    expect(onStartProposal).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Step 2 of 3")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Start calibration preview" }),
    );
    expect(onStartMappingPreview).toHaveBeenCalledOnce();
  });

  it("dispatches selection actions through named callbacks", async () => {
    const callbacks = selectionCallbacks();
    const user = userEvent.setup();
    render(
      <WorkbenchTimelineSelectionActions
        viewModel={selectionViewModel()}
        callbacks={callbacks}
      />,
    );

    const addVisibleCard = screen.getByRole("button", {
      name: "Add visible card N",
    });
    expect(addVisibleCard).toHaveAttribute("title", "Add visible card (N)");
    await user.click(addVisibleCard);
    expect(callbacks.onAction).toHaveBeenCalledWith("add_visible_card");
  });

  it("keeps copying ignore regions available while another tool is active", async () => {
    const callbacks = selectionCallbacks();
    const user = userEvent.setup();
    render(
      <WorkbenchTimelineSelectionActions
        viewModel={selectionViewModel({
          activeTool: "virtual_cards",
          canCopyIgnoreRegions: true,
        })}
        callbacks={callbacks}
      />,
    );

    const copyButton = screen.getByRole("button", {
      name: "Copy ignore regions Click",
    });
    expect(copyButton).toBeEnabled();
    await user.click(copyButton);
    expect(callbacks.onAction).toHaveBeenCalledWith("copy_ignore_regions");
  });

  it("renders frame decisions with the same enabled state and callbacks", async () => {
    const onAccept = vi.fn();
    const onMarkEmpty = vi.fn();
    const onMarkUnusable = vi.fn();
    const user = userEvent.setup();
    render(
      <WorkbenchTimelineSelectionActions
        viewModel={selectionViewModel({
          frameDecision: {
            accepted: false,
            canAccept: true,
            acceptDisabledReason: "Frame changes must be saved first.",
            onAccept,
            onMarkEmpty,
            onMarkUnusable,
          },
        })}
        callbacks={selectionCallbacks()}
      />,
    );

    const decisions = screen.getByRole("group", { name: "Frame decision" });
    await user.click(
      within(decisions).getByRole("button", { name: "Accept frame" }),
    );
    await user.click(
      within(decisions).getByRole("button", { name: "Mark empty" }),
    );
    await user.click(
      within(decisions).getByRole("button", { name: "Mark unusable" }),
    );
    expect(onAccept).toHaveBeenCalledOnce();
    expect(onMarkEmpty).toHaveBeenCalledOnce();
    expect(onMarkUnusable).toHaveBeenCalledOnce();
  });

  it("renders proposal previews, details, and ignore regions", () => {
    render(
      <WorkbenchProposalColumn
        frame={frame}
        candidates={frame.outcome.candidates}
        scene={null}
        activeTool="visible_regions"
        sourceUrl="/frame.jpg"
        frameWidth={100}
        frameHeight={100}
        readOnly
        selection={null}
        editor={null}
        editorError={null}
        selectedCandidateIds={[]}
        onSelectCandidate={vi.fn()}
        onSelectVirtualCard={vi.fn()}
        onSceneAction={vi.fn()}
        proposalSlot={null}
      />,
    );

    const proposal = screen.getByRole("button", { name: "Select proposal 1" });
    expect(
      within(proposal).getByRole("img", { name: "Proposal 1 crop preview" }),
    ).toBeInTheDocument();
    expect(
      within(proposal).getByText("Detector suggestion"),
    ).toBeInTheDocument();
    expect(within(proposal).getByText("Unknown")).toBeInTheDocument();
    expect(within(proposal).getByText("Box")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select ignore region 1" }),
    ).toBeInTheDocument();
  });
});
