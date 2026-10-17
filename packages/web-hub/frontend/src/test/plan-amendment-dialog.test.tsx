import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type {
  ControlCampaign,
  ControlCampaignReadiness,
  ControlPlanAmendment,
  ControlPlanningJob,
} from "@/api/contracts";
import { ApiError } from "@/api/errors";
import { CampaignPlanDialog } from "@/features/automation/campaign-plan-dialog";

const mocks = vi.hoisted(() => ({
  activateCampaignWave: vi.fn(),
  answerPlanningQuestion: vi.fn(),
  approveCampaign: vi.fn(),
  decidePlanAmendment: vi.fn(),
  getCampaignReadiness: vi.fn(),
  getPlanAmendment: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  startPlanAmendment: vi.fn(),
  stopPlanning: vi.fn(),
  updateControlPolicy: vi.fn(),
}));

vi.mock("@/features/automation/api", () => mocks);

beforeEach(() => {
  vi.clearAllMocks();
});

const amendment: ControlPlanAmendment = {
  id: "AMD-1",
  campaign_id: "CMP-1",
  from_version: 7,
  proposed_version: 8,
  reason: "Die Repository-Analyse hat einen gemeinsamen API-Vertrag gefunden.",
  impact: { branches: ["architecture"] },
  status: "review",
  proposed_by: "antigravity-planner",
  approved_by: "",
  approved_sha: "",
  prior_campaign_status: "active",
  from_base_sha: "a".repeat(40),
  planning_base_sha: "b".repeat(40),
  from_plan_signature: "c".repeat(64),
  from_signature_version: 2,
  before_plan_sha256: "d".repeat(64),
  target_plan_sha256: "e".repeat(64),
  patch_sha256: "f".repeat(64),
  focus: { branches: ["architecture"] },
  target_plan: {},
  patch: {
    campaign: { set: { goal: "Ein gemeinsamer API-Vertrag für alle Clients." } },
    artifacts: {
      add: [{ id: "DOC-new", title: "API Design v2", artifact_type: "design_document" }],
    },
    candidates: {
      add: [{ id: "PRC-new", title: "Fallback verbessern" }],
      update: [{ id: "PRC-future", title: "API vereinheitlichen", fields: ["scope", "tests"] }],
      retire: [{ id: "PRC-old", title: "Alten Cache entfernen" }],
    },
    knowledge_relations: {
      add: [{
        source_kind: "candidate",
        source_id: "PRC-new",
        target_kind: "artifact",
        target_id: "DOC-new",
        relation_type: "implements_design",
      }],
      remove: [{
        source_kind: "candidate",
        source_id: "PRC-old",
        target_kind: "artifact",
        target_id: "DOC-old",
        relation_type: "implements_design",
      }],
    },
  },
  validation: {
    ready: true,
    mutable_candidate_ids: ["PRC-new", "PRC-future", "PRC-old"],
    immutable_candidate_ids: ["PRC-running"],
  },
};

const campaign: ControlCampaign = {
  id: "CMP-1",
  project_id: 52,
  title: "Suche verbessern",
  goal: "Die Suche soll verständlich und robust werden.",
  non_goals: "Keine neue Suchmaschine.",
  risk_level: "medium",
  status: "paused",
  version: 7,
  base_sha: "a".repeat(40),
  approved_sha: "a".repeat(40),
  approved_version: 7,
  pr_candidates: [],
  amendments: [amendment],
};

const planningJob: ControlPlanningJob = {
  id: "PLAN-AMD-1",
  project_id: 52,
  idea_seed_id: null,
  job_type: "plan_amendment",
  amendment_id: amendment.id,
  status: "waiting_human",
  planning_depth: "balanced",
  max_candidates: 12,
  activation_policy: "per_candidate",
  wish: amendment.reason,
  constraints: [],
  antigravity_chat_id: "chat-amendment-1",
  campaign_id: campaign.id,
  waiting_reason: "amendment_approval",
  active_question_id: null,
  round_number: 1,
  attempt: 1,
  output: {},
  last_error: "",
  created_by: "human",
  created_at: "2026-08-26T10:00:00Z",
  started_at: "2026-08-26T10:00:01Z",
  finished_at: null,
  updated_at: "2026-08-26T10:02:00Z",
};

