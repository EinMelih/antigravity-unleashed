import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ControlCampaign, ControlPlanningJob } from "@/api/contracts";
import { CampaignPlanDialog } from "@/features/automation/campaign-plan-dialog";

const mocks = vi.hoisted(() => ({
  activateCampaignWave: vi.fn(),
  answerPlanningQuestion: vi.fn(),
  approveCampaign: vi.fn(),
  getCampaignReadiness: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  stopPlanning: vi.fn(),
  updateControlPolicy: vi.fn(),
}));

vi.mock("@/features/automation/api", () => mocks);

const campaign: ControlCampaign = {
  id: "CMP-1",
  project_id: 52,
  title: "Suche verbessern",
  goal: "Die Suche soll verständlich und robust werden.",
  non_goals: "",
  risk_level: "medium",
  status: "draft",
  version: 1,
  base_sha: "a".repeat(40),
  approved_sha: "",
  pr_candidates: [],
  profile: {
    planning_depth: "balanced",
    requested_max_candidates: 5,
    activation_policy: "per_candidate",
  },
  questions: [
    {
      id: "Q-active",
      campaign_id: "CMP-1",
      branch: "Datenmodell",
      question: "Soll die Suche Tippfehler automatisch korrigieren?",
      rationale: "Diese Entscheidung verändert Datenmodell und Tests.",
      answer: "",
      answer_source: "",
      status: "open",
      owner: "human",
      evidence: {},
    },
    {
      id: "Q-other",
      campaign_id: "CMP-1",
      branch: "Darstellung",
      question: "Welche Farbe soll der Hinweis bekommen?",
      rationale: "",
      answer: "",
      answer_source: "",
      status: "open",
      owner: "human",
      evidence: {},
    },
  ],
};

const planningJob: ControlPlanningJob = {
  id: "PLAN-1",
  project_id: 52,
  idea_seed_id: "IDEA-1",
  status: "waiting_human",
  planning_depth: "balanced",
  max_candidates: 5,
  activation_policy: "per_candidate",
  wish: campaign.goal,
  constraints: [],
  antigravity_chat_id: "chat-1",
  campaign_id: campaign.id,
  waiting_reason: "question",
  active_question_id: "Q-active",
  round_number: 2,
  attempt: 1,
  output: {},
  last_error: "",
  created_by: "human",
  created_at: "2026-08-26T10:00:00Z",
  started_at: "2026-08-26T10:00:01Z",
  finished_at: null,
  updated_at: "2026-08-26T10:01:00Z",
};

function renderQuestionDialog(
  selectedCampaign: ControlCampaign = campaign,
  selectedPlanningJob: ControlPlanningJob = planningJob,
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <CampaignPlanDialog
        campaign={selectedCampaign}
        onChanged={onChanged}
        onOpenChange={onOpenChange}
        open
        planningJob={selectedPlanningJob}
        policy={{ mode: "guided", paused: false }}
      />
    </QueryClientProvider>,
  );
  return { onChanged, onOpenChange };
}

it("benennt eine fokussierte Amendment-Rückfrage eindeutig", () => {
  const amendmentCampaign = { ...campaign, status: "paused" };
  const amendmentJob: ControlPlanningJob = {
    ...planningJob,
    idea_seed_id: null,
    job_type: "plan_amendment",
    amendment_id: "AMD-1",
  };

  renderQuestionDialog(amendmentCampaign, amendmentJob);

  expect(screen.getByRole("dialog", { name: "Rückfrage zur Planänderung" })).toBeVisible();
  expect(screen.getByText(/Nur der betroffene Plan-Zweig wird neu geklärt/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Planänderung abbrechen" })).toBeVisible();
  expect(screen.queryByText("Plan prüfen: Suche verbessern")).not.toBeInTheDocument();
});

it("zeigt im Rückfrage-Modus nur die aktive Frage statt der leeren Plan-Shell", () => {
  mocks.getCampaignReadiness.mockResolvedValue({ ready: false, missing: [] });

  renderQuestionDialog();

  expect(screen.getByRole("dialog", { name: "Rückfrage zur Planung" })).toBeVisible();
  expect(screen.getByText(campaign.goal)).toBeVisible();
  expect(screen.getByText("Soll die Suche Tippfehler automatisch korrigieren?")).toBeVisible();
  expect(screen.getByText("Diese Entscheidung verändert Datenmodell und Tests.")).toBeVisible();
  expect(screen.queryByText("Welche Farbe soll der Hinweis bekommen?")).not.toBeInTheDocument();
  expect(screen.queryByText("Reihenfolge und sichere Wellen")).not.toBeInTheDocument();
  expect(mocks.getCampaignReadiness).not.toHaveBeenCalled();
});

it("speichert die Antwort und setzt die Planung sofort verständlich fort", async () => {
  mocks.answerPlanningQuestion.mockResolvedValue({
    question: { id: "Q-active", status: "answered" },
    planning_job: { id: "PLAN-1", status: "queued" },
  });
  mocks.runControlExecutorOnce.mockResolvedValue({ executor: { status: "claimed" } });
  const { onChanged } = renderQuestionDialog();

  fireEvent.change(
    screen.getByRole("textbox", {
      name: "Antwort auf: Soll die Suche Tippfehler automatisch korrigieren?",
    }),
    { target: { value: "Ja, aber nur bei eindeutigen Treffern." } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Antwort speichern" }));

  expect(await screen.findByText("Antwort gespeichert. Die Planung läuft weiter.")).toBeVisible();
  expect(mocks.answerPlanningQuestion).toHaveBeenCalledWith(
    "Q-active",
    "Ja, aber nur bei eindeutigen Treffern.",
  );
  expect(mocks.runControlExecutorOnce).toHaveBeenCalledOnce();
  expect(onChanged).toHaveBeenCalledOnce();
  expect(mocks.getCampaignReadiness).not.toHaveBeenCalled();
});

it("meldet verständlich, wenn die gespeicherte Antwort nur verzögert weiterläuft", async () => {
  mocks.answerPlanningQuestion.mockResolvedValue({
    question: { id: "Q-active", status: "answered" },
    planning_job: { id: "PLAN-1", status: "queued" },
  });
  mocks.runControlExecutorOnce.mockRejectedValue(new Error("Executor nicht erreichbar"));
  renderQuestionDialog();

  fireEvent.change(
    screen.getByRole("textbox", {
      name: "Antwort auf: Soll die Suche Tippfehler automatisch korrigieren?",
    }),
    { target: { value: "Nein, die Eingabe soll unverändert bleiben." } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Antwort speichern" }));

  expect(await screen.findByText(
    "Antwort gespeichert. Die Planung ist eingeplant, konnte aber nicht sofort fortgesetzt werden. Der Hintergrunddienst übernimmt automatisch.",
  )).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("beendet die Rückfrage-Planung erst nach einer klaren Bestätigung", async () => {
  mocks.stopPlanning.mockResolvedValue({ target: "planning_job" });
  const { onChanged, onOpenChange } = renderQuestionDialog();

  fireEvent.click(screen.getByRole("button", { name: "Planung beenden" }));
  expect(screen.getByRole("alertdialog", { name: "Planung wirklich beenden?" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Planung beenden" }));

  expect(await screen.findByRole("dialog", { name: "Rückfrage zur Planung" })).toBeVisible();
  await vi.waitFor(() => expect(mocks.stopPlanning).toHaveBeenCalledWith(planningJob));
  expect(onChanged).toHaveBeenCalledOnce();
  expect(onOpenChange).toHaveBeenCalledWith(false);
});
