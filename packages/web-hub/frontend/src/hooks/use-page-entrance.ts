import { animate } from "animejs";
import { useEffect, useRef } from "react";

export function usePageEntrance(routeKey: string) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    const element = ref.current;
    const reducedMotion = typeof window.matchMedia !== "function"
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!element) return;

    const clearEntranceStyles = () => {
      element.style.removeProperty("opacity");
      element.style.removeProperty("transform");
    };

    // React StrictMode intentionally mounts, cleans up, and mounts effects
    // again in development. Anime.js can otherwise leave the first cancelled
    // animation at opacity 0, so always start from the element's natural style.
    clearEntranceStyles();
    if (reducedMotion) return;

    const animation = animate(element, {
      opacity: [0, 1],
      y: [8, 0],
      duration: 260,
      ease: "out(3)",
    });
    return () => {
      animation.cancel();
      clearEntranceStyles();
    };
  }, [routeKey]);

  return ref;
}
