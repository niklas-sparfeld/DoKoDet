import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import styles from "../App.module.css";

export type TimelineRailSeekingControl = {
  label: string;
  symbol: string;
  shortcut: string;
  ariaShortcut: string;
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
          {group.controls.map((control) => (
            <button
              key={control.label}
              className={styles.recordingTimelineSeekingButton}
              type="button"
              aria-label={control.label}
              aria-keyshortcuts={control.ariaShortcut}
              disabled={control.disabled}
              title={
                control.disabled
                  ? control.disabledReason
                  : `${control.label} · ${control.shortcut}`
              }
              onClick={control.onClick}
            >
              <span aria-hidden="true">{control.symbol}</span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
