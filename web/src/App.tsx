import styles from "./App.module.css";

export function App() {
  return (
    <main className={styles.shell}>
      <p className={styles.eyebrow}>DokoDetector</p>
      <h1>Round analysis timeline</h1>
      <p className={styles.description}>
        The typed frontend foundation is ready for the analysis view.
      </p>
    </main>
  );
}
