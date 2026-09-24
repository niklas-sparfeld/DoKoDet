import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { VisibleCardReviewWorkbench } from "./VisibleCardReviewWorkbench";
import * as fixtures from "./VisibleCardReviewWorkbenchFixtures";
import type { CalibrationRefinementResponse } from "../api/client";
const { calibrationRefinement, frame } = fixtures;

describe("VisibleCardReviewWorkbench", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("draws the selected anchor above overlapping mapping anchors", () => {
    const overlapping = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ anchor_id: string; card_id: string }> };
    };
    overlapping.draft.anchors.push({
      ...overlapping.draft.anchors[0],
      anchor_id: "anchor-2",
      card_id: "other-card",
    });
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={overlapping}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Adjust calibration anchor 1 for anchor-1",
      }),
    );
    const layer = document.querySelector('[data-workbench-layer="mapping"]');
    expect(layer?.lastElementChild).toHaveAttribute(
      "data-anchor-id",
      "anchor-1",
    );
  });

  it("marks corrected cards and points the operator to the next pending card", () => {
    const adjusted = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: {
        anchors: Array<{
          anchor_id: string;
          card_id: string;
          state: string;
          weight_class?: string;
        }>;
      };
    };
    adjusted.draft.anchors[0].state = "adjusted";
    adjusted.draft.anchors[0].weight_class = "adjusted";

    const { unmount } = render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{ activeTool: "mapping" }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={adjusted}
        proposalSlot={document.body}
      />,
    );

    expect(screen.getByText("Human corrected")).toBeInTheDocument();
    expect(
      document.querySelector(
        '[aria-label="Visible-card proposals"] li[data-human-corrected="true"]',
      ),
    ).toBeInTheDocument();

    unmount();
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{ activeTool: "visible_regions" }}
        enabledEditTools={["visible_regions"]}
        proposalSlot={document.body}
      />,
    );
    expect(screen.getByText("Next to review")).toBeInTheDocument();
  });

  it("shrinks mapping strokes and corner handles with zoom", () => {
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
          viewpoint: "rectified",
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
      />,
    );

    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({
      bottom: 100,
      height: 100,
      left: 0,
      right: 100,
      top: 0,
      width: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    const handle = screen.getByRole("button", {
      name: "Adjust calibration anchor 1 for anchor-1",
    });
    const initialRadius = Number(handle.getAttribute("r"));
    expect(handle).toHaveAttribute("opacity", "0.5");
    expect(surface.querySelector('[data-projection="current"]')).toBeNull();

    fireEvent.wheel(surface, { deltaY: -240 });

    expect(Number(handle.getAttribute("r"))).toBe(initialRadius / 2);
  });

  it("keeps editable calibration anchor corners when their order differs", () => {
    const reordered = structuredClone(
      calibrationRefinement,
    ) as CalibrationRefinementResponse & {
      draft: { anchors: Array<{ quadrilateral: number[][] }> };
    };
    reordered.draft.anchors[0].quadrilateral = [
      [60, 40],
      [60, 60],
      [40, 60],
      [40, 40],
    ];
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={frame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={reordered}
        onAnchorCommand={vi.fn()}
      />,
    );
    expect(
      screen.getAllByRole("button", {
        name: /^Adjust calibration anchor \d for anchor-1$/,
      }),
    ).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /Adjust mapped card corner/i }),
    ).not.toBeInTheDocument();
  });

  it.each(["camera", "rectified"] as const)(
    "keeps a candidate projection in place when only table coordinates change in %s view",
    (viewpoint) => {
      render(
        <VisibleCardReviewWorkbench
          recordingId="recording-1"
          frame={frame}
          readOnly={false}
          initialPreferences={{
            activeTool: "mapping",
            enabledLayers: ["mapping", "virtual_cards"],
            viewpoint,
          }}
          enabledEditTools={["mapping"]}
          candidateCalibration={{
            table_to_image: [
              [1, 0, -100],
              [0, 1, -100],
              [0, 0, 1],
            ],
            card_short_size: 10,
            card_long_size: 20,
          }}
        />,
      );
      const current = document.querySelector(
        '[data-workbench-layer="virtual_cards"] polygon[data-card-id="card-1"]',
      );
      const candidate = document.querySelector(
        '[data-projection="candidate"] polygon',
      );
      expect(candidate).toHaveAttribute(
        "points",
        current?.getAttribute("points"),
      );
    },
  );

  it("keeps calibration anchor handles smaller than a card on a unit-scale table", () => {
    const unitFrame = structuredClone(frame);
    unitFrame.outcome.card_scene!.projection.card_short_size = 1;
    unitFrame.outcome.card_scene!.projection.card_long_size = 1.5;
    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={unitFrame}
        readOnly={false}
        initialPreferences={{
          activeTool: "mapping",
          enabledLayers: ["mapping"],
          viewpoint: "rectified",
        }}
        enabledEditTools={["mapping"]}
        calibrationRefinement={calibrationRefinement}
      />,
    );

    const handles = screen.getAllByRole("button", {
      name: /Adjust calibration anchor/i,
    });
    expect(handles).toHaveLength(4);
    expect(Number(handles[0].getAttribute("r"))).toBeLessThan(0.1);
  });

  it("shows numbered stack badges and lets the sidebar reorder cards", async () => {
    const multiCardFrame = structuredClone(frame);
    const cardScene = multiCardFrame.outcome.card_scene!;
    const secondCard = {
      ...cardScene.scene.poses[0],
      card_id: "card-2",
      center: [60, 60] as [number, number],
    };
    cardScene.scene.poses[0].center = [15, 15];
    cardScene.projection.table_to_image_homography = [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0.01, 1],
    ];
    cardScene.scene.poses.push(secondCard);
    cardScene.scene.stacking_order.card_ids.push(secondCard.card_id);
    cardScene.initialized_scene.poses.push(secondCard);
    cardScene.initialized_scene.stacking_order.card_ids.push(
      secondCard.card_id,
    );
    const onSceneChange = vi.fn();

    render(
      <VisibleCardReviewWorkbench
        recordingId="recording-1"
        frame={multiCardFrame}
        readOnly={false}
        onSceneChange={onSceneChange}
        proposalSlot={null}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Edit Virtual cards" }));
    expect(
      screen.queryByText("Stack order · Front to back"),
    ).not.toBeInTheDocument();
    const surface = screen.getByRole("img", {
      name: /Rectified visible-card workbench/,
    });
    expect(
      surface.querySelector('[data-stacking-badge-id="card-1"]'),
    ).toHaveAttribute("data-stacking-index", "0");
    expect(
      surface.querySelector('[data-stacking-badge-id="card-2"]'),
    ).toHaveAttribute("data-stacking-index", "1");

    await userEvent.setup().click(
      screen.getByRole("button", {
        name: "Viewpoint: Rectified. Switch to Camera",
      }),
    );
    const cameraSurface = screen.getByRole("img", {
      name: /1 visible-card proposal/,
    });
    const badgeRadii = Array.from(
      cameraSurface.querySelectorAll("[data-card-stacking-badges] circle"),
      (badge) => Number(badge.getAttribute("r")),
    );
    expect(badgeRadii).toHaveLength(2);
    expect(badgeRadii[0]).toBeGreaterThan(4);
    expect(badgeRadii[0]).toBe(badgeRadii[1]);

    const stackOrder = screen.getByRole("region", { name: "Stack order" });
    const firstRow = stackOrder.querySelector(
      '[data-card-id="card-1"][data-stacking-index="0"]',
    );
    const secondRow = stackOrder.querySelector(
      '[data-card-id="card-2"][data-stacking-index="1"]',
    );
    const values = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      getData: (type: string) => values.get(type) ?? "",
      setData: (type: string, value: string) => values.set(type, value),
    };
    fireEvent.dragStart(firstRow!, { dataTransfer });
    fireEvent.drop(secondRow!, { dataTransfer });

    await waitFor(() => expect(onSceneChange).toHaveBeenCalled());
    expect(
      onSceneChange.mock.calls.at(-1)?.[0].scene.stacking_order.card_ids,
    ).toEqual(["card-2", "card-1"]);
  });
});
