import { useSyncExternalStore } from "react";

export const PROFILE_NAME_STORAGE_KEY = "dokodetector.profile.name";

export const PROFILE_NAME_CHANGE_EVENT = "dokodetector-profile-name-change";
let fallbackProfileName = "";

export function readProfileName(): string {
  if (typeof window === "undefined") return "";

  try {
    return window.localStorage.getItem(PROFILE_NAME_STORAGE_KEY) ?? "";
  } catch {
    return fallbackProfileName;
  }
}

export function saveProfileName(value: string): void {
  if (typeof window === "undefined") return;

  const name = value.trim();
  fallbackProfileName = name;
  try {
    if (name === "") {
      window.localStorage.removeItem(PROFILE_NAME_STORAGE_KEY);
    } else {
      window.localStorage.setItem(PROFILE_NAME_STORAGE_KEY, name);
    }
  } catch {
    // The UI can still use the value for this session when storage is blocked.
  }
  window.dispatchEvent(new Event(PROFILE_NAME_CHANGE_EVENT));
}

export function subscribeToProfileName(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(PROFILE_NAME_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(PROFILE_NAME_CHANGE_EVENT, onStoreChange);
  };
}

export function useProfileName(): string {
  return useSyncExternalStore(
    subscribeToProfileName,
    readProfileName,
    () => "",
  );
}
