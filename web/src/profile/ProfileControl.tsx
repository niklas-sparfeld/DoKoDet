import { useEffect, useId, useState, type FormEvent } from "react";

import { saveProfileName, useProfileName } from "./profile";
import styles from "./ProfileControl.module.css";

export function ProfileControl() {
  const profileName = useProfileName();
  const [open, setOpen] = useState(false);
  const [draftName, setDraftName] = useState(profileName);
  const inputId = useId();

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    saveProfileName(draftName);
    setOpen(false);
  }

  return (
    <div className={styles.profileControl}>
      <button
        className={styles.profileButton}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={
          profileName === "" ? "Set profile name" : `Profile: ${profileName}`
        }
        title="Profile settings"
        onClick={() => {
          setDraftName(profileName);
          setOpen((current) => !current);
        }}
      >
        <PersonIcon />
        <span className={styles.profileButtonLabel}>
          {profileName === "" ? "Profile" : profileName}
        </span>
      </button>

      {open ? (
        <div
          className={styles.profileMenu}
          role="dialog"
          aria-label="Profile settings"
        >
          <p className={styles.profileEyebrow}>Local profile</p>
          <h2>Reviewer identity</h2>
          <p className={styles.profileDescription}>
            This name is used as the Operator ID and Reviewer ID throughout the
            review workspace.
          </p>
          <form className={styles.profileForm} onSubmit={submit}>
            <label htmlFor={inputId}>Name or ID</label>
            <input
              id={inputId}
              autoFocus
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              placeholder="e.g. niklas"
            />
            <div className={styles.profileActions}>
              <button
                className={styles.profileSecondaryButton}
                type="button"
                onClick={() => {
                  setDraftName(profileName);
                  setOpen(false);
                }}
              >
                Cancel
              </button>
              <button className={styles.profilePrimaryButton} type="submit">
                Save profile
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function PersonIcon() {
  return (
    <svg
      className={styles.profileIcon}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="3.25" />
      <path d="M5.75 19.25c.7-3.03 2.8-4.75 6.25-4.75s5.55 1.72 6.25 4.75" />
    </svg>
  );
}
