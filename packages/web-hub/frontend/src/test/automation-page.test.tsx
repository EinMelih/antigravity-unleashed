import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ControlPlanningJob } from "@/api/contracts";
import { ApiError } from "@/api/errors";
import { AutomationPage } from "@/pages/automation-page";
import {
  automationOverview,
  automationPlanningJob,
  automationProject,
} from "@/test/automation-fixtures";

const mocks = vi.hoisted(() => ({
  activateCandidate: vi.fn(),
  activateCampaignWave: vi.fn(),
  approveCampaign: vi.fn(),
  cancelWorkOrder: vi.fn(),
  dispositionIdeaSeed: vi.fn(),
  evaluateTaskEvidence: vi.fn(),
  getCampaignReadiness: vi.fn(),
  getPlanAmendment: vi.fn(),
  startPlanAmendment: vi.fn(),
  mergeTaskOnGitHub: vi.fn(),
  recordTaskApproval: vi.fn(),
  runControlExecutorOnce: vi.fn(),
  stopPlanning: vi.fn(),
  syncTaskGitHub: vi.fn(),
  updateControlPolicy: vi.fn(),
  useAutomationData: vi.fn(),
}));

vi.mock("@/features/automation/use-automation-data", () => ({
  useAutomationData: mocks.useAutomationData,
}));

vi.mock("@/features/automation/api", () => ({
  activateCandidate: mocks.activateCandidate,
  activateCampaignWave: mocks.activateCampaignWave,
  answerPlanningQuestion: vi.fn(),
  approveCampaign: mocks.approveCampaign,
  cancelWorkOrder: mocks.cancelWorkOrder,
  createPlanningJob: vi.fn(),
  dispositionIdeaSeed: mocks.dispositionIdeaSeed,
  evaluateTaskEvidence: mocks.evaluateTaskEvidence,
  getCampaignReadiness: mocks.getCampaignReadiness,
  getPlanAmendment: mocks.getPlanAmendment,
  startPlanAmendment: mocks.startPlanAmendment,
  mergeTaskOnGitHub: mocks.mergeTaskOnGitHub,
  recordTaskApproval: mocks.recordTaskApproval,
  retryPlanningJob: vi.fn(),
  runControlExecutorOnce: mocks.runControlExecutorOnce,
  stopPlanning: mocks.stopPlanning,
  syncTaskGitHub: mocks.syncTaskGitHub,
  updateControlPolicy: mocks.updateControlPolicy,
  updateIdeaSeed: vi.fn(),
  planIdeaSeed: vi.fn(),
}));

