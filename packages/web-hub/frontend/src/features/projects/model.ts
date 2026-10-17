import type {
  AntiGravityProject,
  ControlOverviewResponse,
  HubProject,
  ProjectRuntimeSnapshot,
  ScheduledTask,
  WorkersResponse,
} from "@/api/contracts";
import {
  filterWorkItems,
  flattenWorkItems,
  isAttentionWorkItem,
} from "@/features/automation/model";

export type ProjectAntiGravityLinkState =
  | "unlinked"
  | "checking"
  | "unavailable"
  | "pending_confirmation"
  | "stale"
  | "linked";

export function projectAntiGravityLinkState(
  project: HubProject,
  catalog: AntiGravityProject[] | undefined,
  catalogState: "pending" | "error" | "ready",
): ProjectAntiGravityLinkState {
  if (!project.antigravity_linked) return "unlinked";
  if (catalogState === "pending") return "checking";
  if (catalogState === "error" || !catalog) return "unavailable";
  const savedId = String(project.integrity_project_uuid || "").trim();
  if (!savedId) return "pending_confirmation";
  return catalog.some((candidate) =>
    candidate.id === savedId || candidate.project_uuid === savedId,
  )
    ? "linked"
    : "stale";
}

export function projectWorkItems(control?: ControlOverviewResponse, project?: HubProject) {
  if (!control || !project) return [];
  return flattenWorkItems(control, [project]).filter((item) => item.projectId === project.id);
}

export function projectMetrics(
  control?: ControlOverviewResponse,
  workers?: WorkersResponse,
) {
  const items = control ? flattenWorkItems(control) : [];
  const openPullRequests = items.filter((item) => {
    const task = item.candidate.task;
    if (!task?.pr_url) return false;
    if (task.merged_sha || task.status === "completed") return false;
    return !["merged", "cancelled", "completed"].includes(item.status);
  }).length;
  const testsOpen = items.filter((item) => {
    const pack = item.candidate.evidence_pack;
    return Boolean(pack && (pack.test_pack?.missing?.length || pack.test_pack?.failed?.length));
  }).length;
  const activeAgents = control?.summary.tasks_active ?? workers?.capacity.active ?? 0;
  const blockers = (control?.summary.attention_open ?? 0) + items.filter(isAttentionWorkItem).length;
  return { activeAgents, blockers, openPullRequests, testsOpen };
}

export interface ProjectNextAction {
  label: string;
  description: string;
  href: string;
  tone: "current" | "pending";
}

export function projectNextActions(
  project: HubProject,
  control?: ControlOverviewResponse,
  runtime?: ProjectRuntimeSnapshot,
): ProjectNextAction[] {
  const actions: ProjectNextAction[] = [];
  if (!project.antigravity_linked) {
    actions.push({ label: "Mit Anti-Gravity verknüpfen", description: "Projektkontext für Chats und Agenten herstellen.", href: `#/projects/${project.id}`, tone: "current" });
  }
  if (runtime && !runtime.services.frontend.active && runtime.services.frontend.config.enabled) {
    actions.push({ label: "Frontend starten", description: `Lokale Vorschau auf Port ${runtime.services.frontend.config.port} öffnen.`, href: `#/projects/${project.id}`, tone: "current" });
  }
  const workItems = control
    ? filterWorkItems(projectWorkItems(control, project), "active", "")
    : [];
  for (const workItem of workItems) {
    actions.push({ label: workItem.nextStep, description: workItem.title, href: "#/automation", tone: actions.length ? "pending" : "current" });
  }
  if (!actions.length) {
    actions.push({ label: "Projekt ist bereit", description: "Keine unmittelbare Blockade. Neue Arbeit kann geplant werden.", href: "#/automation", tone: "current" });
  }
  return actions;
}

export function tasksForProject(tasks: ScheduledTask[], project: HubProject) {
  const nativeIds = new Set([
    project.integrity_project_uuid,
    project.antigravity_project_name,
  ].filter((value): value is string => Boolean(value)));
  return tasks.filter((task) => task.all_projects || nativeIds.has(task.project_id));
}
