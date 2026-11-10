import { ProfileControl } from "../profile/ProfileControl";
import styles from "../App.module.css";
import { RecordingEventSetEditor } from "./RecordingEventSetEditor";

export function RecordingEventSetPage({
  recordingId,
}: {
  recordingId: string;
}) {
  return (
    <main className={`${styles.shell} ${styles.recordingsPage}`}>
      <header className={styles.recordingsHeader}>
        <div>
          <p className={styles.eyebrow}>Recording folder</p>
          <h1>Event sets</h1>
        </div>
        <a href={`/recordings/${encodeURIComponent(recordingId)}`}>
          Open recording workspace
        </a>
        <ProfileControl />
      </header>
      <RecordingEventSetEditor recordingId={recordingId} />
    </main>
  );
}
