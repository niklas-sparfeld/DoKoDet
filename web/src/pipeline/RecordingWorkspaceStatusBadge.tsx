import styles from "../App.module.css";
import { formatIdentifier } from "./recordingWorkspaceFormatting";

export function RecordingWorkspaceStatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {formatIdentifier(value)}
    </span>
  );
}
