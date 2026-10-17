import type {
  ControlAttentionItem,
  ControlAuditEvent,
  ControlCampaign,
  ControlCheckpoint,
  ControlOverviewResponse,
  ControlPlanningJob,
  ControlPrCandidate,
  HubProject,
} from "@/api/contracts";

export type WorkItemFilter = "active" | "attention" | "all";

export interface AutomationWorkItem {
  id: string;
  projectId: number;
  projectName: string;
  title: string;
  summary: string;
  status: string;
  risk: string;
  updatedAt: string;
  nextStep: string;
  attention: ControlAttentionItem[];
  activity: Array<
    | { kind: "audit"; createdAt: string; item: ControlAuditEvent }
    | { kind: "checkpoint"; createdAt: string; item: ControlCheckpoint }
  >;
  campaign: ControlCampaign;
  candidate: ControlPrCandidate;
}

export type AutomationEndeavorPhase =
  | "planning"
  | "needs_answer"
  | "plan_review"
  | "ready"
  | "implementing"
  | "human_review"
  | "paused"
  | "failed"
  | "complete";

export interface AutomationEndeavor {
  id: string;
  projectId: number;
  projectName: string;
  title: string;
  phase: AutomationEndeavorPhase;
  phaseLabel: string;
  description: string;
  stage: 1 | 2 | 3 | 4;
  activePrs: number;
  completedPrs: number;
  totalPrs: number;
  reviewWorkItemId?: string;
  updatedAt: string;
  campaign?: ControlCampaign;
  planningJob?: ControlPlanningJob;
}

export type AttentionQueueTarget =
  | { kind: "planning"; campaignId: string; planningJobId?: string }
  | { kind: "work_item"; workItemId: string }
  | { kind: "information" };

export interface AttentionQueueEntry {
  id: string;
  title: string;
  consequence: string;
  recommendation: string;
  urgency: string;
  categoryLabel: string;
  projectName: string;
  createdAt: string;
  target: AttentionQueueTarget;
}

const STATUS_PRIORITY: Record<string, number> = {
  waiting_human: 0,
  waiting_review: 1,
  failed: 2,
  repair: 3,
  paused: 4,
  waiting_ci: 5,
  running: 6,
  leased: 7,
  queued: 8,
  approved: 9,
  ready: 10,
  review: 11,
  completed: 20,
  merged: 21,
  cancelled: 22,
};

const TERMINAL_STATUSES = new Set(["completed", "merged", "cancelled"]);
const ATTENTION_STATUSES = new Set([
  "waiting_human",
  "waiting_review",
  "failed",
  "repair",
  "paused",
]);

const ATTENTION_URGENCY: Record<string, number> = {
  critical: 0,
  high: 1,
  normal: 2,
  low: 3,
};

const ATTENTION_CATEGORY_LABELS: Record<string, string> = {
  agent_permission: "Agentenfreigabe",
  campaign_planning: "Planung",
  deployment_approval: "Auslieferung",
  github_followup: "GitHub-Prüfung",
  human_test: "Menschlicher Test",
  human_test_repair: "Test-Reparatur",
  no_progress: "Blockierte Arbeit",
  plan_amendment: "Planänderung",
  plan_approval: "Planfreigabe",
  planning_question: "Planungsrückfrage",
  project_integrity: "Projektzustand",
  protected_path: "Geschützter Bereich",
  review: "Prüfung",
  work_order_approval: "PR-Freigabe",
};

const TERMINAL_PLANNING_STATUSES = new Set(["completed", "cancelled"]);
const TERMINAL_CAMPAIGN_STATUSES = new Set(["completed", "cancelled"]);
const COMPLETED_PR_STATUSES = new Set(["completed", "merged", "deployed"]);
const CANCELLED_PR_STATUSES = new Set(["cancelled"]);
const HUMAN_REVIEW_STATUSES = new Set(["review", "waiting_review", "waiting_human"]);

function newestPlanningJob(jobs: ControlPlanningJob[]) {
  return [...jobs].sort((left, right) =>
    (right.updated_at || right.created_at || "").localeCompare(
      left.updated_at || left.created_at || "",
    ),
  )[0];
}