function renderDialog({
  amendmentDetail = amendment,
  campaignOverride = campaign,
  planningJobOverride = planningJob,
}: {
  amendmentDetail?: ControlPlanAmendment | Error;
  campaignOverride?: ControlCampaign;
  planningJobOverride?: ControlPlanningJob | null;
} = {}) {
  if (amendmentDetail instanceof Error) {
    mocks.getPlanAmendment.mockRejectedValue(amendmentDetail);
  } else {
    mocks.getPlanAmendment.mockResolvedValue(amendmentDetail);
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <CampaignPlanDialog
        campaign={campaignOverride}
        onChanged={onChanged}
        onOpenChange={onOpenChange}
        open
        planningJob={planningJobOverride ?? undefined}
        policy={{ mode: "campaign", paused: false }}
      />
    </QueryClientProvider>,
  );
  return { onChanged, onOpenChange };
}

const sourceReadiness: ControlCampaignReadiness = {
  campaign_id: campaign.id,
  ready: true,
  status: "ready",
  score: 100,
  missing: [],
  gates: [],
  plan_signature: "9".repeat(64),
  plan_signature_version: 2,
  simulation: null,
};

const futureCandidate = {
  id: "PRC-future",
  campaign_id: campaign.id,
  title: "Zukünftigen API-Slice anpassen",
  scope: "API-Slice noch vor dem Start anpassen.",
  non_goals: "",
  risk_level: "medium",
  priority: 10,
  status: "ready",
  base_sha: campaign.base_sha,
  acceptance_criteria: ["API bleibt kompatibel."],
  depends_on: [],
  work_order: null,
  contract: null,
  task: null,
  evidence_pack: null,
  findings: [],
  approvals: [],
} as ControlCampaign["pr_candidates"][number];

const runningCandidate = {
  ...futureCandidate,
  id: "PRC-running",
  title: "Bereits laufender Slice",
  status: "running",
  task: { id: "TASK-running", status: "running", started_at: "2026-08-26T10:00:00Z" },
} as ControlCampaign["pr_candidates"][number];

function renderSourcePlanDialog(
  status: "approved" | "active" | "paused" = "active",
  candidates: ControlCampaign["pr_candidates"] = [futureCandidate, runningCandidate],
) {
  const sourceCampaign: ControlCampaign = {
    ...campaign,
    amendments: [],
    status,
    pr_candidates: candidates,
  };
  mocks.getCampaignReadiness.mockResolvedValue(sourceReadiness);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onChanged = vi.fn().mockResolvedValue(undefined);
  render(
    <QueryClientProvider client={client}>
      <CampaignPlanDialog
        campaign={sourceCampaign}
        onChanged={onChanged}
        onOpenChange={vi.fn()}
        open
        policy={{ mode: "campaign", paused: false }}
      />
    </QueryClientProvider>,
  );
  return { onChanged, sourceCampaign };
}

