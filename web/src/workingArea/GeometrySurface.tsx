import styles from "./GeometrySurface.module.css";

export type GeometryFrameIdentity = {
  sourceId: string;
  frameId: string;
  width: number;
  height: number;
  contentSha256: string;
};

export type GeometryCalibrationIdentity = {
  revisionId: string;
  digest: string;
};

export type GeometryPolygon = {
  kind: "polygon";
  points: readonly (readonly [number, number])[];
};

export type GeometryOverlay = {
  id: string;
  label: string;
  frame: GeometryFrameIdentity;
  calibration: GeometryCalibrationIdentity | null;
  requiresCalibration?: boolean;
  geometry: GeometryPolygon;
};

type Props = {
  frame: GeometryFrameIdentity;
  imageUrl: string;
  overlays: readonly GeometryOverlay[];
  calibration?: GeometryCalibrationIdentity | null;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  viewport?: { zoom: number; x: number; y: number };
  viewpoint?: "source" | "rectified";
};

function sameFrame(
  left: GeometryFrameIdentity,
  right: GeometryFrameIdentity,
): boolean {
  return (
    left.sourceId === right.sourceId &&
    left.frameId === right.frameId &&
    left.width === right.width &&
    left.height === right.height &&
    left.contentSha256 === right.contentSha256
  );
}

function sameCalibration(
  left: GeometryCalibrationIdentity | null,
  right: GeometryCalibrationIdentity | null | undefined,
): boolean {
  return (
    left !== null &&
    right !== null &&
    right !== undefined &&
    left.revisionId === right.revisionId &&
    left.digest === right.digest
  );
}

function canDraw(
  overlay: GeometryOverlay,
  frame: GeometryFrameIdentity,
  calibration: GeometryCalibrationIdentity | null | undefined,
): boolean {
  if (!sameFrame(overlay.frame, frame)) return false;
  if (overlay.requiresCalibration)
    return sameCalibration(overlay.calibration, calibration);
  return (
    overlay.calibration === null ||
    sameCalibration(overlay.calibration, calibration)
  );
}

export function GeometrySurface({
  frame,
  imageUrl,
  overlays,
  calibration = null,
  selectedId = null,
  onSelect,
  viewport = { zoom: 1, x: 0, y: 0 },
  viewpoint = "source",
}: Props) {
  const visibleOverlays = overlays.filter((overlay) =>
    canDraw(overlay, frame, calibration),
  );

  return (
    <section className={styles.surface} aria-label="Spatial evidence surface">
      <div
        className={styles.viewport}
        data-viewpoint={viewpoint}
        style={{
          transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
          transformOrigin: "center",
        }}
      >
        <img
          className={styles.frame}
          src={imageUrl}
          width={frame.width}
          height={frame.height}
          alt="Source frame"
        />
        <svg
          className={styles.geometry}
          viewBox={`0 0 ${frame.width} ${frame.height}`}
          preserveAspectRatio="xMidYMid meet"
          aria-hidden="false"
        >
          {visibleOverlays.map((overlay) => {
            const selectable = onSelect !== undefined;
            const selected = overlay.id === selectedId;
            return (
              <polygon
                key={overlay.id}
                className={selected ? styles.selected : styles.polygon}
                points={overlay.geometry.points
                  .map(([x, y]) => `${x},${y}`)
                  .join(" ")}
                role={selectable ? "button" : undefined}
                tabIndex={selectable ? 0 : undefined}
                aria-label={overlay.label}
                aria-pressed={selectable ? selected : undefined}
                onClick={selectable ? () => onSelect(overlay.id) : undefined}
                onKeyDown={
                  selectable
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelect(overlay.id);
                        }
                      }
                    : undefined
                }
              />
            );
          })}
        </svg>
      </div>
    </section>
  );
}
