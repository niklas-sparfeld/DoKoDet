import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  GeometrySurface,
  type GeometryFrameIdentity,
  type GeometryOverlay,
} from "./GeometrySurface";

const frame: GeometryFrameIdentity = {
  sourceId: "recording-1",
  frameId: "frame-1",
  width: 640,
  height: 360,
  contentSha256: "a".repeat(64),
};

const region: GeometryOverlay = {
  id: "region-1",
  label: "Visible region 1",
  frame,
  calibration: null,
  geometry: {
    kind: "polygon",
    points: [
      [20, 30],
      [80, 30],
      [80, 90],
    ],
  },
};

describe("GeometrySurface", () => {
  it("draws matching geometry and keeps visible text and controls outside the surface", () => {
    render(
      <GeometrySurface
        frame={frame}
        imageUrl="/frame.jpg"
        overlays={[region]}
      />,
    );

    const surface = screen.getByRole("region", {
      name: "Spatial evidence surface",
    });
    expect(
      within(surface).getByRole("img", { name: "Source frame" }),
    ).toHaveAttribute("src", "/frame.jpg");
    expect(within(surface).getByRole("img")).toHaveAttribute("width", "640");
    expect(within(surface).getByRole("img")).toHaveAttribute("height", "360");
    expect(surface.querySelector("svg")).toHaveAttribute(
      "viewBox",
      "0 0 640 360",
    );
    expect(surface.querySelector("polygon")).toHaveAttribute(
      "points",
      "20,30 80,30 80,90",
    );
    expect(surface.querySelectorAll("button")).toHaveLength(0);
    expect(surface.textContent).toBe("");
  });

  it("suppresses overlays from another exact frame or calibration", () => {
    const otherFrame = { ...frame, frameId: "frame-2" };
    const calibrated: GeometryOverlay = {
      ...region,
      id: "pose-1",
      frame,
      calibration: { revisionId: "cal-r1", digest: "b".repeat(64) },
      requiresCalibration: true,
    };

    const { container, rerender } = render(
      <GeometrySurface
        frame={frame}
        imageUrl="/frame.jpg"
        overlays={[region]}
      />,
    );
    rerender(
      <GeometrySurface
        frame={otherFrame}
        imageUrl="/frame-2.jpg"
        overlays={[region, calibrated]}
        calibration={{ revisionId: "cal-r1", digest: "c".repeat(64) }}
      />,
    );
    expect(container.querySelector("polygon")).toBeNull();

    rerender(
      <GeometrySurface
        frame={frame}
        imageUrl="/frame.jpg"
        overlays={[calibrated]}
        calibration={null}
      />,
    );
    expect(container.querySelector("polygon")).toBeNull();
  });

  it("supports pointer and keyboard selection with accessible names", () => {
    const onSelect = vi.fn();
    render(
      <GeometrySurface
        frame={frame}
        imageUrl="/frame.jpg"
        overlays={[region]}
        selectedId={region.id}
        onSelect={onSelect}
      />,
    );

    const shape = screen.getByRole("button", { name: "Visible region 1" });
    expect(shape).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(shape);
    fireEvent.keyDown(shape, { key: "Enter" });
    fireEvent.keyDown(shape, { key: " " });
    expect(onSelect).toHaveBeenCalledTimes(3);
    expect(onSelect).toHaveBeenCalledWith("region-1");
  });

  it("shows layer patterns and a visible keyboard focus treatment", () => {
    render(
      <GeometrySurface
        frame={frame}
        imageUrl="/frame.jpg"
        overlays={[
          region,
          {
            ...region,
            id: "pile-1",
            label: "Pile region 1",
            pattern: "dashed",
          },
          {
            ...region,
            id: "ignore-1",
            label: "Ignore region 1",
            pattern: "dotted",
          },
        ]}
        onSelect={vi.fn()}
      />,
    );

    const shapes = screen.getAllByRole("button");
    expect(shapes.map((shape) => shape.getAttribute("data-pattern"))).toEqual([
      "solid",
      "dashed",
      "dotted",
    ]);
    expect(shapes[1].getAttribute("class")).toContain("dashed");
    expect(shapes[2].getAttribute("class")).toContain("dotted");
    expect(shapes[0]).toHaveAttribute("tabindex", "0");
  });
});