it("zeigt die geprüfte Planänderung mit verständlichen deutschen Begriffen", async () => {
  renderDialog();

  expect(await screen.findByRole("dialog", { name: "Planänderung prüfen: Suche verbessern" })).toBeVisible();
  expect(await screen.findByText("Plan v7 → v8")).toBeVisible();
  expect(await screen.findByText("API vereinheitlichen")).toBeVisible();
  expect(screen.getByText("Fallback verbessern")).toBeVisible();
  expect(screen.getByText("Alten Cache entfernen")).toBeVisible();
  expect(screen.getByText("API Design v2")).toBeVisible();
  expect(screen.getByText("Ziel")).toBeVisible();
  expect(screen.getByText("2 Wissensverknüpfungen")).toBeVisible();
  expect(screen.getByText("0 Abhängigkeitsregeln und 0 Konfliktregeln werden neu geprüft.")).toBeVisible();
  expect(screen.getByText("goal")).not.toBeVisible();
  expect(screen.getByText(/Laufende oder bereits gestartete geplante PRs werden nicht verändert/)).toBeVisible();
  expect(screen.getByText(/Prüfnachweise, GitHub-Daten und Auslieferungen bleiben unverändert/)).toBeVisible();
  expect(screen.getByText(/Danach ist die normale Planfreigabe weiterhin nötig/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Änderung übernehmen" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Änderung ablehnen" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Planänderung abbrechen" })).toBeVisible();
  expect(mocks.getCampaignReadiness).not.toHaveBeenCalled();
});

it("bleibt ohne erfolgreich geladene Amendment-Details fail-closed", async () => {
  const amendmentSummary: ControlPlanAmendment = {
    ...amendment,
    patch: undefined,
    target_plan: undefined,
    validation: undefined,
  };
  renderDialog({
    amendmentDetail: new Error("Amendment-Details nicht erreichbar"),
    campaignOverride: { ...campaign, amendments: [amendmentSummary] },
  });

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Amendment-Details nicht erreichbar",
  );
  expect(screen.queryByText("Zielplan geprüft")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Änderung übernehmen" })).toBeDisabled();
});

it("übernimmt nur den exakt geprüften Zielplan und erklärt die nächste Freigabe", async () => {
  mocks.decidePlanAmendment.mockResolvedValue({
    amendment: { ...amendment, status: "approved" },
    campaign: { ...campaign, status: "draft", version: 8 },
  });
  const { onChanged } = renderDialog();

  const approveButton = await screen.findByRole("button", { name: "Änderung übernehmen" });
  await waitFor(() => expect(approveButton).toBeEnabled());
  fireEvent.click(approveButton);
  expect(screen.getByRole("alertdialog", { name: "Planänderung übernehmen?" })).toBeVisible();
  expect(screen.getByText(/Danach prüfst und genehmigst du den neuen Plan separat/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Änderung übernehmen" }));

  await waitFor(() => expect(mocks.decidePlanAmendment).toHaveBeenCalledWith(
    amendment,
    "approved",
    "Geprüften Zielplan als neuen Campaign-Entwurf übernehmen.",
  ));
  expect(await screen.findByText(
    "Planänderung übernommen. Plan v8 ist jetzt ein Entwurf und braucht noch die normale Planfreigabe.",
  )).toBeVisible();
  expect(onChanged).toHaveBeenCalledOnce();
});

it("lehnt die Änderung ab und erklärt die Rückkehr zum vorherigen Planstatus", async () => {
  mocks.decidePlanAmendment.mockResolvedValue({
    amendment: { ...amendment, status: "rejected" },
    campaign: { ...campaign, status: "active" },
  });
  const { onChanged } = renderDialog();

  const rejectButton = await screen.findByRole("button", { name: "Änderung ablehnen" });
  await waitFor(() => expect(rejectButton).toBeEnabled());
  fireEvent.click(rejectButton);
  expect(screen.getByRole("alertdialog", { name: "Planänderung ablehnen?" })).toBeVisible();
  expect(screen.getByText(/Der aktuelle Plan bleibt unverändert/)).toBeVisible();
  expect(screen.getByText(/Plan kehrt zu „Aktiv“ zurück/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Änderung ablehnen" }));

  await waitFor(() => expect(mocks.decidePlanAmendment).toHaveBeenCalledWith(
    amendment,
    "rejected",
    "Vorgeschlagene Planänderung nach menschlicher Prüfung ablehnen.",
  ));
  expect(await screen.findByText("Planänderung abgelehnt. Der Plan ist wieder aktiv.")).toBeVisible();
  expect(onChanged).toHaveBeenCalledOnce();
});

it("bricht den zugehörigen Planungsauftrag bestätigt ab, ohne den Plan zu löschen", async () => {
  mocks.stopPlanning.mockResolvedValue({
    target: "planning_job",
    planning_job: { ...planningJob, status: "cancelled" },
  });
  const { onChanged } = renderDialog();

  fireEvent.click(await screen.findByRole("button", { name: "Planänderung abbrechen" }));
  expect(screen.getByRole("alertdialog", { name: "Planänderung abbrechen?" })).toBeVisible();
  expect(screen.getByText(/Der vorgeschlagene Zielplan wird nicht angewendet/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Planänderung abbrechen" }));

  await waitFor(() => expect(mocks.stopPlanning).toHaveBeenCalledWith(
    planningJob,
    "Planänderung und fokussierte Neuplanung abbrechen.",
  ));
  expect(await screen.findByText("Planänderung abgebrochen. Der Plan ist wieder aktiv.")).toBeVisible();
  expect(onChanged).toHaveBeenCalledOnce();
  expect(mocks.decidePlanAmendment).not.toHaveBeenCalledWith(
    expect.anything(),
    "approved",
    expect.anything(),
  );
});

it("deaktiviert den Abbruch ehrlich, wenn kein passender Amendment-Job geladen ist", async () => {
  renderDialog({ planningJobOverride: null });

  const cancelButton = await screen.findByRole("button", { name: "Planänderung abbrechen" });
  expect(cancelButton).toBeDisabled();
  expect(screen.getByText(
    "Abbrechen ist erst möglich, wenn der zugehörige Planungsauftrag geladen ist. Aktualisiere die Ansicht.",
  )).toBeVisible();
});

it("lädt bei einem 409 den exakten Amendment-Review neu", async () => {
  mocks.getPlanAmendment
    .mockResolvedValueOnce(amendment)
    .mockRejectedValueOnce(new Error("Amendment-Refetch offline"));
  mocks.decidePlanAmendment.mockRejectedValue(new ApiError(
    "Stale amendment target",
    { code: "stale_amendment_target", status: 409 },
  ));
  const { onChanged } = renderDialog();

  const approveButton = await screen.findByRole("button", { name: "Änderung übernehmen" });
  await waitFor(() => expect(approveButton).toBeEnabled());
  fireEvent.click(approveButton);
  fireEvent.click(screen.getByRole("button", { name: "Änderung übernehmen" }));

  await waitFor(() => expect(mocks.getPlanAmendment).toHaveBeenCalledTimes(2));
  expect(onChanged).toHaveBeenCalledOnce();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Die Planänderung hat sich seit deiner Ansicht geändert. Die neuesten Prüfsummen wurden geladen; bitte prüfe Ausgangs- und Zielplan erneut.",
  );
  expect(screen.queryByText(/Planänderung übernommen/)).not.toBeInTheDocument();
});

it("startet eine gezielte Planänderung mit exakter sichtbarer Plan-Identität", async () => {
  mocks.startPlanAmendment.mockResolvedValue({
    amendment: { id: "AMD-new", status: "planning" },
    planning_job: { id: "PLAN-AMD-new", job_type: "plan_amendment" },
  });
  const { onChanged, sourceCampaign } = renderSourcePlanDialog("active");

  const planDialog = await screen.findByRole("dialog", { name: "Plan prüfen: Suche verbessern" });
  expect(await within(planDialog).findByText(/Signatur v2: 9{64}/)).toBeVisible();
  fireEvent.click(within(planDialog).getByRole("button", { name: "Plan gezielt ändern" }));

  const form = screen.getByRole("alertdialog", { name: "Plan gezielt ändern" });
  expect(within(form).getByText(/Laufende Arbeit, Prüfnachweise, GitHub-Daten und Auslieferungen bleiben unverändert/)).toBeVisible();
  expect(within(form).getByRole("group", { name: "Betroffene zukünftige geplante PRs (optional)" })).toBeVisible();
  expect(within(form).getByText("Technische Ausgangsreferenz")).toBeVisible();
  expect(within(form).getByText(/Source:/)).not.toBeVisible();
  const submit = within(form).getByRole("button", { name: "Planänderung starten" });
  expect(submit).toBeDisabled();
  expect(within(form).getByLabelText("Zukünftigen API-Slice anpassen")).toBeVisible();
  expect(within(form).queryByLabelText("Bereits laufender Slice")).not.toBeInTheDocument();
  expect(within(form).queryByLabelText(/JSON/i)).not.toBeInTheDocument();

  fireEvent.change(within(form).getByLabelText("Warum muss der Plan geändert werden?"), {
    target: { value: "Neue Repository-Erkenntnisse betreffen den API-Vertrag." },
  });
  fireEvent.change(within(form).getByLabelText("Was soll sich am Plan ändern?"), {
    target: { value: "Nur den zukünftigen API-Slice kompatibel neu planen." },
  });
  fireEvent.click(within(form).getByLabelText("Zukünftigen API-Slice anpassen"));
  expect(submit).toBeEnabled();
  fireEvent.click(submit);

  await waitFor(() => expect(mocks.startPlanAmendment).toHaveBeenCalledWith(
    sourceCampaign.id,
    {
      reason: "Neue Repository-Erkenntnisse betreffen den API-Vertrag.",
      focus: {
        branches: [futureCandidate.id],
        requested_change: "Nur den zukünftigen API-Slice kompatibel neu planen.",
      },
      expected_version: sourceCampaign.version,
      expected_base_sha: sourceCampaign.base_sha,
      expected_plan_signature: sourceReadiness.plan_signature,
      expected_plan_signature_version: 2,
    },
  ));
  expect(await screen.findByRole("status")).toHaveTextContent(
    /Plan wird pausiert.*pro Runde höchstens eine Rückfrage/i,
  );
  expect(onChanged).toHaveBeenCalledOnce();
});

it("bietet nur wirklich ungestartete ready Slices für eine Planänderung an", async () => {
  const approvedCandidate = {
    ...futureCandidate,
    id: "PRC-approved",
    title: "Bereits freigegebener Slice",
    status: "approved",
  };
  const orderedCandidate = {
    ...futureCandidate,
    id: "PRC-ordered",
    title: "Slice mit Arbeitsauftrag",
    work_order: {
      id: "WO-ordered",
      status: "approved",
      rationale: "Bereits freigegeben.",
      approval_sha: campaign.base_sha,
    },
  };
  const taskedCandidate = {
    ...futureCandidate,
    id: "PRC-tasked",
    title: "Slice mit gestarteter Aufgabe",
    task: { id: "TASK-started", status: "queued" },
  } as ControlCampaign["pr_candidates"][number];
  renderSourcePlanDialog("active", [
    futureCandidate,
    approvedCandidate,
    orderedCandidate,
    taskedCandidate,
  ]);

  const planDialog = await screen.findByRole("dialog", { name: "Plan prüfen: Suche verbessern" });
  await within(planDialog).findByText(/Signatur v2: 9{64}/);
  const changeButton = within(planDialog).getByRole("button", { name: "Plan gezielt ändern" });
  await waitFor(() => expect(changeButton).toBeEnabled());
  fireEvent.click(changeButton);
  const form = screen.getByRole("alertdialog", { name: "Plan gezielt ändern" });

  expect(within(form).getByLabelText("Zukünftigen API-Slice anpassen")).toBeVisible();
  expect(within(form).queryByLabelText("Bereits freigegebener Slice")).not.toBeInTheDocument();
  expect(within(form).queryByLabelText("Slice mit Arbeitsauftrag")).not.toBeInTheDocument();
  expect(within(form).queryByLabelText("Slice mit gestarteter Aufgabe")).not.toBeInTheDocument();
});

it("lädt nach einem stale Start-409 die exakte Plan-Identität neu", async () => {
  mocks.getCampaignReadiness
    .mockResolvedValueOnce(sourceReadiness)
    .mockResolvedValueOnce({ ...sourceReadiness, plan_signature: "8".repeat(64) });
  mocks.startPlanAmendment.mockRejectedValue(new ApiError(
    "Source plan changed",
    { code: "stale_plan_signature", status: 409 },
  ));
  const { onChanged } = renderSourcePlanDialog("approved");

  const planDialog = await screen.findByRole("dialog", { name: "Plan prüfen: Suche verbessern" });
  await within(planDialog).findByText(/Signatur v2: 9{64}/);
  fireEvent.click(within(planDialog).getByRole("button", { name: "Plan gezielt ändern" }));
  const form = screen.getByRole("alertdialog", { name: "Plan gezielt ändern" });
  fireEvent.change(within(form).getByLabelText("Warum muss der Plan geändert werden?"), {
    target: { value: "Die aktuelle Planbasis ist fachlich nicht mehr korrekt." },
  });
  fireEvent.change(within(form).getByLabelText("Was soll sich am Plan ändern?"), {
    target: { value: "Den noch offenen Zielplan auf die neue Basis abstimmen." },
  });
  fireEvent.click(within(form).getByRole("button", { name: "Planänderung starten" }));

  expect(await within(form).findByRole("alert")).toHaveTextContent(
    /Plan hat sich seit deiner Ansicht geändert.*neu geladen/i,
  );
  expect(mocks.getCampaignReadiness).toHaveBeenCalledTimes(2);
  expect(onChanged).toHaveBeenCalledOnce();
});
