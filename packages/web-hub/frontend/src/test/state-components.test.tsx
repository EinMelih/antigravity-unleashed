import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EmptyState,
  ErrorState,
  LoadingState,
  OfflineState,
} from "@/components/states";

describe("shared data states", () => {
  it("announces loading without requiring motion", () => {
    render(<LoadingState />);
    expect(screen.getByRole("status")).toHaveTextContent("Einen Moment bitte");
  });

  it("renders an explicit empty state", () => {
    render(
      <EmptyState
        description="Für diesen Filter wurden keine Einträge gefunden."
        title="Keine Ergebnisse"
      />,
    );
    expect(screen.getByText("Keine Ergebnisse")).toBeVisible();
  });

  it("offers a visible retry action for errors", () => {
    const retry = vi.fn();
    render(<ErrorState description="Testfehler" onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("uses a distinct offline message", () => {
    render(<OfflineState />);
    expect(screen.getByRole("alert")).toHaveTextContent("Hub nicht erreichbar");
  });
});
