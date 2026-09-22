import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PoseBasedVisibleCardEditor } from "./PoseBasedVisibleCardEditor";
import type { EditableFrame } from "./PipelineVisibleCardTypes";
import {
  projectImagePointToTable,
  type PoseCard,
  type PoseSceneEnvelope,
} from "./PoseBasedVisibleCardScene";

const DIGEST = "a".repeat(64);

function scene(): PoseSceneEnvelope {
  const poses = [
    {
      schema_version: "card-pose/v1" as const,
      card_id: "card-a",
      center: [0, 0] as [number, number],
      rotation_degrees: 0,
      source_suggestion_id: "suggestion-a",
      fit_diagnostics_digest: DIGEST,
    },
    {
      schema_version: "card-pose/v1" as const,
      card_id: "card-b",
      center: [2, 0] as [number, number],
      rotation_degrees: 0,
      source_suggestion_id: "suggestion-b",
      fit_diagnostics_digest: DIGEST,
    },
  ];
  const makeScene = () => ({
    schema_version: "reviewed-card-scene/v1" as const,
    source_frame_id: "frame-1",
    source_frame_width: 100,
    source_frame_height: 80,
    calibration_revision_id: "calibration-1",
    calibration_digest: DIGEST,
    poses: poses.map((pose) => ({
      ...pose,
      center: [...pose.center] as [number, number],
    })),
    stacking_order: {
      schema_version: "card-stacking-order/v1" as const,
      card_ids: ["card-a", "card-b"],
      uncertain_edges: [],
      contradictions: [],
    },
    derivation_recipe_version: "card-plane-derived-regions/v1",
    scene_digest: DIGEST,
  });
  return {
    schema_version: "reviewed-card-scene-editor/v1",
    scene: makeScene(),
    initialized_scene: makeScene(),
    projection: {
      table_to_image_homography: [
        [20, 0, 50],
        [0, 20, 40],
        [0, 0, 1],
      ],
      card_short_size: 1,
      card_long_size: 1.5,
    },
    card_review_states: poses.map((pose) => ({
      card_id: pose.card_id,
      source: "proposal" as const,
      proposal_id: `proposal-${pose.card_id}`,
      state: "pending" as const,
    })),
    completion_state: "pending",
    completion_reason: null,
  };
}

function changedScene(): PoseSceneEnvelope {
  const next = scene();
  next.scene.scene_digest = "b".repeat(64);
  return next;
}

function frame(): EditableFrame {
  return {
    itemId: "event-1",
    baseItemId: null,
    reviewState: "pending",
    outcome: {
      event_id: "event-1",
      frame_identity: {
        requested_time_us: 100,
        frame_index: 1,
        presentation_timestamp_us: 100,
        width: 100,
        height: 80,
        image_sha256: DIGEST,
      },
      status: "detected",
      candidates: [],
      ignored_regions: [],
      error: null,
    },
  };
}

