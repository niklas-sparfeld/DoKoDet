import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import styles from "../App.module.css";

export type TimelineRailSeekingControl = {
  label: string;
  ariaLabel?: string;
  symbol: string;
  shortcut: string;
  ariaShortcut?: string;
  ariaPressed?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
};

export type TimelineRailSeekingGroup = {
  label: string;
  controls: readonly TimelineRailSeekingControl[];
};

export function useTimelineRailSeekingSlot(): HTMLElement | null {
  const [slot, setSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSlot(
        document.querySelector<HTMLElement>(
          '[data-timeline-seeking-slot="true"]',
        ),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  return slot;
}

export function useTimelineRailReviewControlsSlot(): HTMLElement | null {
  const [slot, setSlot] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSlot(
        document.querySelector<HTMLElement>(
          '[data-timeline-review-controls-slot="true"]',
        ),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  return slot;
}

export function TimelineRailSeekingPortal({
  slot,
  groups,
}: {
  slot: HTMLElement;
  groups: readonly TimelineRailSeekingGroup[];
}) {
  return createPortal(<TimelineRailSeekingControls groups={groups} />, slot);
}

export function TimelineRailSeekingControls({
  groups,
}: {
  groups: readonly TimelineRailSeekingGroup[];
}) {
  return (
    <div
      className={styles.recordingTimelineSeekingControls}
      data-timeline-seeking-controls="true"
    >
      {groups.map((group) => (
        <div
          key={group.label}
          className={styles.recordingTimelineSeekingGroup}
          role="group"
          aria-label={group.label}
        >
          {group.controls.map((control) => {
            const shortcutLabel = formatSeekingShortcut(control.shortcut);
            const tooltip =
              control.disabled && control.disabledReason !== undefined
                ? `${control.disabledReason} (${shortcutLabel})`
                : `${control.label} (${shortcutLabel})`;
            return (
              <button
                key={control.label}
                className={styles.recordingTimelineSeekingButton}
                type="button"
                aria-label={`${control.ariaLabel ?? control.label} ${shortcutLabel}`}
                aria-keyshortcuts={control.ariaShortcut ?? control.shortcut}
                aria-pressed={control.ariaPressed}
                disabled={control.disabled}
                title={tooltip}
                onClick={control.onClick}
              >
                <span aria-hidden="true">{control.symbol}</span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function formatSeekingShortcut(shortcut: string): string {
  return shortcut
    .replaceAll("ArrowLeft", "←")
    .replaceAll("ArrowRight", "→")
    .replaceAll("Alt+", "⌥")
    .replaceAll("Meta+", "⌘")
    .replaceAll("Shift+", "⇧");
}
