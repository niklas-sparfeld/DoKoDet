import { createPortal } from "react-dom";

import styles from "./App.module.css";

export function Toast({ message }: { message: string }) {
  return createPortal(
    <p className={styles.toast} role="status" aria-live="polite">
      {message}
    </p>,
    document.body,
  );
}