describe("PoseBasedVisibleCardEditor", () => {
  it("saves one scene command when a standard card is added", async () => {
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
      />,
    );

    expect(
      screen.getByRole("application", { name: "Rectified virtual table" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("How to review and refine"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Source frame background" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("application", { name: "Rectified virtual table" }),
    ).toHaveAttribute("viewBox", "-4 -3.5 8.75 7");
    fireEvent.click(
      screen.getByRole("button", { name: "Add standard-size card" }),
    );

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0].scene.poses).toHaveLength(3);
    expect(onChange.mock.calls[0][1]).toContain("added");
  });

  it("renders the front card above the back card in the rectified view", () => {
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );

    const cards = screen.getAllByRole("button", {
      name: /Virtual table card/,
    });
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Virtual table card card-b",
      "Virtual table card card-a",
    ]);
    expect(
      cards
        .map((card) => card.querySelector("polygon"))
        .map((polygon) => polygon?.getAttribute("fill-opacity")),
    ).toEqual(["0.25", "0.25"]);
    expect(
      cards
        .map((card) => card.querySelector("polygon"))
        .map((polygon) => polygon?.getAttribute("stroke-width")),
    ).toEqual(["0.02", "0.035"]);
  });

  it("renders the selected card above higher cards for interaction", async () => {
    const overlappingScene = scene();
    overlappingScene.scene.poses[1].center = [0.25, 0];
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={overlappingScene}
        readOnly={false}
        onChange={onChange}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Virtual table card card-b" }),
    );

    expect(
      screen
        .getAllByRole("button", { name: /Virtual table card/ })
        .map((card) => card.getAttribute("aria-label")),
    ).toEqual(["Virtual table card card-a", "Virtual table card card-b"]);
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });
    Object.defineProperty(table, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
        right: 100,
        bottom: 100,
      }),
    });
    fireEvent.pointerDown(screen.getByLabelText("Rotate card-b"), {
      pointerId: 12,
      clientX: 50,
      clientY: 50,
    });
    fireEvent.pointerMove(table, {
      pointerId: 12,
      clientX: 60,
      clientY: 40,
    });
    fireEvent.pointerUp(table, { pointerId: 12 });

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(
      onChange.mock.calls[0][0].scene.poses.find(
        (pose: PoseCard) => pose.card_id === "card-b",
      )?.rotation_degrees,
    ).not.toBe(0);
  });

  it("warps the source frame into the table plane for the rectified view", () => {
    const perspectiveScene = scene();
    perspectiveScene.projection.table_to_image_homography = [
      [20, 3, 50],
      [2, 20, 40],
      [0.08, 0.04, 1],
    ];

    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={perspectiveScene}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );

    const background = screen.getByRole("img", {
      name: "Source frame background",
    });
    expect(background).toHaveAttribute("opacity", "1");
    const patches = background.querySelectorAll("g[transform]");
    expect(patches.length).toBeGreaterThan(1);
    expect(
      new Set(Array.from(patches, (patch) => patch.getAttribute("transform")))
        .size,
    ).toBeGreaterThan(1);
    const transform = patches[0].getAttribute("transform");
    const coefficients = transform
      ?.slice("matrix(".length, -1)
      .split(" ")
      .map(Number);
    const topLeft = projectImagePointToTable(
      [0, 0],
      perspectiveScene.projection.table_to_image_homography,
    );
    expect(coefficients).toBeDefined();
    expect(topLeft).not.toBeNull();
    expect(coefficients?.[4]).toBeCloseTo(topLeft![0]);
    expect(coefficients?.[5]).toBeCloseTo(topLeft![1]);
  });

  it("uses the same editor action for keyboard nudges", async () => {
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
      />,
    );

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Virtual table card card-a" }),
      {
        key: "ArrowRight",
      },
    );

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0].scene.poses[0].center[0]).toBe(0.025);
  });

  it("switches views without changing the scene and exposes card decisions", async () => {
    const onChange = vi.fn();
    const onCardDecision = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
        onCardDecision={onCardDecision}
      />,
    );

    expect(
      screen.getByRole("application", { name: "Rectified virtual table" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(
      screen.getByRole("img", { name: "Projected card scene" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("application", { name: "Rectified virtual table" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rectified table" }));
    fireEvent.click(screen.getByRole("button", { name: "Accept card" }));
    expect(onCardDecision).toHaveBeenCalledWith("card-a", "accept");
  });

  it("keeps the selected view when the selected frame changes", async () => {
    const rendered = render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(
      screen.getByRole("img", { name: "Projected card scene" }),
    ).toBeInTheDocument();

    rendered.rerender(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={{ ...frame(), itemId: "event-2" }}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("img", { name: "Projected card scene" }),
    ).toBeInTheDocument();
  });

  it("does not move a card for a click-sized pointer movement", async () => {
    const onChange = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
      />,
    );
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });
    const card = screen.getByRole("button", {
      name: "Virtual table card card-a",
    });
    Object.defineProperty(table, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
        right: 100,
        bottom: 100,
      }),
    });

    fireEvent.pointerDown(card, { pointerId: 8, clientX: 50, clientY: 50 });
    fireEvent.pointerMove(table, { pointerId: 8, clientX: 52, clientY: 52 });
    fireEvent.pointerUp(table, { pointerId: 8, clientX: 52, clientY: 52 });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("clears the selected card when the empty table is clicked", () => {
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });

    expect(screen.getByLabelText("Rotate card-a")).toBeInTheDocument();
    fireEvent.click(table);
    expect(screen.queryByLabelText("Rotate card-a")).not.toBeInTheDocument();
  });

  it("zooms the table under the wheel or trackpad pointer", () => {
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });
    Object.defineProperty(table, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
        right: 100,
        bottom: 100,
      }),
    });
    const initialViewBox = table.getAttribute("viewBox");

    fireEvent.wheel(screen.getByRole("button", { name: "Zoom in" }), {
      deltaY: -120,
    });
    expect(table.getAttribute("viewBox")).toBe(initialViewBox);

    fireEvent.wheel(table, {
      clientX: 50,
      clientY: 50,
      deltaY: -120,
      ctrlKey: true,
    });

    expect(table.getAttribute("viewBox")).not.toBe(initialViewBox);
    expect(Number(table.getAttribute("viewBox")?.split(" ")[2])).toBeLessThan(
      6.75,
    );
  });

  it("pans the virtual table by dragging its empty surface", () => {
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
      />,
    );
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });
    Object.defineProperty(table, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
        right: 100,
        bottom: 100,
      }),
    });

    fireEvent.pointerDown(table, {
      button: 0,
      clientX: 50,
      clientY: 50,
      pointerId: 9,
    });
    fireEvent.pointerMove(table, {
      clientX: 60,
      clientY: 70,
      pointerId: 9,
    });
    fireEvent.pointerUp(table, { pointerId: 9 });

    expect(table.getAttribute("viewBox")).toBe("-4.875 -4.9 8.75 7");
  });

  it("keeps the viewport state when the card scene or mapping changes", () => {
    const onTableViewStateChange = vi.fn();
    const { rerender } = render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
        tableViewState={{ zoom: 1, pan: [0, 0] }}
        onTableViewStateChange={onTableViewStateChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(onTableViewStateChange).toHaveBeenLastCalledWith({
      zoom: 1.25,
      pan: [0, 0],
    });

    rerender(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
        tableViewState={{ zoom: 1.25, pan: [0, 0] }}
        onTableViewStateChange={onTableViewStateChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Pan table right" }));
    expect(onTableViewStateChange).toHaveBeenLastCalledWith({
      zoom: 1.25,
      pan: [0.5, 0],
    });

    rerender(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={{ ...frame(), itemId: "event-2" }}
        scene={changedScene()}
        readOnly={false}
        onChange={vi.fn()}
        tableViewState={{ zoom: 1.25, pan: [0.5, 0] }}
        onTableViewStateChange={onTableViewStateChange}
        candidateCalibration={{
          table_to_image: [
            [20, 0, 50],
            [0, 20, 40],
            [0, 0, 1],
          ],
          card_short_size: 1,
          card_long_size: 1.5,
        }}
      />,
    );

    const viewBox = screen
      .getByRole("application", { name: "Rectified virtual table" })
      .getAttribute("viewBox")
      ?.split(" ")
      .map(Number);
    expect(viewBox).toEqual([
      expect.closeTo(-2.625, 10),
      expect.closeTo(-2.8, 10),
      expect.closeTo(7, 10),
      expect.closeTo(5.6, 10),
    ]);
  });

  it("creates one numeric anchor command without changing card pose geometry", () => {
    const onChange = vi.fn();
    const onAnchorCommand = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={onChange}
        onAnchorCommand={onAnchorCommand}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Refine mapping" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Anchor X" }), {
      target: { value: "-0.75" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply anchor edit" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(onAnchorCommand).toHaveBeenCalledTimes(1);
    expect(onAnchorCommand.mock.calls[0][0]).toMatchObject({
      operation: "set_corners",
      state: "adjusted",
      moved_corner: 0,
      constraint: "diagonal",
    });
  });

  it("cancels an anchor gesture on Escape without emitting a command", () => {
    const onAnchorCommand = vi.fn();
    render(
      <PoseBasedVisibleCardEditor
        recordingId="recording-1"
        frame={frame()}
        scene={scene()}
        readOnly={false}
        onChange={vi.fn()}
        onAnchorCommand={onAnchorCommand}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Refine mapping" }));
    const table = screen.getByRole("application", {
      name: "Rectified virtual table",
    });
    const handle = screen.getByRole("button", {
      name: "Anchor corner 1 for card card-a",
    });
    Object.defineProperty(table, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        top: 0,
        width: 100,
        height: 100,
        right: 100,
        bottom: 100,
      }),
    });
    fireEvent.pointerDown(handle, { pointerId: 7 });
    fireEvent.pointerMove(table, { pointerId: 7, clientX: 5, clientY: 5 });
    fireEvent.keyDown(table, { key: "Escape" });
    fireEvent.pointerUp(table, { pointerId: 7 });

    expect(onAnchorCommand).not.toHaveBeenCalled();
  });
});
