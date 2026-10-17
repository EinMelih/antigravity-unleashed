import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ControlFlowMetric } from "@/api/contracts";
import { AutomationMetrics } from "@/features/automation/automation-metrics";


const metrics: ControlFlowMetric[] = [
  {
    key: "planning_outcomes",
    label: "Planung erfolgreich",
    description: "Abgeschlossene Planungsläufe unter allen beendeten Läufen.",
    value: 50,
    unit: "percent",
    numerator: 2,
    denominator: 4,
    sample_size: 4,
    breakdown: { completed: 2, failed: 1, cancelled: 1 },
  },
  {
    key: "human_questions",
    label: "Menschliche Rückfragen",
    description: "Persistierte Planungsfragen.",
    value: 3,
    unit: "count",
    numerator: 3,
    denominator: 2,
    sample_size: 2,
    breakdown: {},
  },
];


describe("AutomationMetrics", () => {
  it("keeps derived quality secondary but exposes value, unit, sample and outcomes", async () => {
    const user = userEvent.setup();
    render(<AutomationMetrics metrics={metrics} />);

    const heading = screen.getByText("Ablaufqualität");
    const details = heading.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    await user.click(heading);

    expect(details).toHaveAttribute("open");
    const section = within(details as HTMLElement);
    expect(section.getByText("50 %")).toBeVisible();
    expect(section.getByText("Anzahl 3")).toBeVisible();
    expect(section.getByText("Stichprobe: 4")).toBeVisible();
    expect(
      section.getByText("2 abgeschlossen · 1 fehlgeschlagen · 1 abgebrochen"),
    ).toBeVisible();
    expect(section.getByText("Abgeschlossene Planungsläufe unter allen beendeten Läufen."))
      .toBeVisible();
  });

  it("shows an honest empty state when no metric has a sample", async () => {
    const user = userEvent.setup();
    render(
      <AutomationMetrics
        metrics={[
          {
            ...metrics[0]!,
            value: null,
            numerator: 0,
            denominator: 0,
            sample_size: 0,
            breakdown: { completed: 0, failed: 0, cancelled: 0 },
          },
        ]}
      />,
    );

    await user.click(screen.getByText("Ablaufqualität"));

    expect(screen.getByText("Noch keine belastbare Stichprobe")).toBeVisible();
    expect(screen.queryByText("0 %")).not.toBeInTheDocument();
  });
});