function endeavorPhase(
  planningJob: ControlPlanningJob | undefined,
  campaign: ControlCampaign | undefined,
  statuses: string[],
): Pick<AutomationEndeavor, "description" | "phase" | "phaseLabel" | "stage"> {
  if (planningJob?.status === "failed") {
    return {
      phase: "failed",
      phaseLabel: "Planung fehlgeschlagen",
      stage: planningJob.job_type === "plan_amendment" ? 2 : 1,
      description: "Die KI-Planung braucht einen neuen Versuch oder eine menschliche Korrektur.",
    };
  }
  if (["queued", "running"].includes(planningJob?.status || "")) {
    const amendment = planningJob?.job_type === "plan_amendment";
    return {
      phase: "planning",
      phaseLabel: amendment
        ? "Planänderung wird vorbereitet"
        : planningJob?.status === "running"
          ? "Repository wird untersucht"
          : "Planung ist eingeplant",
      stage: amendment ? 2 : 1,
      description: amendment
        ? "Anti-Gravity prüft den betroffenen Teil des bestehenden Plans erneut."
        : planningJob?.status === "running"
          ? "Anti-Gravity analysiert das Projekt und zerlegt das Ziel in geordnete PRs."
          : "Der Hintergrunddienst startet die Repository-Analyse automatisch.",
    };
  }
  if (
    planningJob?.status === "waiting_human" &&
    planningJob.waiting_reason === "question"
  ) {
    return {
      phase: "needs_answer",
      phaseLabel: "Antwort benötigt",
      stage: planningJob.job_type === "plan_amendment" ? 2 : 1,
      description: "Eine gezielte Rückfrage muss beantwortet werden, bevor die Planung weiterläuft.",
    };
  }
  if (
    campaign?.status === "draft" ||
    planningJob?.waiting_reason === "plan_approval" ||
    planningJob?.waiting_reason === "amendment_approval"
  ) {
    return {
      phase: "plan_review",
      phaseLabel: planningJob?.waiting_reason === "amendment_approval"
        ? "Planänderung prüfen"
        : "Plan prüfen",
      stage: 2,
      description: "Ziel, PR-Reihenfolge und Prüfregeln einmal kontrollieren und freigeben.",
    };
  }
  if (campaign?.status === "paused") {
    return {
      phase: "paused",
      phaseLabel: "Vorhaben pausiert",
      stage: 3,
      description: "Die sichere Abarbeitung ist angehalten. Im Plan stehen Grund und nächste Aktion.",
    };
  }

  const reviewCount = statuses.filter((status) => HUMAN_REVIEW_STATUSES.has(status)).length;
  const completedCount = statuses.filter((status) => COMPLETED_PR_STATUSES.has(status)).length;
  if (reviewCount > 0) {
    return {
      phase: "human_review",
      phaseLabel: "Menschliche Prüfung",
      stage: 4,
      description: `${reviewCount} ${reviewCount === 1 ? "PR wartet" : "PRs warten"} auf deine Prüfung.`,
    };
  }
  if (statuses.length > 0 && completedCount === statuses.length) {
    return {
      phase: "complete",
      phaseLabel: "Vorhaben abgeschlossen",
      stage: 4,
      description: "Alle geplanten PRs sind abgeschlossen.",
    };
  }

  const hasStartedCandidate = Boolean(
    campaign?.pr_candidates?.some((candidate) => candidate.work_order || candidate.task),
  );
  if (campaign?.status === "active" || hasStartedCandidate) {
    return {
      phase: "implementing",
      phaseLabel: "PRs werden umgesetzt",
      stage: 3,
      description: "Anti-Gravity arbeitet die freigegebenen PRs in sicherer Reihenfolge ab.",
    };
  }
  return {
    phase: "ready",
    phaseLabel: "Plan ist freigegeben",
    stage: 2,
    description: "Die nächste sichere PR-Welle kann gestartet werden.",
  };
}

