import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { usePageEntrance } from "@/hooks/use-page-entrance";

function Page({ route }: { route: string }) {
  const ref = usePageEntrance(route);
  return <div ref={ref}>{route}</div>;
}

function PageWithStaleAnimationStyles({ route }: { route: string }) {
  const ref = usePageEntrance(route);
  return <div ref={ref} style={{ opacity: 0, transform: "translateY(8px)" }}>{route}</div>;
}

describe("usePageEntrance", () => {
  it("resets the document scroll position on every route change", () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const view = render(<Page route="/studio" />);
    expect(scrollTo).toHaveBeenLastCalledWith({ top: 0, left: 0, behavior: "auto" });

    view.rerender(<Page route="/projects/51" />);
    expect(scrollTo).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });

  it("clears stale entrance styles when reduced motion disables animation", () => {
    vi.stubGlobal("scrollTo", vi.fn());
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));

    const view = render(<PageWithStaleAnimationStyles route="/studio" />);
    const page = view.getByText("/studio");

    expect(page.style.opacity).toBe("");
    expect(page.style.transform).toBe("");
    vi.unstubAllGlobals();
  });
});
