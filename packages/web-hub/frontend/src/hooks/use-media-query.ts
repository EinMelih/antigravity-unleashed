import { useSyncExternalStore } from "react";

function subscribe(query: string, callback: () => void) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }

  const mediaQuery = window.matchMedia(query);
  mediaQuery.addEventListener("change", callback);
  return () => mediaQuery.removeEventListener("change", callback);
}

function getSnapshot(query: string, fallback: boolean) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return fallback;
  }
  return window.matchMedia(query).matches;
}

export function useMediaQuery(query: string, fallback = false) {
  return useSyncExternalStore(
    (callback) => subscribe(query, callback),
    () => getSnapshot(query, fallback),
    () => fallback,
  );
}
