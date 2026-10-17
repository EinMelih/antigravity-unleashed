import type {
  ControlAttentionItem,
  ControlOverviewResponse,
  ControlTask,
  ConversationSummaryResponse,
  HubProject,
} from "@/api/contracts";
import type { NextActionItem } from "@/components/next-actions";

export const ACTIVE_TASK_STATUSES = new Set([
  "leased",
  "running",
  "waiting_ci",
  "waiting_review",
  "waiting_human",
  "repair",
]);

export interface StudioAction extends NextActionItem {
  actionLabel: string;
  href: string;
}

export interface StudioSources {
  control?: ControlOverviewResponse;
  conversations?: ConversationSummaryResponse;
  projects?: HubProject[];
}

function attentionDescription(item: ControlAttentionItem) {
  return item.recommendation || item.consequence || "Eine Entscheidung ist erforderlich.";
}

export function activeTasks(tasks: ControlTask[] = []) {
  return tasks.filter((task) => ACTIVE_TASK_STATUSES.has(task.status));
}

export function buildNextActions({
  control,
  conversations,
  projects,
}: StudioSources): StudioAction[] {
  const actions: StudioAction[] = [];
  const availableProjects = projects ?? [];

  for (const item of (control?.attention ?? []).filter((entry) => entry.status === "open")) {
    actions.push({
      title: item.title || "Entscheidung prüfen",
      description: attentionDescription(item),
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "In Automation prüfen",
      href: "#/automation",
    });
  }

  for (const projectWithRepair of availableProjects.filter(
    (project) =>
      project.github_bootstrap_required || project.git_branch === "directory_missing",
  )) {
    actions.push({
      title: `${projectWithRepair.github_repo || projectWithRepair.name} reparieren`,
      description:
        projectWithRepair.github_setup_error ||
        "Repository oder lokaler Projektordner benötigt Aufmerksamkeit.",
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "Projekt öffnen",
      href: `#/projects/${projectWithRepair.id}`,
    });
  }

  for (const unlinkedProject of availableProjects.filter(
    (project) => !project.antigravity_linked,
  )) {
    actions.push({
      title: `${unlinkedProject.github_repo || unlinkedProject.name} verknüpfen`,
      description:
        "Ordne das Repository einem Anti-Gravity-Projekt zu, damit Chats und Arbeit zusammengehören.",
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "Projekt öffnen",
      href: `#/projects/${unlinkedProject.id}`,
    });
  }

  const runningTasks = activeTasks(control?.tasks);
  if (runningTasks.length > 0) {
    actions.push({
      title: `${runningTasks.length} aktive ${runningTasks.length === 1 ? "Aufgabe" : "Aufgaben"} beobachten`,
      description:
        "Fortschritt, Blockaden und Evidence sind in der Automation gebündelt.",
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "Automation öffnen",
      href: "#/automation",
    });
  }

  const activeAgentCount = conversations?.counts.running ?? 0;
  if (activeAgentCount > 0) {
    actions.push({
      title: `${activeAgentCount} aktive ${activeAgentCount === 1 ? "Conversation" : "Conversations"} ansehen`,
      description: "Öffne die Chats, um laufende Antworten und Zustellungen zu verfolgen.",
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "Chats öffnen",
      href: "#/chats",
    });
  }

  if (projects?.length === 0) {
    actions.push({
      title: "Erstes Repository hinzufügen",
      description:
        "Importiere ein bestehendes GitHub-Repository oder erstelle ein neues Projekt.",
      status: actions.length === 0 ? "current" : "pending",
      actionLabel: "Projekt hinzufügen",
      href: "#/projects/new",
    });
  }

  if (actions.length === 0) {
    actions.push({
      title: "Conversation fortsetzen",
      description: "Es liegt keine dringende Entscheidung oder Blockade vor.",
      status: "current",
      actionLabel: "Chats öffnen",
      href: "#/chats",
    });
  }

  return actions;
}

export function projectHealth(project: HubProject) {
  if (
    project.git_branch === "directory_missing" ||
    project.github_bootstrap_status === "repair_required"
  ) {
    return { label: "Blockiert", tone: "blocked" as const };
  }
  if (project.github_bootstrap_required || !project.antigravity_linked) {
    return { label: "Aufmerksamkeit", tone: "attention" as const };
  }
  return { label: "Gesund", tone: "healthy" as const };
}
