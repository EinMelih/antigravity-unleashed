import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AttentionQueue } from "@/features/automation/attention-queue";
import type { AttentionQueueEntry } from "@/features/automation/model";

function entry(
  id: string,
  target: AttentionQueueEntry["target"] = { kind: "information" },
): AttentionQueueEntry {
  return {
    id,
    title: `Entscheidung ${id}`,
    consequence: "Ohne Entscheidung wartet die Arbeit.",
    recommendation: "Den aktuellen Stand prüfen.",
    urgency: "normal",
    categoryLabel: "Prüfung",
    projectName: "antigravity-web",
    createdAt: "2026-08-26 12:00:00",
    target,
  };
}

describe("AttentionQueue", () => {
  it("shows every item and routes planning and work without hiding information-only items", () => {
    const onOpenPlanning = vi.fn();
    const onOpenWorkItem = vi.fn();
    const entries = [
      entry("1", { kind: "planning", campaignId: "CMP-1", planningJobId: "PLAN-1" }),
      entry("2", { kind: "work_item", workItemId: "TASK-1" }),
      entry("3"),
      entry("4"),
      entry("5"),
    ];

    render(
      <AttentionQueue
        entries={entries}
        onOpenPlanning={onOpenPlanning}
        onOpenWorkItem={onOpenWorkItem}
      />,
    );

    const queue = screen.getByRole("region", { name: "Braucht deine Entscheidung" });
    expect(within(queue).getAllByRole("listitem")).toHaveLength(5);
    expect(within(queue).getByText("Entscheidung 5")).toBeVisible();
    expect(within(queue).getAllByText("Keine direkte Aktion verfügbar.")).toHaveLength(3);

    fireEvent.click(within(queue).getByRole("button", { name: "Plan öffnen: Entscheidung 1" }));
    fireEvent.click(within(queue).getByRole("button", { name: "Arbeit öffnen: Entscheidung 2" }));

    expect(onOpenPlanning).toHaveBeenCalledWith("CMP-1", "PLAN-1");
    expect(onOpenWorkItem).toHaveBeenCalledWith("TASK-1");
  });

  it("has a calm empty state", () => {
    render(
      <AttentionQueue entries={[]} onOpenPlanning={vi.fn()} onOpenWorkItem={vi.fn()} />,
    );

    expect(screen.getByText("Aktuell braucht nichts deine Entscheidung.")).toBeVisible();
  });
});
