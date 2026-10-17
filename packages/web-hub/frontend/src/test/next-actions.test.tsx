import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NextActions } from "@/components/next-actions";

describe("NextActions", () => {
  it("puts the current action first and keeps every later action compactly visible", () => {
    render(
      <NextActions
        items={[
          {
            title: "Repository verbunden",
            description: "Das Projekt ist bereit.",
            status: "complete",
          },
          {
            title: "Plan prüfen",
            description: "Prüfe den vorgeschlagenen Ablauf.",
            status: "current",
            actionLabel: "Plan öffnen",
            href: "#/automation",
          },
          {
            title: "Ersten PR umsetzen",
            description: "Anti-Gravity beginnt nach deiner Freigabe.",
            status: "pending",
            actionLabel: "Projekt öffnen",
            href: "#/projects/1",
          },
          {
            title: "Menschlich prüfen",
            description: "Prüfe Änderungen und Tests vor dem Merge.",
            status: "pending",
            actionLabel: "Prüfung öffnen",
            href: "#/automation/review",
          },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Als Nächstes" })).toBeVisible();
    const primary = screen.getByRole("article", { name: "Plan prüfen" });
    expect(within(primary).getByRole("link", { name: "Plan öffnen" })).toHaveAttribute(
      "href",
      "#/automation",
    );

    const following = screen.getByRole("list", { name: "Danach" });
    expect(within(following).getByText("Ersten PR umsetzen")).toBeVisible();
    expect(within(following).getByText("Menschlich prüfen")).toBeVisible();
    expect(screen.queryByText("Repository verbunden")).not.toBeInTheDocument();
    expect(screen.queryByText("Jetzt wichtig")).not.toBeInTheDocument();
  });
});