export function buildEndeavors(
  control: Pick<ControlOverviewResponse, "campaigns" | "planning_jobs">,
  projects: HubProject[] = [],
): AutomationEndeavor[] {
  const projectNames = new Map(
    projects.map((project) => [project.id, project.github_repo || project.name]),
  );
  const activeJobs = control.planning_jobs.filter(
    (job) => !TERMINAL_PLANNING_STATUSES.has(job.status),
  );
  const usedJobIds = new Set<string>();
  const endeavors: AutomationEndeavor[] = [];

  for (const campaign of control.campaigns) {
    if (TERMINAL_CAMPAIGN_STATUSES.has(campaign.status)) continue;
    const campaignJobs = activeJobs.filter((job) => job.campaign_id === campaign.id);
    for (const job of campaignJobs) usedJobIds.add(job.id);
    const planningJob = newestPlanningJob(
      campaignJobs.filter((job) => !(
        job.job_type !== "plan_amendment" &&
        job.status === "waiting_human" &&
        campaign.status !== "draft"
      )),
    );
    const candidates = (campaign.pr_candidates ?? []).filter((candidate) =>
      candidate.status !== "obsolete" && workItemStatus(candidate) !== "obsolete",
    );
    const statuses = candidates.map(workItemStatus);
    const completedPrs = statuses.filter((status) => COMPLETED_PR_STATUSES.has(status)).length;
    const activePrs = statuses.filter(
      (status) => !COMPLETED_PR_STATUSES.has(status) && !CANCELLED_PR_STATUSES.has(status),
    ).length;
    const reviewWorkItemId = candidates.find((candidate) =>
      HUMAN_REVIEW_STATUSES.has(workItemStatus(candidate)) && candidate.task?.id,
    )?.task?.id;
    endeavors.push({
      id: campaign.id,
      projectId: campaign.project_id,
      projectName: projectNames.get(campaign.project_id) || `Projekt ${campaign.project_id}`,
      title: campaign.title,
      ...endeavorPhase(planningJob, campaign, statuses),
      activePrs,
      completedPrs,
      totalPrs: statuses.length,
      reviewWorkItemId,
      updatedAt: planningJob?.updated_at || campaign.updated_at || campaign.created_at || "",
      campaign,
      planningJob,
    });
  }

  for (const planningJob of activeJobs) {
    if (usedJobIds.has(planningJob.id)) continue;
    const title = planningJob.wish.split("\n").find((line) => line.trim())?.trim() || "Neues Vorhaben";
    endeavors.push({
      id: planningJob.id,
      projectId: planningJob.project_id,
      projectName: projectNames.get(planningJob.project_id) || `Projekt ${planningJob.project_id}`,
      title,
      ...endeavorPhase(planningJob, undefined, []),
      activePrs: 0,
      completedPrs: 0,
      totalPrs: 0,
      updatedAt: planningJob.updated_at || planningJob.created_at || "",
      planningJob,
    });
  }

  const phasePriority: Record<AutomationEndeavorPhase, number> = {
    needs_answer: 0,
    plan_review: 1,
    failed: 2,
    human_review: 3,
    implementing: 4,
    planning: 5,
    ready: 6,
    paused: 7,
    complete: 8,
  };
  return endeavors.sort((left, right) =>
    phasePriority[left.phase] - phasePriority[right.phase] ||
    right.updatedAt.localeCompare(left.updatedAt),
  );
}

export function workItemStatus(candidate: ControlPrCandidate) {
  return candidate.task?.status || candidate.status || "ready";
}

export function nextStepFor(candidate: ControlPrCandidate, campaign: ControlCampaign) {
  const status = workItemStatus(candidate);
  const steps: Record<string, string> = {
    waiting_human: "Menschliche Entscheidung prüfen",
    waiting_review: "Tests und Evidence prüfen",
    failed: "Fehler analysieren und Reparatur planen",
    repair: "Reparaturfortschritt beobachten",
    paused: "Grund der Pause prüfen",
    waiting_ci: "Automatische Checks abwarten",
    running: "Agent arbeitet am vereinbarten Scope",
    leased: "Worker bereitet die Ausführung vor",
    queued: "Wartet auf einen freien Worker",
    completed: "Abschluss und Merge-Ergebnis prüfen",
    merged: "Arbeit ist gemergt",
    cancelled: "Arbeit wurde beendet",
  };
  if (steps[status]) return steps[status];
  if (campaign.status === "draft") return "Campaign-Plan prüfen und freigeben";
  if (candidate.status === "ready") return "Work Order für diesen Slice freigeben";
  return "Status im Control Center prüfen";
}

function activityFor(
  control: ControlOverviewResponse,
  campaign: ControlCampaign,
  candidate: ControlPrCandidate,
) {
  const ids = new Set(
    [campaign.id, candidate.id, candidate.task?.id].filter(
      (value): value is string => Boolean(value),
    ),
  );
  const activity: AutomationWorkItem["activity"] = [];
  for (const item of control.audit) {
    if (ids.has(item.entity_id)) {
      activity.push({ kind: "audit", createdAt: item.created_at, item });
    }
  }
  for (const item of control.checkpoints) {
    if (ids.has(item.entity_id)) {
      activity.push({ kind: "checkpoint", createdAt: item.created_at, item });
    }
  }
  return activity.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
}

export function flattenWorkItems(
  control: ControlOverviewResponse,
  projects: HubProject[] = [],
): AutomationWorkItem[] {
  const projectNames = new Map(
    projects.map((project) => [project.id, project.github_repo || project.name]),
  );
  const rows: AutomationWorkItem[] = [];
  for (const campaign of control.campaigns) {
    for (const candidate of campaign.pr_candidates ?? []) {
      const entityIds = new Set(
        [campaign.id, candidate.id, candidate.task?.id].filter(
          (value): value is string => Boolean(value),
        ),
      );
      const attention = control.attention.filter((item) =>
        entityIds.has(item.entity_id),
      );
      rows.push({
        id: candidate.task?.id || candidate.id,
        projectId: campaign.project_id,
        projectName: projectNames.get(campaign.project_id) || `Projekt ${campaign.project_id}`,
        title: candidate.title,
        summary: candidate.scope,
        status: workItemStatus(candidate),
        risk: candidate.risk_level || campaign.risk_level || "medium",
        updatedAt:
          candidate.task?.updated_at || candidate.updated_at || campaign.updated_at || "",
        nextStep: attention[0]?.recommendation || nextStepFor(candidate, campaign),
        attention,
        activity: activityFor(control, campaign, candidate),
        campaign,
        candidate,
      });
    }
  }
  return rows.sort((left, right) => {
    const status =
      (STATUS_PRIORITY[left.status] ?? 15) - (STATUS_PRIORITY[right.status] ?? 15);
    return status || right.updatedAt.localeCompare(left.updatedAt);
  });
}

