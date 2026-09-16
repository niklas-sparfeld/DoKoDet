import styles from "../App.module.css";
import { formatIdentifier } from "./recordingWorkspaceFormatting";

export function RecordingWorkspaceStatusBadge({
  value,
  label,
}: {
  value: string;
  label?: string;
}) {
  return (
    <span className={styles.status} data-state={value}>
      {label ?? formatIdentifier(value)}
    </span>
  );
}
