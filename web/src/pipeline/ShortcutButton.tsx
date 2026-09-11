import styles from "../App.module.css";
import controlStyles from "./ShortcutButton.module.css";

export function ShortcutButton({
  label,
  shortcut,
  ariaShortcut,
  variant = "secondary",
  disabled = false,
  disabledReason,
  onClick,
}: {
  label: string;
  shortcut: string;
  ariaShortcut: string;
  variant?: "primary" | "secondary";
  disabled?: boolean;
  disabledReason?: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`${variant === "primary" ? styles.primaryButton : styles.secondaryButton} ${controlStyles.button}`}
      type="button"
      aria-label={`${label} ${shortcut}`}
      aria-keyshortcuts={ariaShortcut}
      disabled={disabled}
      title={disabled ? disabledReason : undefined}
      onClick={onClick}
    >
      <span>{label}</span>
      <kbd className={controlStyles.shortcutPill}>{shortcut}</kbd>
    </button>
  );
}