function attentionTarget(
  control: ControlOverviewResponse,
  item: ControlAttentionItem,
  workItems: AutomationWorkItem[],
): AttentionQueueTarget {
  const questionCampaign = control.campaigns.find((campaign) =>
    campaign.questions?.some((question) => question.id === item.entity_id),
  );
  const directPlanningJob = control.planning_jobs.find(
    (job) =>
      job.id === item.entity_id ||
      (item.entity_type === "planning_question" && job.active_question_id === item.entity_id),
  );
  const directCampaign = control.campaigns.find(
    (campaign) => campaign.id === item.entity_id,
  );
  const campaignId =
    (item.entity_type === "campaign" ? directCampaign?.id : "") ||
    questionCampaign?.id ||
    control.campaigns.find((campaign) => campaign.id === directPlanningJob?.campaign_id)?.id ||
    "";
  const isPlanningItem =
    Boolean(campaignId) &&
    (["campaign", "planning_job", "planning_question"].includes(item.entity_type) ||
      ["plan_approval", "planning_question"].includes(item.category));

  if (isPlanningItem) {
    const expectedReason = item.category === "planning_question" ? "question" : "plan_approval";
    const planningJob =
      directPlanningJob ||
      [...control.planning_jobs]
        .filter((job) => job.campaign_id === campaignId)
        .sort((left, right) => {
          const reasonPriority =
            Number(right.waiting_reason === expectedReason) -
            Number(left.waiting_reason === expectedReason);
          return reasonPriority || right.updated_at.localeCompare(left.updated_at);
        })[0];
    return planningJob
      ? { kind: "planning", campaignId, planningJobId: planningJob.id }
      : { kind: "planning", campaignId };
  }

  if (["agent_task", "pr_candidate"].includes(item.entity_type)) {
    const workItem = workItems.find((candidate) =>
      item.entity_type === "agent_task"
        ? candidate.candidate.task?.id === item.entity_id
        : candidate.candidate.id === item.entity_id,
    );
    if (workItem) return { kind: "work_item", workItemId: workItem.id };
  }

  return { kind: "information" };
}

export function buildAttentionQueue(
  control: ControlOverviewResponse,
  projects: HubProject[] = [],
  workItems: AutomationWorkItem[] = flattenWorkItems(control, projects),
): AttentionQueueEntry[] {
  const projectNames = new Map(
    projects.map((project) => [project.id, project.github_repo || project.name]),
  );

  return control.attention
    .filter((item) => item.status === "open")
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const urgency =
        (ATTENTION_URGENCY[left.item.urgency] ?? 2) -
        (ATTENTION_URGENCY[right.item.urgency] ?? 2);
      const recency = (right.item.created_at || "").localeCompare(
        left.item.created_at || "",
      );
      return urgency || recency || left.index - right.index;
    })
    .map(({ item }) => ({
      id: item.id,
      title: item.title || "Entscheidung prüfen",
      consequence: item.consequence,
      recommendation: item.recommendation,
      urgency: item.urgency,
      categoryLabel: ATTENTION_CATEGORY_LABELS[item.category] || "Weiterer Hinweis",
      projectName: projectNames.get(item.project_id) || `Projekt ${item.project_id}`,
      createdAt: item.created_at || "",
      target: attentionTarget(control, item, workItems),
    }));
}

export function filterWorkItems(
  items: AutomationWorkItem[],
  filter: WorkItemFilter,
  search: string,
) {
  const normalizedSearch = search.trim().toLocaleLowerCase("de");
  return items.filter((item) => {
    const statusMatch =
      filter === "all" ||
      (filter === "active" && !TERMINAL_STATUSES.has(item.status)) ||
      (filter === "attention" &&
        (item.attention.length > 0 || ATTENTION_STATUSES.has(item.status)));
    if (!statusMatch) return false;
    if (!normalizedSearch) return true;
    return [item.title, item.projectName, item.summary, item.status].some((value) =>
      value.toLocaleLowerCase("de").includes(normalizedSearch),
    );
  });
}

export function isAttentionWorkItem(item: AutomationWorkItem) {
  return item.attention.length > 0 || ATTENTION_STATUSES.has(item.status);
}
