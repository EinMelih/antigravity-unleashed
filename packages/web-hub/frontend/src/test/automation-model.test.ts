import { describe, expect, it } from "vitest";

import {
  buildAttentionQueue,
  buildEndeavors,
  filterWorkItems,
  flattenWorkItems,
  nextStepFor,
} from "@/features/automation/model";
import {
  automationOverview,
  automationPlanningJob,
  automationProject,
} from "@/test/automation-fixtures";

describe("Automation model", () => {
  it("projects one endeavor across planning and campaign state", () => {
    const overview = automationOverview();
    overview.campaigns[0]!.status = "draft";
    overview.planning_jobs = [automationPlanningJob()];

    const endeavors = buildEndeavors(overview, [automationProject]);

    expect(endeavors).toHaveLength(1);
    expect(endeavors[0]).toMatchObject({
      id: "CMP-1",
      projectName: "cat-search",
      title: "Cat Search Qualität",
      phase: "plan_review",
      phaseLabel: "Plan prüfen",
      stage: 2,
      completedPrs: 1,
      totalPrs: 2,
      campaign: { id: "CMP-1" },
      planningJob: { id: "PLAN-waiting_human" },
    });
  });

  it("ignores a consumed initial plan gate after the campaign advanced", () => {
    const overview = automationOverview();
    overview.planning_jobs = [automationPlanningJob()];

    const endeavors = buildEndeavors(overview, [automationProject]);

    expect(endeavors).toHaveLength(1);
    expect(endeavors[0]).toMatchObject({
      id: "CMP-1",
      phase: "human_review",
      planningJob: undefined,
    });
  });

  it("keeps a running planning job visible before a campaign exists", () => {
    const overview = automationOverview();
    overview.campaigns = [];
    overview.planning_jobs = [automationPlanningJob("running")];

    const endeavors = buildEndeavors(overview, [automationProject]);

    expect(endeavors).toEqual([
      expect.objectContaining({
        id: "PLAN-running",
        projectName: "cat-search",
        phase: "planning",
        phaseLabel: "Repository wird untersucht",
        stage: 1,
        completedPrs: 0,
        totalPrs: 0,
      }),
    ]);
  });

  it("surfaces human review as the current phase with truthful PR counts", () => {
    const endeavors = buildEndeavors(automationOverview(), [automationProject]);

    expect(endeavors[0]).toMatchObject({
      phase: "human_review",
      phaseLabel: "Menschliche Prüfung",
      stage: 4,
      activePrs: 1,
      completedPrs: 1,
      totalPrs: 2,
      reviewWorkItemId: "TASK-waiting_review",
    });
  });

  it("excludes obsolete amendment slices from progress and completion", () => {
    const overview = automationOverview();
    const retiredCandidate = overview.campaigns[0]!.pr_candidates[0]!;
    retiredCandidate.status = "obsolete";
    retiredCandidate.task = null;
    retiredCandidate.work_order = null;

    const endeavors = buildEndeavors(overview, [automationProject]);

    expect(endeavors[0]).toMatchObject({
      phase: "complete",
      activePrs: 0,
      completedPrs: 1,
      totalPrs: 1,
      reviewWorkItemId: undefined,
    });
  });

  it("deduplicates overlapping planning and amendment jobs for one campaign", () => {
    const overview = automationOverview();
    const initialJob = automationPlanningJob();
    const amendmentJob = {
      ...automationPlanningJob("running"),
      id: "PLAN-amendment",
      job_type: "plan_amendment",
      amendment_id: "AMD-1",
      campaign_id: "CMP-1",
      updated_at: "2026-08-06 11:00:00",
    };
    overview.planning_jobs = [initialJob, amendmentJob];

    const endeavors = buildEndeavors(overview, [automationProject]);

    expect(endeavors).toHaveLength(1);
    expect(endeavors[0]).toMatchObject({
      id: "CMP-1",
      phase: "planning",
      planningJob: { id: "PLAN-amendment" },
    });
  });

  it("flattens campaigns and sorts attention before completed work", () => {
    const items = flattenWorkItems(automationOverview(), [automationProject]);
    expect(items).toHaveLength(2);
    expect(items.at(0)).toMatchObject({
      projectName: "cat-search",
      status: "waiting_review",
      nextStep: "Tests und Änderungen prüfen.",
    });
    expect(items.at(0)?.activity).toHaveLength(2);
    expect(items.at(1)?.status).toBe("completed");
  });

  it("filters active, attention and search without changing source data", () => {
    const items = flattenWorkItems(automationOverview(), [automationProject]);
    expect(filterWorkItems(items, "active", "")).toHaveLength(1);
    expect(filterWorkItems(items, "attention", "")).toHaveLength(1);
    expect(filterWorkItems(items, "all", "Dokumentation")).toHaveLength(1);
    expect(items).toHaveLength(2);
  });

  it("derives a readable next step from task state", () => {
    const overview = automationOverview();
    const campaign = overview.campaigns[0];
    const candidate = campaign?.pr_candidates[0];
    expect(candidate && campaign ? nextStepFor(candidate, campaign) : "").toBe(
      "Tests und Evidence prüfen",
    );
  });

  it("keeps every open attention item and sorts urgency then newest first", () => {
    const overview = automationOverview();
    const planningJob = automationPlanningJob();
    planningJob.waiting_reason = "question";
    planningJob.active_question_id = "Q-1";
    planningJob.round_number = 1;
    overview.planning_jobs = [planningJob];
    overview.campaigns[0]!.questions = [
      {
        id: "Q-1",
        campaign_id: "CMP-1",
        branch: "scope",
        question: "Soll die bestehende API kompatibel bleiben?",
        rationale: "Bestimmt den Migrationspfad.",
        answer: "",
        answer_source: "",
        status: "open",
        owner: "human",
        evidence: {},
      },
    ];
    overview.attention = [
      {
        id: "ATT-low",
        project_id: 52,
        category: "deployment_approval",
        entity_type: "deployment",
        entity_id: "DEP-1",
        title: "Deployment prüfen",
        consequence: "Die Auslieferung wartet.",
        recommendation: "Zielsystem kontrollieren.",
        urgency: "low",
        status: "open",
        created_at: "2026-08-26 12:00:00",
      },
      {
        id: "ATT-high-old",
        project_id: 52,
        category: "plan_approval",
        entity_type: "campaign",
        entity_id: "CMP-1",
        title: "Plan zuerst prüfen",
        consequence: "Die Planung wartet.",
        recommendation: "Plan kontrollieren.",
        urgency: "high",
        status: "open",
        created_at: "2026-08-26 09:00:00",
      },
      {
        id: "ATT-normal-old",
        project_id: 52,
        category: "review",
        entity_type: "agent_task",
        entity_id: "TASK-waiting_review",
        title: "Umsetzung prüfen",
        consequence: "Der Merge wartet.",
        recommendation: "Nachweise kontrollieren.",
        urgency: "normal",
        status: "open",
        created_at: "2026-08-26 08:00:00",
      },
      {
        id: "ATT-high-new",
        project_id: 52,
        category: "plan_approval",
        entity_type: "campaign",
        entity_id: "CMP-1",
        title: "Aktuellen Plan prüfen",
        consequence: "Die Planung wartet.",
        recommendation: "Plan kontrollieren.",
        urgency: "high",
        status: "open",
        created_at: "2026-08-26 11:00:00",
      },
      {
        id: "ATT-question",
        project_id: 52,
        category: "planning_question",
        entity_type: "planning_question",
        entity_id: "Q-1",
        title: "Planungsfrage beantworten",
        consequence: "Die Planung wartet.",
        recommendation: "Eine kurze Antwort geben.",
        urgency: "normal",
        status: "open",
        created_at: "2026-08-26 09:30:00",
      },
      {
        id: "ATT-unmapped",
        project_id: 52,
        category: "project_integrity",
        entity_type: "project",
        entity_id: "52",
        title: "Projektzustand prüfen",
        consequence: "Eine Information fehlt.",
        recommendation: "Projektstatus lesen.",
        urgency: "normal",
        status: "open",
        created_at: "2026-08-26 10:00:00",
      },
      {
        id: "ATT-closed",
        project_id: 52,
        category: "review",
        entity_type: "agent_task",
        entity_id: "TASK-waiting_review",
        title: "Bereits erledigt",
        consequence: "",
        recommendation: "",
        urgency: "critical",
        status: "resolved",
        created_at: "2026-08-26 13:00:00",
      },
    ];
    const workItems = flattenWorkItems(overview, [automationProject]);

    const queue = buildAttentionQueue(overview, [automationProject], workItems);

    expect(queue.map((entry) => entry.id)).toEqual([
      "ATT-high-new",
      "ATT-high-old",
      "ATT-unmapped",
      "ATT-question",
      "ATT-normal-old",
      "ATT-low",
    ]);
    expect(queue).toHaveLength(6);
    expect(queue.find((entry) => entry.id === "ATT-high-old")?.target).toEqual({
      campaignId: "CMP-1",
      kind: "planning",
      planningJobId: "PLAN-waiting_human",
    });
    expect(queue.find((entry) => entry.id === "ATT-normal-old")?.target).toEqual({
      kind: "work_item",
      workItemId: "TASK-waiting_review",
    });
    expect(queue.find((entry) => entry.id === "ATT-question")?.target).toEqual({
      campaignId: "CMP-1",
      kind: "planning",
      planningJobId: "PLAN-waiting_human",
    });
    expect(queue.find((entry) => entry.id === "ATT-unmapped")?.target).toEqual({
      kind: "information",
    });
  });
});
