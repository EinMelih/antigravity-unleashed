import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutomationStatus } from "@/features/automation/automation-status";
import { automationOverview } from "@/test/automation-fixtures";

describe("AutomationStatus", () => {
  it("shows decisions and system state without exposing the internal work mode", () => {
    const control = automationOverview();
    control.policy.mode = "guided";
    control.policy.paused = true;
    control.summary.human_gates_open = 2;

    render(
      <AutomationStatus
        control={control}
        workersError={false}
        workersLoading={false}
      />,
    );

    const status = screen.getByRole("region", {
      name: "Status der Automatisierung",
    });
    expect(within(status).getByText("Deine Prüfung")).toBeVisible();
    expect(within(status).getByText("2 Entscheidungen offen")).toBeVisible();
    expect(within(status).getByText("Ausführung")).toBeVisible();
    expect(within(status).getByText("Pausiert")).toBeVisible();
    expect(within(status).getByText("System")).toBeVisible();
    expect(within(status).getByText("Wird geprüft")).toBeVisible();
    expect(within(status).queryByText("Arbeitsmodus")).not.toBeInTheDocument();
    expect(within(status).queryByText("guided", { exact: false })).not.toBeInTheDocument();
    expect(within(status).queryByText("Worker")).not.toBeInTheDocument();
  });
});
