import { useSyncExternalStore } from "react";

export const hubRoutes = [
  "/studio",
  "/chats",
  "/automation",
  "/more",
  "/scheduled-tasks",
  "/help",
  "/system",
  "/settings",
  "/knowledge",
  "/api-logs",
] as const;

export type HubRoute = (typeof hubRoutes)[number];
export type ProjectRoute = `/projects/${number}`;
export type NewProjectRoute = "/projects/new";
export type AppRoute = HubRoute | ProjectRoute | NewProjectRoute;

function isHubRoute(value: string): value is HubRoute {
  return hubRoutes.some((route) => route === value);
}

function getHashRoute(): AppRoute {
  const value = window.location.hash.replace(/^#/, "") || "/studio";
  if (isHubRoute(value)) return value;
  if (value === "/projects/new") return value;
  if (/^\/projects\/\d+$/.test(value)) return value as ProjectRoute;
  return "/studio";
}

function subscribeToHashRoute(onStoreChange: () => void) {
  window.addEventListener("hashchange", onStoreChange);
  return () => window.removeEventListener("hashchange", onStoreChange);
}

export function routeHref(route: AppRoute) {
  return `#${route}`;
}

export function useHubRoute() {
  return useSyncExternalStore<AppRoute>(
    subscribeToHashRoute,
    getHashRoute,
    () => "/studio",
  );
}