function query(options: {
  data?: unknown;
  error?: unknown;
  pending?: boolean;
} = {}) {
  return {
    data: options.data,
    error: options.error ?? null,
    isPending: options.pending ?? false,
    isError: Boolean(options.error),
    isSuccess: Boolean(options.data),
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

function automationData() {
  return {
    health: query({ data: { status: "ok" } }),
    control: query({ data: automationOverview() }),
    workers: query({
      data: {
        success: true,
        primary: null,
        workers: [],
        capacity: { active: 1, maximum: 4, minimum_warm: 1, queued: 0, idle_ttl_seconds: 60 },
      },
    }),
    projects: query({ data: { projects: [automationProject] } }),
    ideaSeeds: query({
      data: [
        {
          id: "IDEA-inbox",
          project_id: 52,
          title: "Accessible idea inbox",
          note: "Make the existing idea inbox useful in the React Hub.",
          source: "human",
          status: "inbox",
          provenance: {},
          created_at: "2026-08-26 10:00:00",
          updated_at: "2026-08-26 10:00:00",
        },
        {
          id: "IDEA-deferred",
          project_id: 52,
          title: "Deferred database browser",
          note: "Show the most important database records in the Hub.",
          source: "human",
          status: "deferred",
          provenance: {},
          created_at: "2026-08-26 09:00:00",
          updated_at: "2026-08-26 09:00:00",
        },
      ],
    }),
  };
}

function renderAutomationPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return render(<AutomationPage />, { wrapper: Wrapper });
}

function readyCampaignReadiness() {
  const gateKeys = [
    "outcome_contract",
    "pivotal_fork",
    "repository_grounding",
    "decision_ledger",
    "alternatives_tradeoffs",
    "candidate_contracts",
    "dependency_conflict_simulation",
    "verification_release",
  ];
  return {
    campaign_id: "CMP-1",
    ready: true,
    status: "ready",
    score: 100,
    missing: [],
    gates: gateKeys.map((key) => ({
      key,
      passed: true,
      missing: [],
      evidence: [`${key} geprüft`],
    })),
    plan_signature: "c".repeat(64),
    plan_signature_version: 1,
    grandfathered_approval: false,
    simulation: {
      campaign_id: "CMP-1",
      acyclic: true,
      candidate_count: 2,
      topological_order: ["PRC-waiting_review", "PRC-completed"],
      waves: [
        { wave: 1, candidate_ids: ["PRC-waiting_review"], parallel_count: 1 },
        { wave: 2, candidate_ids: ["PRC-completed"], parallel_count: 1 },
      ],
      dependencies: {
        "PRC-waiting_review": [],
        "PRC-completed": ["PRC-waiting_review"],
      },
      conflicts: [
        {
          candidate_id: "PRC-waiting_review",
          conflicts_with_id: "PRC-completed",
          reason: "Beide ändern denselben Suchvertrag.",
          resources: ["src/search.ts"],
        },
      ],
      max_wave: 2,
    },
  };
}

describe("AutomationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the path from an idea to human review in order", () => {
    mocks.useAutomationData.mockReturnValue(automationData());

    renderAutomationPage();

    const journey = screen.getByRole("region", {
      name: "Ablauf von der Idee zur Prüfung",
    });
    const steps = within(journey).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[0]).toHaveTextContent("Idee beschreiben");
    expect(steps[1]).toHaveTextContent("Plan prüfen");
    expect(steps[2]).toHaveTextContent("PRs in Reihenfolge umsetzen");
    expect(steps[3]).toHaveTextContent("Mensch prüft & merged");
  });

  it("opens the waiting PR directly from its endeavor", () => {
    mocks.useAutomationData.mockReturnValue(automationData());

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "PR prüfen" }));

    expect(screen.getByRole("dialog", { name: "Suche zugänglich machen" })).toBeVisible();
  });

  it("opens approved, active and paused campaign plans without an attention or planning job", async () => {
    const overview = automationOverview();
    const source = overview.campaigns[0]!;
    overview.campaigns = (["approved", "active", "paused"] as const).map((status, index) => ({
      ...source,
      id: `CMP-${status}`,
      title: `Plan ${status}`,
      status,
      amendments: [],
      pr_candidates: [],
      version: index + 2,
    }));
    overview.attention = [];
    overview.planning_jobs = [];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());

    renderAutomationPage();

    for (const status of ["approved", "active", "paused"] as const) {
      const openButton = screen.getByRole("button", { name: `Plan öffnen: Plan ${status}` });
      fireEvent.click(openButton);
      expect(await screen.findByRole("dialog", { name: `Plan prüfen: Plan ${status}` })).toBeVisible();
      fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
      await waitFor(() => expect(
        screen.queryByRole("dialog", { name: `Plan prüfen: Plan ${status}` }),
      ).not.toBeInTheDocument());
    }
  });

  it("uses the matching typed amendment job when a review is opened from the plan card", async () => {
    const overview = automationOverview();
    const campaign = overview.campaigns[0]!;
    const amendment = {
      id: "AMD-direct-review",
      campaign_id: campaign.id,
      from_version: campaign.version,
      proposed_version: campaign.version + 1,
      reason: "Neue Repository-Erkenntnisse ändern den noch offenen Plan.",
      impact: {},
      status: "review",
      proposed_by: "antigravity-planner",
      approved_by: "",
      approved_sha: "",
      prior_campaign_status: "active",
      from_base_sha: campaign.base_sha,
      planning_base_sha: "b".repeat(40),
      before_plan_sha256: "c".repeat(64),
      target_plan_sha256: "d".repeat(64),
      patch_sha256: "e".repeat(64),
      target_plan: {},
      patch: {},
      validation: { ready: true, mutable_candidate_ids: [], immutable_candidate_ids: [] },
      planning_job_id: "PLAN-direct-review",
    };
    const amendmentJob: ControlPlanningJob = {
      ...automationPlanningJob(),
      id: "PLAN-direct-review",
      idea_seed_id: null,
      job_type: "plan_amendment",
      amendment_id: amendment.id,
      campaign_id: campaign.id,
      waiting_reason: "amendment_approval",
    };
    campaign.status = "paused";
    campaign.amendments = [amendment];
    overview.planning_jobs = [amendmentJob];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getPlanAmendment.mockResolvedValue(amendment);
    mocks.stopPlanning.mockResolvedValue({
      target: "planning_job",
      planning_job: { ...amendmentJob, status: "cancelled" },
    });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Änderung prüfen" }));

    const review = await screen.findByRole("dialog", {
      name: `Planänderung prüfen: ${campaign.title}`,
    });
    fireEvent.click(within(review).getByRole("button", { name: "Planänderung abbrechen" }));
    const confirmation = screen.getByRole("alertdialog", { name: "Planänderung abbrechen?" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Planänderung abbrechen" }));

    await waitFor(() => expect(mocks.stopPlanning).toHaveBeenCalledWith(
      amendmentJob,
      "Planänderung und fokussierte Neuplanung abbrechen.",
    ));
  });

  it("opens the idea description dialog from the empty state", () => {
    const overview = automationOverview();
    overview.campaigns = [];
    overview.planning_jobs = [];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);

    renderAutomationPage();

    fireEvent.click(screen.getByRole("button", { name: "Idee beschreiben" }));
    expect(
      screen.getByRole("dialog", { name: "Idee beschreiben" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Projekt")).toBeVisible();
    expect(screen.getByLabelText("Was soll Anti-Gravity umsetzen?")).toBeVisible();
    expect(
      screen.getByLabelText(
        "Plan einmal freigeben, danach automatisch in sicherer Reihenfolge abarbeiten",
      ),
    ).toBeVisible();
  });

  it("labels PR implementation and decisions in plain language", () => {
    mocks.useAutomationData.mockReturnValue(automationData());

    renderAutomationPage();

    const implementation = screen.getByRole("region", { name: "Umsetzung & PRs" });
    expect(within(implementation).getByText("Laufende Arbeit")).toBeVisible();
    expect(
      within(implementation).getByRole("group", { name: "Umsetzung und PRs filtern" }),
    ).toBeVisible();
    expect(
      within(implementation).getByRole("button", { name: "Entscheidung nötig" }),
    ).toBeVisible();
    expect(
      within(implementation).getByRole("searchbox", { name: "Umsetzung durchsuchen" }),
    ).toBeVisible();
    expect(within(implementation).queryByText("Work Items")).not.toBeInTheDocument();
  });

  it("presents planning and campaign progress as one understandable endeavor", () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);

    renderAutomationPage();

    const endeavors = screen.getByRole("region", { name: "Vorhaben" });
    expect(within(endeavors).getByText("Cat Search Qualität")).toBeVisible();
    expect(within(endeavors).getByText("Plan prüfen", { selector: "span" })).toBeVisible();
    expect(within(endeavors).getByText("1 von 2 PRs abgeschlossen")).toBeVisible();
    expect(
      within(endeavors).getByRole("button", {
        name: "Plan prüfen",
      }),
    ).toBeVisible();
    expect(screen.queryByRole("region", { name: "Pläne" })).not.toBeInTheDocument();
  });

  it("opens the matching campaign and work item from the central attention queue", () => {
    const overview = automationOverview();
    overview.planning_jobs = [automationPlanningJob()];
    overview.attention = [
      {
        id: "ATT-plan",
        project_id: 52,
        category: "plan_approval",
        entity_type: "campaign",
        entity_id: "CMP-1",
        title: "Planfreigabe prüfen",
        consequence: "Die Planung wartet.",
        recommendation: "PR-Reihenfolge prüfen.",
        urgency: "high",
        status: "open",
      },
      {
        id: "ATT-task",
        project_id: 52,
        category: "review",
        entity_type: "agent_task",
        entity_id: "TASK-waiting_review",
        title: "PR-Nachweise prüfen",
        consequence: "Der Merge wartet.",
        recommendation: "Tests kontrollieren.",
        urgency: "normal",
        status: "open",
      },
    ];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);

    renderAutomationPage();
    const queue = screen.getByRole("region", { name: "Braucht deine Entscheidung" });
    const planButton = within(queue).getByRole("button", {
      name: "Plan öffnen: Planfreigabe prüfen",
    });
    const workButton = within(queue).getByRole("button", {
      name: "Arbeit öffnen: PR-Nachweise prüfen",
    });

    fireEvent.click(planButton);
    expect(screen.getByRole("dialog", { name: "Plan prüfen: Cat Search Qualität" })).toBeVisible();

    fireEvent.click(workButton);
    expect(screen.getByRole("dialog", { name: "Suche zugänglich machen" })).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Plan prüfen: Cat Search Qualität" })).not.toBeInTheDocument();
  });

  it("reviews a generated campaign plan directly in React", async () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.campaigns[0]!.profile = {
      activation_policy: "campaign_wave",
      planning_depth: "deep",
      requested_max_candidates: 30,
      readiness_score: 100,
    };
    overview.campaigns[0]!.questions = [
      {
        id: "Q-1",
        campaign_id: "CMP-1",
        branch: "architecture",
        question: "Soll die bestehende API kompatibel bleiben?",
        rationale: "Bestimmt den Migrationspfad.",
        answer: "Ja, bestehende Clients dürfen nicht brechen.",
        answer_source: "human",
        status: "resolved",
        owner: "human",
        evidence: {},
      },
    ];
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan prüfen" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Plan prüfen: Cat Search Qualität",
    });
    expect(dialog).toBeVisible();
    expect(await within(dialog).findByText("2 sichere Wellen")).toBeVisible();
    expect(within(dialog).getByText("8/8 Gates")).toBeVisible();
    expect(within(dialog).getByText(/Signatur v1: c{64}/)).toBeVisible();
    expect(within(dialog).getByText("Suche zugänglich machen")).toBeVisible();
    expect(within(dialog).getByText(/Konflikt mit Dokumentation abschließen/)).toBeVisible();
    fireEvent.click(within(dialog).getByText("Plan- und Dokumentdetails"));
    expect(
      within(dialog).getByText("Ja, bestehende Clients dürfen nicht brechen."),
    ).toBeVisible();
    const approveButton = within(dialog).getByRole("button", {
      name: "Plan freigeben und Abarbeitung starten",
    });
    expect(approveButton).toBeEnabled();

    fireEvent.click(approveButton);
    const confirmation = screen.getByRole("alertdialog", {
      name: "Plan wirklich freigeben?",
    });
    expect(within(confirmation).getByText(/Plan v2 auf aaaaaaaaaaaa/)).toBeVisible();
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Freigeben und starten" }),
    );
    await waitFor(() => expect(mocks.approveCampaign).toHaveBeenCalledWith(
      overview.campaigns[0],
      "c".repeat(64),
    ));
    expect(mocks.updateControlPolicy).toHaveBeenCalledWith("campaign");
    expect(mocks.activateCampaignWave).toHaveBeenCalledWith("CMP-1");
  });

  it("approves per-candidate plans without changing the global mode", async () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.campaigns[0]!.profile = {
      activation_policy: "per_candidate",
      planning_depth: "deep",
      requested_max_candidates: 30,
    };
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan prüfen" }));
    const dialog = await screen.findByRole("dialog", { name: /Plan prüfen:/ });
    await within(dialog).findByText("2 sichere Wellen");
    fireEvent.click(within(dialog).getByRole("button", { name: "Plan freigeben" }));
    const confirmation = screen.getByRole("alertdialog", { name: "Plan wirklich freigeben?" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Plan freigeben" }));

    await waitFor(() => expect(mocks.approveCampaign).toHaveBeenCalledTimes(1));
    expect(mocks.updateControlPolicy).not.toHaveBeenCalled();
    expect(mocks.activateCampaignWave).not.toHaveBeenCalled();
  });

  it("can approve a plan while paused without starting work", async () => {
    const overview = automationOverview();
    overview.policy.paused = true;
    overview.campaigns[0]!.status = "draft";
    overview.campaigns[0]!.profile = {
      activation_policy: "campaign_wave",
      planning_depth: "deep",
      requested_max_candidates: 30,
    };
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan prüfen" }));
    const dialog = await screen.findByRole("dialog", { name: /Plan prüfen:/ });
    await within(dialog).findByText("2 sichere Wellen");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Plan freigeben (Automation bleibt pausiert)",
      }),
    );
    const confirmation = screen.getByRole("alertdialog", { name: "Plan wirklich freigeben?" });
    expect(within(confirmation).getByText(/Automation bleibt pausiert/)).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Plan freigeben" }));

    await waitFor(() => expect(mocks.approveCampaign).toHaveBeenCalledTimes(1));
    expect(mocks.updateControlPolicy).not.toHaveBeenCalled();
    expect(mocks.activateCampaignWave).not.toHaveBeenCalled();
  });

  it("keeps partial approval failures visible and refreshes the overview", async () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.campaigns[0]!.profile = {
      activation_policy: "campaign_wave",
      planning_depth: "deep",
      requested_max_candidates: 30,
    };
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());
    mocks.activateCampaignWave.mockRejectedValueOnce(new Error("Wave konnte nicht aktiviert werden."));

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan prüfen" }));
    const dialog = await screen.findByRole("dialog", { name: /Plan prüfen:/ });
    await within(dialog).findByText("2 sichere Wellen");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Plan freigeben und Abarbeitung starten",
      }),
    );
    const confirmation = screen.getByRole("alertdialog", { name: "Plan wirklich freigeben?" });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Freigeben und starten" }));

    expect(await within(dialog).findByText("Wave konnte nicht aktiviert werden.")).toBeVisible();
    expect(data.control.refetch).toHaveBeenCalled();
    expect(dialog).toBeVisible();
  });

  it("reloads readiness when the exact viewed signature is stale", async () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.campaigns[0]!.profile = {
      activation_policy: "campaign_wave",
      planning_depth: "deep",
      requested_max_candidates: 30,
    };
    overview.planning_jobs = [automationPlanningJob()];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.getCampaignReadiness.mockResolvedValue(readyCampaignReadiness());
    mocks.approveCampaign.mockRejectedValue(
      new ApiError("Plan changed.", {
        code: "stale_plan_signature",
        status: 409,
      }),
    );

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: "Plan prüfen" }));
    const dialog = await screen.findByRole("dialog", { name: /Plan prüfen:/ });
    await within(dialog).findByText("8/8 Gates");
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Plan freigeben und Abarbeitung starten",
      }),
    );
    const confirmation = screen.getByRole("alertdialog", {
      name: "Plan wirklich freigeben?",
    });
    expect(within(confirmation).getByText(/Exakte Plan-Signatur v1: c{64}/)).toBeVisible();
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Freigeben und starten" }),
    );

    expect(await within(dialog).findByText(/seit deiner Ansicht geändert/)).toBeVisible();
    expect(mocks.getCampaignReadiness).toHaveBeenCalledTimes(2);
    expect(data.control.refetch).toHaveBeenCalled();
    expect(dialog).toBeVisible();
    expect(mocks.activateCampaignWave).not.toHaveBeenCalled();
  });

  it("opens a work item and exposes all detail areas", () => {
    const overview = automationOverview();
    overview.campaigns[0]!.pr_candidates[0]!.findings = [
      {
        id: "FND-RESOLVED",
        task_id: overview.campaigns[0]!.pr_candidates[0]!.task!.id,
        classification: "REQUIRED",
        source: "review",
        body: "Markdown-Werte escapen.",
        status: "resolved",
        resolution: "Escaping ergänzt und erneut geprüft.",
        sha: "b".repeat(40),
      },
      {
        id: "FND-OPEN",
        task_id: overview.campaigns[0]!.pr_candidates[0]!.task!.id,
        classification: "QUESTION",
        source: "review",
        body: "Ist die Dokumentation aktuell?",
        status: "open",
        resolution: "",
        sha: "b".repeat(40),
      },
    ];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    renderAutomationPage();
    expect(
      screen.queryByRole("link", { name: /Legacy-Control-Center/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    expect(screen.getByRole("dialog", { name: "Suche zugänglich machen" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Im Control Center öffnen" })).toHaveAttribute(
      "href",
      "/dashboard/legacy?review=TASK-waiting_review&project_id=52",
    );
    expect(screen.getAllByRole("tab")).toHaveLength(6);
    fireEvent.click(screen.getByRole("tab", { name: "Tests & Evidence" }));
    expect(screen.getByText("Ein Gate ist offen.")).toBeVisible();
    expect(screen.getByText("REQUIRED · Gelöst")).toBeVisible();
    expect(screen.getByText("Gelöst: Escaping ergänzt und erneut geprüft.")).toBeVisible();
    expect(screen.getByText("QUESTION · Offen")).toBeVisible();
  });

  it("shows delivery gates and records a confirmed human-test decision for the exact SHA", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const sha = candidate.task!.current_sha;
    candidate.task!.status = "waiting_human";
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha,
      status: "ready_for_human",
      summary: "Alle Nachweise sind bereit.",
      test_pack: { ...candidate.evidence_pack!.test_pack, missing: [], failed: [] },
    };
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.recordTaskApproval.mockResolvedValue({
      id: "APR-human",
      approval_type: "human_test",
      decision: "approved",
      sha,
    });
    mocks.evaluateTaskEvidence.mockResolvedValue(candidate.evidence_pack);

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));

    expect(within(drawer).getByRole("heading", { name: "Delivery-Gates" })).toBeVisible();
    expect(within(drawer).getByText("Evidence für aktuellen SHA")).toBeVisible();
    expect(within(drawer).getByText("Human-Test-Freigabe")).toBeVisible();
    expect(within(drawer).getByText("Merge-Freigabe")).toBeVisible();
    expect(within(drawer).getByRole("button", { name: "Pull Request mergen" })).toBeDisabled();

    fireEvent.click(within(drawer).getByRole("button", { name: "Evidence neu bewerten" }));
    await waitFor(() =>
      expect(mocks.evaluateTaskEvidence).toHaveBeenCalledWith(candidate.task!.id),
    );
    fireEvent.click(within(drawer).getByRole("button", { name: "Human-Test freigeben" }));
    const confirmation = screen.getByRole("alertdialog", {
      name: "Human-Test wirklich freigeben?",
    });
    expect(within(confirmation).getByText(new RegExp(sha.slice(0, 12)))).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Freigeben" }));

    await waitFor(() =>
      expect(mocks.recordTaskApproval).toHaveBeenCalledWith(candidate.task!.id, {
        approval_type: "human_test",
        decision: "approved",
        sha,
        reason: expect.stringContaining("Human-Test"),
      }),
    );
    expect(data.control.refetch).toHaveBeenCalled();
  });

  it("records a confirmed human-test rejection for the exact SHA", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const sha = candidate.task!.current_sha;
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha,
      status: "ready_for_human",
      test_pack: { ...candidate.evidence_pack!.test_pack, missing: [], failed: [] },
    };
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.recordTaskApproval.mockResolvedValue({
      id: "APR-rejected",
      approval_type: "human_test",
      decision: "rejected",
      sha,
    });
    mocks.runControlExecutorOnce.mockResolvedValue({ executor: { status: "claimed" } });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Human-Test ablehnen" }));
    const confirmation = screen.getByRole("dialog", { name: "Human-Test ablehnen" });
    expect(within(confirmation).getByText(sha, { exact: true })).toBeVisible();
    fireEvent.change(within(confirmation).getByLabelText("Ausgeführte Schritte"), {
      target: { value: "Vorschau öffnen und Suche per Tastatur bedienen." },
    });
    fireEvent.change(within(confirmation).getByLabelText("Erwartetes Verhalten"), {
      target: { value: "Der Treffer wird geöffnet." },
    });
    fireEvent.change(within(confirmation).getByLabelText("Beobachtetes Verhalten"), {
      target: { value: "Der Treffer bleibt geschlossen." },
    });
    fireEvent.change(within(confirmation).getByLabelText("Umgebung"), {
      target: { value: "Windows 11, Chrome 128" },
    });
    fireEvent.click(
      within(confirmation).getByRole("button", { name: "Ablehnung einplanen" }),
    );

    await waitFor(() =>
      expect(mocks.recordTaskApproval).toHaveBeenCalledWith(candidate.task!.id, {
        approval_type: "human_test",
        decision: "rejected",
        sha,
        reason: expect.stringContaining("Reproduktionspaket"),
        evidence: {
          environment: "Windows 11, Chrome 128",
          executed_steps: "Vorschau öffnen und Suche per Tastatur bedienen.",
          expected_behavior: "Der Treffer wird geöffnet.",
          observed_behavior: "Der Treffer bleibt geschlossen.",
        },
      }),
    );
    expect(mocks.runControlExecutorOnce).toHaveBeenCalledTimes(1);
  });

  it("records a separate confirmed merge approval after the human gate", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const sha = candidate.task!.current_sha;
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha,
      status: "approved",
      test_pack: { ...candidate.evidence_pack!.test_pack, missing: [], failed: [] },
    };
    candidate.approvals = [
      {
        id: "APR-human",
        approval_type: "human_test",
        decision: "approved",
        sha,
        revoked_at: null,
      },
    ];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.recordTaskApproval.mockResolvedValue({
      id: "APR-merge",
      approval_type: "merge",
      decision: "approved",
      sha,
    });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Merge freigeben" }));
    const confirmation = screen.getByRole("alertdialog", {
      name: "Merge wirklich freigeben?",
    });
    fireEvent.click(within(confirmation).getByRole("button", { name: "Merge freigeben" }));

    await waitFor(() =>
      expect(mocks.recordTaskApproval).toHaveBeenCalledWith(candidate.task!.id, {
        approval_type: "merge",
        decision: "approved",
        sha,
        reason: expect.stringContaining("Merge-Gates"),
      }),
    );
  });

  it("merges only after every visible SHA-bound delivery gate is satisfied", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const sha = candidate.task!.current_sha;
    candidate.task!.status = "waiting_human";
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha,
      status: "approved",
      summary: "Human-Test bestanden.",
      test_pack: { ...candidate.evidence_pack!.test_pack, missing: [], failed: [] },
    };
    candidate.approvals = [
      {
        id: "APR-human",
        approval_type: "human_test",
        decision: "approved",
        sha,
        revoked_at: null,
      },
      {
        id: "APR-merge",
        approval_type: "merge",
        decision: "approved",
        sha,
        revoked_at: null,
      },
    ];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.mergeTaskOnGitHub.mockResolvedValue({
      task: { ...candidate.task!, status: "completed", merged_sha: "c".repeat(40) },
      merge: { merged: true, message: "Merged", sha: "c".repeat(40) },
      campaign_completed: false,
      issue_close_warning: "Issue konnte nicht geschlossen werden.",
    });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));
    const mergeButton = within(drawer).getByRole("button", { name: "Pull Request mergen" });
    expect(mergeButton).toBeEnabled();

    fireEvent.click(mergeButton);
    const confirmation = screen.getByRole("alertdialog", {
      name: "Pull Request wirklich mergen?",
    });
    expect(within(confirmation).getByText(new RegExp(`PR #${candidate.task!.pr_number}`))).toBeVisible();
    expect(within(confirmation).getByText(new RegExp(sha.slice(0, 12)))).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Jetzt mergen" }));

    await waitFor(() =>
      expect(mocks.mergeTaskOnGitHub).toHaveBeenCalledWith(candidate.task!.id),
    );
    expect(
      await within(drawer).findByText(/Issue konnte nicht geschlossen werden/),
    ).toBeVisible();
    expect(data.control.refetch).toHaveBeenCalled();
  });

  it("does not accept human or merge approvals from an older SHA", () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const sha = candidate.task!.current_sha;
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha,
      status: "approved",
      test_pack: { ...candidate.evidence_pack!.test_pack, missing: [], failed: [] },
    };
    candidate.approvals = [
      {
        id: "APR-human-old",
        approval_type: "human_test",
        decision: "approved",
        sha: "a".repeat(40),
        revoked_at: null,
      },
      {
        id: "APR-merge-old",
        approval_type: "merge",
        decision: "approved",
        sha: "a".repeat(40),
        revoked_at: null,
      },
    ];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));

    expect(within(drawer).getByRole("button", { name: "Merge freigeben" })).toBeDisabled();
    expect(within(drawer).getByRole("button", { name: "Pull Request mergen" })).toBeDisabled();
    expect(within(drawer).getAllByText("Offen")).toHaveLength(2);
  });

  it("keeps a successful GitHub sync visible when the follow-up refresh fails", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    const data = automationData();
    data.control = query({ data: overview });
    data.control.refetch.mockRejectedValueOnce(new Error("Overview unavailable"));
    mocks.useAutomationData.mockReturnValue(data);
    mocks.syncTaskGitHub.mockResolvedValue({
      task: candidate.task,
      evidence_pack: candidate.evidence_pack,
    });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("tab", { name: "GitHub" }));
    fireEvent.click(within(drawer).getByRole("button", { name: "Mit GitHub synchronisieren" }));

    expect(
      await within(drawer).findByText(/GitHub wurde synchronisiert.*Ansicht.*nicht aktualisiert/i),
    ).toBeVisible();
    expect(mocks.syncTaskGitHub).toHaveBeenCalledWith(candidate.task!.id);
  });

  it("activates a ready PR slice directly with its exact base SHA", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    candidate.status = "ready";
    candidate.work_order = null;
    candidate.task = null;
    candidate.evidence_pack = null;
    overview.tasks = [];
    overview.attention = [];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.activateCandidate.mockResolvedValue({ id: "WO-ready", status: "approved" });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("button", { name: "PR-Slice freigeben" }));
    const confirmation = screen.getByRole("alertdialog", {
      name: "PR-Slice wirklich freigeben?",
    });
    expect(within(confirmation).getByText(/aaaaaaaaaaaa/)).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Jetzt freigeben" }));

    await waitFor(() =>
      expect(mocks.activateCandidate).toHaveBeenCalledWith(
        candidate.id,
        candidate.base_sha,
        expect.stringContaining("Hub"),
      ),
    );
    expect(mocks.updateControlPolicy).not.toHaveBeenCalled();
    expect(data.control.refetch).toHaveBeenCalled();
  });

  it("cancels an approved work order only while its task is visibly unstarted", async () => {
    const overview = automationOverview();
    const candidate = overview.campaigns[0]!.pr_candidates[0]!;
    candidate.status = "approved";
    candidate.task = {
      ...candidate.task!,
      status: "queued",
      attempt: 0,
      started_at: null,
      current_sha: "",
      merged_sha: "",
      branch_name: "",
      worktree_path: "",
      antigravity_chat_id: "",
      issue_number: null,
      issue_url: "",
      pr_number: null,
      pr_url: "",
      last_error: "",
    };
    candidate.evidence_pack = {
      ...candidate.evidence_pack!,
      sha: "",
      status: "collecting",
      summary: "",
      preview_url: "",
      risk: {},
      test_pack: {},
    };
    overview.tasks = [candidate.task];
    overview.attention = [];
    const data = automationData();
    data.control = query({ data: overview });
    mocks.useAutomationData.mockReturnValue(data);
    mocks.cancelWorkOrder.mockResolvedValue({ idempotent: false });

    renderAutomationPage();
    fireEvent.click(screen.getByRole("button", { name: /Suche zugänglich machen/ }));
    const drawer = screen.getByRole("dialog", { name: "Suche zugänglich machen" });
    fireEvent.click(within(drawer).getByRole("button", { name: "Freigabe zurücknehmen" }));
    const confirmation = screen.getByRole("alertdialog", {
      name: "Arbeitsauftrag wirklich zurücknehmen?",
    });
    expect(within(confirmation).getByText(/noch nicht gestartete/)).toBeVisible();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Zurücknehmen" }));

    await waitFor(() =>
      expect(mocks.cancelWorkOrder).toHaveBeenCalledWith(
        candidate.work_order!.id,
        expect.stringContaining("Ausführung"),
      ),
    );
    expect(data.control.refetch).toHaveBeenCalled();
  });

  it("filters to completed work through visible controls", () => {
    mocks.useAutomationData.mockReturnValue(automationData());
    renderAutomationPage();
    expect(screen.queryByText("Dokumentation abschließen")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Alle" }));
    expect(screen.getByText("Dokumentation abschließen")).toBeVisible();
  });

  it("renders loading and offline states", () => {
    const data = automationData();
    data.control = query({ pending: true });
    mocks.useAutomationData.mockReturnValue(data);
    const view = renderAutomationPage();
    expect(screen.getByRole("heading", { name: "Einen Moment bitte" })).toBeVisible();

    data.control = query({ error: new ApiError("offline", { offline: true }) });
    mocks.useAutomationData.mockReturnValue(data);
    view.rerender(<AutomationPage />);
    expect(screen.getByRole("heading", { name: "Hub nicht erreichbar" })).toBeVisible();
  });

  it("keeps work items visible when an optional source fails", () => {
    const data = automationData();
    data.workers = query({ error: new Error("DevTools unavailable") });
    mocks.useAutomationData.mockReturnValue(data);
    renderAutomationPage();
    expect(screen.getByText(/1 ergänzende Datenquelle/)).toBeVisible();
    expect(screen.getByText("Suche zugänglich machen")).toBeVisible();
  });

  it("renders the idea inbox independently and refreshes seeds plus planning after a mutation", async () => {
    const data = automationData();
    mocks.useAutomationData.mockReturnValue(data);
    mocks.dispositionIdeaSeed.mockResolvedValue({
      id: "IDEA-deferred",
      project_id: 52,
      title: "Deferred database browser",
      note: "Show the most important database records in the Hub.",
      source: "human",
      status: "inbox",
      provenance: {},
      created_at: "2026-08-26 09:00:00",
      updated_at: "2026-08-26 10:00:00",
    });

    renderAutomationPage();
    expect(screen.getByRole("heading", { name: "Ideen" })).toBeVisible();
    expect(screen.getByRole("article", { name: "Accessible idea inbox" })).toBeVisible();
    const deferred = screen.getByRole("article", { name: "Deferred database browser" });
    fireEvent.click(within(deferred).getByRole("button", { name: "Wieder öffnen" }));

    await waitFor(() =>
      expect(mocks.dispositionIdeaSeed).toHaveBeenCalledWith("IDEA-deferred", {
        disposition: "inbox",
        reason: "",
      }),
    );
    expect(data.ideaSeeds.refetch).toHaveBeenCalled();
    expect(data.control.refetch).toHaveBeenCalled();
  });

  it("keeps work items usable when only the idea inbox fails", () => {
    const data = automationData();
    data.ideaSeeds = query({ error: new Error("Idea store unavailable") });
    mocks.useAutomationData.mockReturnValue(data);

    renderAutomationPage();
    expect(screen.getByRole("alert")).toHaveTextContent("Idea store unavailable");
    expect(screen.getByText("Suche zugänglich machen")).toBeVisible();
  });
});
