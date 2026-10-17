import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ControlCampaign, ControlPlanningJob } from "@/api/contracts";
import { EndeavorList } from "@/features/automation/endeavor-list";
import { automationOverview } from "@/test/automation-fixtures";

const mocks = vi.hoisted(() => ({
  retryPlanningJob: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  stopPlanning: vi.fn(),
}));

vi.mock("@/features/automation/api", () => mocks);

function planningJob(
  id: string,
  overrides: Partial<ControlPlanningJob> & Record<string, unknown>,
): ControlPlanningJob {
  return {
    id,
    project_id: 1,
    idea_seed_id: `IDEA-${id}`,
    status: "waiting_human",
    planning_depth: "balanced",
    max_candidates: 5,
    activation_policy: "per_candidate",
    wish: `Vorhaben ${id}`,
    constraints: [],
    antigravity_chat_id: "chat-1",
    campaign_id: `CMP-${id}`,
    attempt: 1,
    output: {},
    last_error: "",
    created_by: "human",
    created_at: "2026-08-26T10:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-08-26T10:00:00Z",
    ...overrides,
  } as ControlPlanningJob;
}

it("unterscheidet Rückfragen von Planfreigaben und blendet beendete Planung aus", () => {
  render(
    <EndeavorList
      campaigns={[]}
      jobs={[
        planningJob("question", {
          waiting_reason: "question",
          active_question_id: "Q-1",
          round_number: 2,
        }),
        planningJob("approval", {
          waiting_reason: "plan_approval",
          active_question_id: null,
          round_number: 2,
        }),
        planningJob("completed", { status: "completed" }),
        planningJob("cancelled", { status: "cancelled" }),
      ]}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  expect(screen.getByText("Antwort benötigt")).toBeVisible();
  expect(screen.getByRole("button", { name: "Antworten" })).toBeVisible();
  expect(screen.getByText("Plan prüfen", { selector: "span" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Plan prüfen" })).toBeVisible();
  expect(screen.queryByText("Vorhaben completed")).not.toBeInTheDocument();
  expect(screen.queryByText("Vorhaben cancelled")).not.toBeInTheDocument();
});

it("zeigt eine review-bereite Planänderung auch bei pausierter Campaign eindeutig an", () => {
  const amendmentJob = planningJob("amendment", {
    job_type: "plan_amendment",
    amendment_id: "AMD-1",
    waiting_reason: "amendment_approval",
    active_question_id: null,
    round_number: 1,
  });
  const pausedCampaign = {
    id: amendmentJob.campaign_id,
    status: "paused",
  } as ControlCampaign;

  render(
    <EndeavorList
      campaigns={[pausedCampaign]}
      jobs={[amendmentJob]}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  expect(screen.getByText("Planänderung prüfen", { selector: "span" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Änderung prüfen" })).toBeVisible();
});

it("öffnet bei menschlicher Prüfung direkt die wartende PR", () => {
  const onInspectCampaign = vi.fn();
  const onInspectWorkItem = vi.fn();

  render(
    <EndeavorList
      campaigns={automationOverview().campaigns}
      jobs={[]}
      onChanged={vi.fn()}
      onInspectCampaign={onInspectCampaign}
      onInspectJob={vi.fn()}
      onInspectWorkItem={onInspectWorkItem}
      projects={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "PR prüfen" }));

  expect(onInspectWorkItem).toHaveBeenCalledWith("TASK-waiting_review");
  expect(onInspectCampaign).not.toHaveBeenCalled();
});

it("benennt den Abbruch eines Re-Grilling-Jobs als Planänderung", () => {
  const amendmentJob = planningJob("amendment-running", {
    job_type: "plan_amendment",
    amendment_id: "AMD-running",
    status: "running",
    waiting_reason: "",
    active_question_id: null,
    round_number: 0,
  });

  render(
    <EndeavorList
      campaigns={[]}
      jobs={[amendmentJob]}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Planänderung abbrechen" }));
  expect(screen.getByRole("alertdialog", { name: "Planänderung abbrechen?" })).toBeVisible();
  expect(screen.getByText(/vorherige sichere Campaign-Status/)).toBeVisible();
});

it("überlässt das Retry-Limit dem Backend", () => {
  render(
    <EndeavorList
      campaigns={[]}
      jobs={[planningJob("failed", { status: "failed", attempt: 99 })]}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  expect(screen.getByRole("button", { name: "Erneut planen" })).toBeVisible();
});

it("erklärt technische Planungsfehler verständlich und klappt Rohdetails ein", () => {
  const technicalError = "Linked Anti-Gravity project 'Demo' did not become visible.";
  render(
    <EndeavorList
      campaigns={[]}
      jobs={[planningJob("failed-project", {
        status: "failed",
        last_error: technicalError,
      })]}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  expect(screen.getByText(/Projektverknüpfung konnte nicht bestätigt werden/)).toBeVisible();
  expect(screen.getByText(technicalError)).not.toBeVisible();
  fireEvent.click(screen.getByText("Technische Details"));
  expect(screen.getByText(technicalError)).toBeVisible();
});

it("öffnet den ausgewählten Planning-Job statt nur seiner Campaign", () => {
  const questionJob = planningJob("question", {
    waiting_reason: "question",
    active_question_id: "Q-1",
    round_number: 1,
  });
  const onInspectJob = vi.fn();

  render(
    <EndeavorList
      campaigns={[]}
      jobs={[questionJob]}
      onChanged={vi.fn()}
      onInspectJob={onInspectJob}
      projects={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Antworten" }));
  expect(onInspectJob).toHaveBeenCalledWith(questionJob);
});

it("beendet eine laufende Planung erst nach Bestätigung", async () => {
  const runningJob = planningJob("running", {
    status: "running",
    waiting_reason: "",
    active_question_id: null,
    round_number: 0,
  });
  const onChanged = vi.fn();
  mocks.stopPlanning.mockResolvedValue({ target: "planning_job" });

  render(
    <EndeavorList
      campaigns={[]}
      jobs={[runningJob]}
      onChanged={onChanged}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Planung beenden" }));
  expect(screen.getByRole("alertdialog", { name: "Planung wirklich beenden?" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Planung beenden" }));

  await waitFor(() => expect(mocks.stopPlanning).toHaveBeenCalledWith(runningJob));
  expect(onChanged).toHaveBeenCalledOnce();
});

it("versteckt aktive Vorhaben nicht hinter einer festen Obergrenze", () => {
  const jobs = Array.from({ length: 11 }, (_, index) =>
    planningJob(`running-${index + 1}`, {
      status: "running",
      waiting_reason: "",
      active_question_id: null,
      round_number: 0,
    }),
  );

  render(
    <EndeavorList
      campaigns={[]}
      jobs={jobs}
      onChanged={vi.fn()}
      onInspectJob={vi.fn()}
      projects={[]}
    />,
  );

  expect(screen.getByText("Vorhaben running-11")).toBeVisible();
});
