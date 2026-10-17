import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkItemDelivery } from "@/features/automation/work-item-delivery";
import { automationCandidate } from "@/test/automation-fixtures";

const mocks = vi.hoisted(() => ({
  evaluateTaskEvidence: vi.fn(),
  mergeTaskOnGitHub: vi.fn(),
  recordTaskApproval: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  syncTaskGitHub: vi.fn(),
}));

vi.mock("@/features/automation/api", () => ({
  evaluateTaskEvidence: mocks.evaluateTaskEvidence,
  mergeTaskOnGitHub: mocks.mergeTaskOnGitHub,
  recordTaskApproval: mocks.recordTaskApproval,
  runControlExecutorOnce: mocks.runControlExecutorOnce,
  syncTaskGitHub: mocks.syncTaskGitHub,
}));

function readyCandidate() {
  const candidate = automationCandidate("waiting_human");
  candidate.evidence_pack = {
    ...candidate.evidence_pack!,
    status: "ready_for_human",
    summary: "Automatische Nachweise sind bereit.",
    test_pack: {
      ...candidate.evidence_pack!.test_pack,
      failed: [],
      missing: [],
    },
  };
  return candidate;
}

function fillRequiredReproduction(dialog: HTMLElement) {
  fireEvent.change(within(dialog).getByLabelText("Ausgeführte Schritte"), {
    target: { value: "1. Vorschau öffnen\n2. Suche mit Tab fokussieren\n3. Enter drücken" },
  });
  fireEvent.change(within(dialog).getByLabelText("Erwartetes Verhalten"), {
    target: { value: "Das erste Suchergebnis wird geöffnet." },
  });
  fireEvent.change(within(dialog).getByLabelText("Beobachtetes Verhalten"), {
    target: { value: "Die Seite scrollt nach oben; das Ergebnis bleibt geschlossen." },
  });
  fireEvent.change(within(dialog).getByLabelText("Umgebung"), {
    target: { value: "Windows 11, Chrome 128, lokale Vorschau" },
  });
}

describe("WorkItemDelivery human-test rejection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.recordTaskApproval.mockResolvedValue({
      id: "APR-rejected",
      approval_type: "human_test",
      decision: "rejected",
      sha: "b".repeat(40),
    });
    mocks.runControlExecutorOnce.mockResolvedValue({ executor: { status: "claimed" } });
  });

  it("requires a SHA-bound reproduction package and wakes the repair executor", async () => {
    const candidate = readyCandidate();
    const sha = candidate.task!.current_sha;
    const onChanged = vi.fn().mockResolvedValue(undefined);
    render(<WorkItemDelivery candidate={candidate} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Human-Test ablehnen" }));
    const dialog = screen.getByRole("dialog", { name: "Human-Test ablehnen" });
    expect(within(dialog).getByText(sha, { exact: true })).toBeVisible();
    const submit = within(dialog).getByRole("button", { name: "Ablehnung einplanen" });
    expect(submit).toBeDisabled();

    fillRequiredReproduction(dialog);
    fireEvent.change(within(dialog).getByLabelText("Diagnose (optional)"), {
      target: { value: "Der Enter-Handler greift am Container statt am Link." },
    });
    fireEvent.change(within(dialog).getByLabelText("Artefakt (optional)"), {
      target: { value: "artifacts/manual-search-failure.webm" },
    });
    fireEvent.change(within(dialog).getByLabelText("Notiz (optional)"), {
      target: { value: "Mit der Maus funktioniert derselbe Treffer." },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(mocks.recordTaskApproval).toHaveBeenCalledWith(candidate.task!.id, {
        approval_type: "human_test",
        decision: "rejected",
        sha,
        reason: expect.stringContaining("Reproduktionspaket"),
        evidence: {
          artifact_ref: "artifacts/manual-search-failure.webm",
          diagnosis: "Der Enter-Handler greift am Container statt am Link.",
          environment: "Windows 11, Chrome 128, lokale Vorschau",
          executed_steps: "1. Vorschau öffnen\n2. Suche mit Tab fokussieren\n3. Enter drücken",
          expected_behavior: "Das erste Suchergebnis wird geöffnet.",
          note: "Mit der Maus funktioniert derselbe Treffer.",
          observed_behavior: "Die Seite scrollt nach oben; das Ergebnis bleibt geschlossen.",
        },
      }),
    );
    expect(mocks.runControlExecutorOnce).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/Reparatur wurde eingeplant/i)).toBeVisible();
  });

  it("keeps a successful rejection visible when the immediate executor tick fails", async () => {
    const candidate = readyCandidate();
    const onChanged = vi.fn().mockResolvedValue(undefined);
    mocks.runControlExecutorOnce.mockRejectedValue(new Error("Executor nicht erreichbar"));
    render(<WorkItemDelivery candidate={candidate} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Human-Test ablehnen" }));
    const dialog = screen.getByRole("dialog", { name: "Human-Test ablehnen" });
    fillRequiredReproduction(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Ablehnung einplanen" }));

    expect(
      await screen.findByText(/Reparatur wurde eingeplant.*Executor.*nicht sofort gestartet/i),
    ).toBeVisible();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("keeps the reproduction dialog and error visible when rejection was not persisted", async () => {
    const candidate = readyCandidate();
    const onChanged = vi.fn().mockResolvedValue(undefined);
    mocks.recordTaskApproval.mockRejectedValue(new Error("SHA ist inzwischen veraltet"));
    render(<WorkItemDelivery candidate={candidate} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Human-Test ablehnen" }));
    const dialog = screen.getByRole("dialog", { name: "Human-Test ablehnen" });
    fillRequiredReproduction(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Ablehnung einplanen" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("SHA ist inzwischen veraltet");
    expect(mocks.runControlExecutorOnce).not.toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Human-Test ablehnen" })).toBeVisible();
  });
});
