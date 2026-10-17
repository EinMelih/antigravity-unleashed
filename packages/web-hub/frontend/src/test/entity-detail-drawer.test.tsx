import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EntityDetailDrawer } from "@/components/entity-detail-drawer";

function tabs(suffix = "") {
  return [
    { id: "overview", label: "Übersicht", content: <p>Übersicht {suffix}</p> },
    { id: "plan", label: "Plan", content: <p>Plan {suffix}</p> },
  ];
}

describe("EntityDetailDrawer", () => {
  it("keeps the selected tab during polling-like rerenders", () => {
    const onOpenChange = vi.fn();
    const view = render(
      <EntityDetailDrawer
        entityKey="TASK-1"
        onOpenChange={onOpenChange}
        open
        tabs={tabs("A")}
        title="Work Item"
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "Plan" }));
    expect(screen.getByText("Plan A")).toBeVisible();

    view.rerender(
      <EntityDetailDrawer
        entityKey="TASK-1"
        onOpenChange={onOpenChange}
        open
        tabs={tabs("B")}
        title="Work Item aktualisiert"
      />,
    );
    expect(screen.getByText("Plan B")).toBeVisible();
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("resets to overview for another entity and closes with Escape", () => {
    const onOpenChange = vi.fn();
    const view = render(
      <EntityDetailDrawer
        entityKey="TASK-1"
        onOpenChange={onOpenChange}
        open
        tabs={tabs("A")}
        title="Erstes Work Item"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Plan" }));
    view.rerender(
      <EntityDetailDrawer
        entityKey="TASK-2"
        onOpenChange={onOpenChange}
        open
        tabs={tabs("B")}
        title="Zweites Work Item"
      />,
    );
    expect(screen.getByText("Übersicht B")).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
