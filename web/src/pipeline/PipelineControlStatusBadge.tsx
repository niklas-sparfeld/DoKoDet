import styles from "../App.module.css";

export function PipelineControlStatusBadge({ value }: { value: string }) {
  return (
    <span className={styles.status} data-state={value}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
