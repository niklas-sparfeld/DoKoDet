import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import styles from "./JobStartActions.module.css";

export type JobStartAction = {
  id: string;
  label: string;
  description: string;
  expectedOutput: string;
  sections: Array<{ title: string; content: ReactNode }>;
};

type Props = {
  actions: JobStartAction[];
  loading?: boolean;
  submitting?: boolean;
  validationErrors?: string[];
  canSubmit?: boolean;
  onStart?: (
    action: JobStartAction,
    event: FormEvent<HTMLFormElement>,
  ) => boolean | Promise<boolean> | void | Promise<void>;
};

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function JobStartActions({
  actions,
  loading = false,
  submitting = false,
  validationErrors = [],
  canSubmit = true,
  onStart,
}: Props) {
  const [active, setActive] = useState<JobStartAction | null>(null);
  const currentActive = active
    ? (actions.find((action) => action.id === active.id) ?? null)
    : null;
  const opener = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (active) {
      closeButton.current?.focus();
      return;
    }
    opener.current?.focus();
  }, [active]);

  function close() {
    if (submitting) return;
    setActive(null);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const elements = dialog.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (!elements?.length) return;
    const first = elements[0];
    const last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <>
      <section className={styles.actions} aria-label="Actions">
        <h2>Actions</h2>
        {actions.map((action) => (
          <button
            className={styles.actionButton}
            key={action.id}
            type="button"
            onClick={(event) => {
              opener.current = event.currentTarget;
              setActive(action);
            }}
          >
            {action.label}…
          </button>
        ))}
      </section>
      {currentActive ? (
        <div
          className={styles.backdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close();
          }}
        >
          <div
            ref={dialog}
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="job-start-title"
            aria-describedby="job-start-description"
            onKeyDown={handleKeyDown}
          >
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!submitting && canSubmit) {
                  void Promise.resolve(onStart?.(currentActive, event)).then(
                    (accepted) => {
                      if (accepted === true) setActive(null);
                    },
                  );
                }
              }}
            >
              <header className={styles.header}>
                <div>
                  <p className={styles.eyebrow}>Start work</p>
                  <h2 id="job-start-title">{currentActive.label}</h2>
                </div>
                <button
                  ref={closeButton}
                  aria-label="Close"
                  type="button"
                  disabled={submitting}
                  onClick={close}
                >
                  Close
                </button>
              </header>
              <p id="job-start-description">{currentActive.description}</p>
              <div className={styles.body}>
                {validationErrors.length ? (
                  <section
                    aria-labelledby="job-start-errors-title"
                    className={styles.errors}
                  >
                    <h3 id="job-start-errors-title">
                      Fix these fields before starting
                    </h3>
                    <ul>
                      {validationErrors.map((error) => (
                        <li key={error}>{error}</li>
                      ))}
                    </ul>
                  </section>
                ) : null}
                {loading ? (
                  <p role="status">Loading available choices…</p>
                ) : null}
                {currentActive.sections.map((section) => (
                  <section
                    className={styles.section}
                    aria-label={section.title}
                    key={section.title}
                  >
                    <h3>{section.title}</h3>
                    {section.content}
                  </section>
                ))}
                <section
                  className={styles.section}
                  aria-label="Expected output"
                >
                  <h3>Expected output</h3>
                  <p>{currentActive.expectedOutput}</p>
                </section>
              </div>
              {submitting ? (
                <p role="status">
                  Starting {currentActive.label.toLowerCase()}…
                </p>
              ) : null}
              <footer className={styles.footer}>
                <button type="button" disabled={submitting} onClick={close}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || submitting || !canSubmit}
                >
                  {submitting
                    ? "Starting…"
                    : `Start ${currentActive.label.toLowerCase()}`}
                </button>
              </footer>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
