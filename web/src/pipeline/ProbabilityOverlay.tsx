import { useEffect, useRef } from "react";

import styles from "../App.module.css";

type ProbabilitySample = {
  time_s: number;
  probability: number;
};

export type ProbabilityMetrics = {
  probabilities: ProbabilitySample[];
  threshold: number;
  eventTimes: number[];
};

export function readProbabilityMetrics(
  state: Record<string, unknown>,
): ProbabilityMetrics | null {
  const metrics = readObject(state.metrics);
  const rawProbabilities = metrics?.probabilities;
  if (!Array.isArray(rawProbabilities)) {
    return null;
  }

  const probabilities = rawProbabilities
    .map((value) => {
      const sample = readObject(value);
      const time = readFiniteNumber(sample?.time_s);
      const probability = readFiniteNumber(sample?.probability);
      return time === null || probability === null
        ? null
        : { time_s: time, probability };
    })
    .filter((sample): sample is ProbabilitySample => sample !== null)
    .sort((left, right) => left.time_s - right.time_s);
  if (probabilities.length === 0) {
    return null;
  }

  const thresholdValue = readFiniteNumber(metrics?.threshold);
  const threshold = thresholdValue === null ? 0.5 : clamp(thresholdValue, 0, 1);
  const rawEvents = metrics?.events;
  const eventTimes = Array.isArray(rawEvents)
    ? rawEvents
        .map((value) => readFiniteNumber(readObject(value)?.time_s))
        .filter((time): time is number => time !== null)
    : [];
  return { probabilities, threshold, eventTimes };
}

export function ProbabilityOverlay({
  metrics,
  runId,
  onClose,
}: {
  metrics: ProbabilityMetrics;
  runId: string;
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousActiveElement = document.activeElement as HTMLElement | null;
    const previousBodyOverflow = document.body.style.overflow;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      previousActiveElement?.focus();
    };
  }, [onClose]);

  const titleId = `probabilities-${runId}-title`;
  return (
    <div
      className={styles.frameOverlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={onClose}
    >
      <div
        className={styles.frameDialog}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.frameDialogHeader}>
          <div>
            <p className={styles.statusLabel}>Processor diagnostics</p>
            <h2 id={titleId}>CardEventNet probabilities</h2>
            <p className={styles.frameDialogMeta}>
              Run <span>{runId}</span>
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className={styles.frameDialogClose}
            aria-label="Close probabilities"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <ProbabilityChart metrics={metrics} />
      </div>
    </div>
  );
}

function ProbabilityChart({ metrics }: { metrics: ProbabilityMetrics }) {
  const width = 960;
  const height = 430;
  const plot = { left: 72, right: 24, top: 24, bottom: 64 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const firstTime = metrics.probabilities[0]?.time_s ?? 0;
  const lastTime = metrics.probabilities.at(-1)?.time_s ?? firstTime;
  const minTime = Math.min(0, firstTime);
  const maxTime = Math.max(lastTime, minTime + 1);
  const timeRange = maxTime - minTime;
  const x = (time: number) =>
    plot.left + ((time - minTime) / timeRange) * plotWidth;
  const y = (probability: number) =>
    plot.top + (1 - clamp(probability, 0, 1)) * plotHeight;
  const probabilityPoints = metrics.probabilities
    .map((sample) => `${x(sample.time_s)},${y(sample.probability)}`)
    .join(" ");
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = Array.from(
    { length: 6 },
    (_, index) => minTime + (timeRange * index) / 5,
  );

  return (
    <div className={styles.probabilityChart}>
      <svg
        className={styles.probabilityChartSvg}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="CardEventNet probability over time chart"
      >
        <title>CardEventNet probability over time</title>
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line
              className={styles.probabilityGridLine}
              x1={plot.left}
              x2={width - plot.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className={styles.probabilityAxisLabel}
              x={plot.left - 12}
              y={y(tick) + 4}
              textAnchor="end"
            >
              {tick.toFixed(2)}
            </text>
          </g>
        ))}
        {xTicks.map((tick, index) => (
          <g key={`x-${tick}`}>
            <line
              className={styles.probabilityGridLine}
              x1={x(tick)}
              x2={x(tick)}
              y1={plot.top}
              y2={height - plot.bottom}
            />
            <text
              className={styles.probabilityAxisLabel}
              x={x(tick)}
              y={height - plot.bottom + 24}
              textAnchor={
                index === 0 ? "start" : index === 5 ? "end" : "middle"
              }
            >
              {formatSeconds(tick)}
            </text>
          </g>
        ))}
        <line
          className={styles.probabilityAxis}
          x1={plot.left}
          x2={plot.left}
          y1={plot.top}
          y2={height - plot.bottom}
        />
        <line
          className={styles.probabilityAxis}
          x1={plot.left}
          x2={width - plot.right}
          y1={height - plot.bottom}
          y2={height - plot.bottom}
        />
        <line
          className={styles.probabilityThreshold}
          x1={plot.left}
          x2={width - plot.right}
          y1={y(metrics.threshold)}
          y2={y(metrics.threshold)}
        />
        {metrics.eventTimes.map((eventTime, index) => (
          <line
            key={`${eventTime}-${index}`}
            className={styles.probabilityEvent}
            x1={x(eventTime)}
            x2={x(eventTime)}
            y1={plot.top}
            y2={height - plot.bottom}
          />
        ))}
        <polyline
          className={styles.probabilityLine}
          points={probabilityPoints}
        />
        <text
          className={styles.probabilityAxisTitle}
          transform={`translate(18 ${plot.top + plotHeight / 2}) rotate(-90)`}
          textAnchor="middle"
        >
          probability
        </text>
        <text
          className={styles.probabilityAxisTitle}
          x={plot.left + plotWidth / 2}
          y={height - 12}
          textAnchor="middle"
        >
          time (s)
        </text>
      </svg>
      <div className={styles.probabilityLegend} aria-label="Chart legend">
        <span>
          <i className={styles.probabilityLegendLine} /> probability
        </span>
        <span>
          <i className={styles.probabilityLegendThreshold} /> threshold (
          {formatPercent(metrics.threshold)})
        </span>
        {metrics.eventTimes.length > 0 ? (
          <span>
            <i className={styles.probabilityLegendEvent} /> prediction
          </span>
        ) : null}
      </div>
      <p className={styles.frameDialogMeta}>
        {metrics.probabilities.length.toLocaleString()} probability samples ·{" "}
        {metrics.eventTimes.length} decoded predictions
      </p>
    </div>
  );
}

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatSeconds(value: number): string {
  return value >= 10 ? value.toFixed(1) : value.toFixed(2);
}
