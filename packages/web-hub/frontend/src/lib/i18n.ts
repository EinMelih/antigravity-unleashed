import { useSyncExternalStore } from "react";

export type HubLanguage = "de" | "en";

const STORAGE_KEY = "antigravity_hub_lang";
const EVENT_NAME = "antigravity-hub-lang-change";

export function getHubLanguage(): HubLanguage {
  if (typeof window === "undefined") return "de";
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "en" || raw === "de") return raw;
  } catch {
    // Ignore storage errors in restricted environments
  }
  return "de";
}

export function setHubLanguage(lang: HubLanguage): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Ignore storage errors
  }
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: lang }));
  // Notify any embedded iframes (such as /docs)
  try {
    const iframes = document.querySelectorAll("iframe");
    iframes.forEach((frame) => {
      frame.contentWindow?.postMessage(
        { type: "antigravity-lang", lang },
        "*",
      );
    });
  } catch {
    // Ignore cross-frame errors
  }
}

function subscribeToLanguage(onStoreChange: () => void) {
  if (typeof window === "undefined") return () => {};
  const handler = () => onStoreChange();
  window.addEventListener(EVENT_NAME, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT_NAME, handler);
    window.removeEventListener("storage", handler);
  };
}

export function useHubLanguage(): [HubLanguage, (lang: HubLanguage) => void] {
  const lang = useSyncExternalStore<HubLanguage>(
    subscribeToLanguage,
    getHubLanguage,
    () => "de",
  );
  return [lang, setHubLanguage];
}
