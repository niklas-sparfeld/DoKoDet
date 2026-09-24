import { createPortal } from "react-dom";
import { useEffect, useState } from "react";

import styles from "./App.module.css";

export function Toast({ message }: { message: string }) {
  const [dismissedMessage, setDismissedMessage] = useState<string | null>(null);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDismissedMessage(message);
    }, 10_000);

    return () => window.clearTimeout(timeoutId);
  }, [message]);

  if (dismissedMessage === message) {
    return null;
  }

  return createPortal(
    <div className={styles.toast} role="status" aria-live="polite">
      <span>{message}</span>
      <button
        className={styles.toastClose}
        type="button"
        aria-label="Close notification"
        onClick={() => setDismissedMessage(message)}
      >
        ×
      </button>
    </div>,
    document.body,
  );
}
