import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ControlDeployment } from "@/api/contracts";
import { AutomationDeployments } from "@/features/automation/automation-deployments";


const secret = "never-render-this-secret";

const deployment: ControlDeployment = {
  id: "DPL-ROLLBACK-2",
  task_id: "TASK-1",
  project_id: 52,
  environment: "staging",
  status: "running",
  sha: "b".repeat(40),
  artifact_ref: `https://artifacts.example/build.zip?token=${secret}`,
  preview_url: `https://preview.example/app?api_key=${secret}`,
  previous_stable_sha: "a".repeat(40),
  migration: {},
  logs: [
    `deploy started token=${secret}`,
    { access_token: secret, message: "health check pending" },
    "container is warming up",
    "fourth line stays outside the preview",
  ],
  health: { ok: false, message: "Health check pending" },
  approved_by: "owner",
  rollback_of: "DPL-BASE-1",
  started_at: "2026-08-26 10:02:00",
  finished_at: null,
  created_at: "2026-08-26 10:00:00",
  updated_at: "2026-08-26 10:03:00",
};


describe("AutomationDeployments", () => {
  it("shows recorded delivery state without claiming provider success or leaking logs", async () => {
    const user = userEvent.setup();
    render(<AutomationDeployments deployments={[deployment]} />);

    const heading = screen.getByText("Delivery & Deployments");
    const details = heading.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(screen.queryByText(secret, { exact: false })).not.toBeInTheDocument();

    await user.click(heading);

    const section = within(details as HTMLElement);
    expect(
      section.getByText(
        "Vom Control Center aufgezeichneter Zustand – kein Nachweis eines externen Provider-Deployments.",
      ),
    ).toBeVisible();
    expect(section.getByText("Staging")).toBeVisible();
    const running = section.getByText("Läuft (aufgezeichnet)");
    expect(running).toHaveClass("is-running");
    expect(running).not.toHaveClass("is-success");
    expect(section.getByText("b".repeat(40))).toBeVisible();
    expect(section.getByText("a".repeat(40))).toBeVisible();
    expect(section.getByText("https://artifacts.example/build.zip")).toBeVisible();
    expect(section.getByText("https://preview.example/app")).toBeVisible();
    expect(section.getByText("Fehlerhaft gemeldet")).toBeVisible();
    expect(section.getByText("Rollback von DPL-BASE-1")).toBeVisible();
    expect(section.getByText("4 Logeinträge verborgen")).toBeVisible();
    expect(section.getByText("26.08.2026, 10:00")).toBeVisible();
    expect(section.getByText("26.08.2026, 10:02")).toBeVisible();
    expect(section.getByText("Noch offen")).toBeVisible();
    expect(section.queryByText(secret, { exact: false })).not.toBeInTheDocument();

    await user.click(section.getByRole("button", { name: "Gekürzte Logs anzeigen" }));

    expect(section.queryByText(secret, { exact: false })).not.toBeInTheDocument();
    expect(section.getByText("deploy started token=[ausgeblendet]")).toBeVisible();
    expect(section.getByText(/access_token.*\[ausgeblendet\]/)).toBeVisible();
    expect(section.getByText("Weitere 1 Logzeile ausgeblendet.")).toBeVisible();
  });

  it("does not render malformed SHA or timestamp fields as trusted text", async () => {
    const user = userEvent.setup();
    render(
      <AutomationDeployments
        deployments={[{
          ...deployment,
          sha: `token=${secret}`,
          created_at: `token=${secret}`,
        }]}
      />,
    );

    await user.click(screen.getByText("Delivery & Deployments"));

    expect(screen.getByText("Ungültiger SHA-Wert")).toBeVisible();
    expect(screen.getByText("Ungültiger Zeitwert")).toBeVisible();
    expect(screen.queryByText(secret, { exact: false })).not.toBeInTheDocument();
  });

  it("explains an empty recorded history without implying missing provider data", async () => {
    const user = userEvent.setup();
    render(<AutomationDeployments deployments={[]} />);

    expect(screen.getByText("0 aufgezeichnete Einträge")).toBeVisible();
    await user.click(screen.getByText("Delivery & Deployments"));

    expect(screen.getByText("Noch keine Delivery-Aktivität aufgezeichnet")).toBeVisible();
    expect(
      screen.getByText(
        "Hier erscheinen ausschließlich Zustände, die das Control Center selbst gespeichert hat.",
      ),
    ).toBeVisible();
  });

  it("contains an unreadable legacy payload without rendering its raw contents", async () => {
    const user = userEvent.setup();
    const legacyPayload = {
      error: "legacy delivery payload",
      token: secret,
    } as unknown as ControlDeployment[];

    render(<AutomationDeployments deployments={legacyPayload} />);

    expect(screen.getByText("Delivery-Daten nicht lesbar")).toBeVisible();
    await user.click(screen.getByText("Delivery & Deployments"));

    expect(
      screen.getByText("Die aufgezeichneten Delivery-Daten konnten nicht dargestellt werden."),
    ).toBeVisible();
    expect(screen.queryByText(secret, { exact: false })).not.toBeInTheDocument();
  });
});
