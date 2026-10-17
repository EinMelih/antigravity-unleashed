import type { ChatHistoryEntry, ConversationCatalogItem, ModelCatalogItem } from "@/api/contracts";

export type ConversationScope = "active" | "archived" | "all";
export type ConversationTypeFilter = "all" | "normal" | "project";
export type ConversationProjectFilter = string;

export const ALL_PROJECTS_FILTER = "all";

export interface ConversationProjectOption {
  count: number;
  label: string;
  value: ConversationProjectFilter;
}

function conversationProjectLabel(conversation: ConversationCatalogItem) {
  const projectName = conversation.project_name?.trim();
  if (projectName) return projectName;
  const repositoryName = conversation.repository_name?.trim();
  if (repositoryName) return repositoryName;
  const workspaceName = conversation.workspace_path
    ?.split(/[\\/]/)
    .filter(Boolean)
    .at(-1)
    ?.trim();
  return workspaceName || "Unbekanntes Projekt";
}

export function conversationProjectKey(conversation: ConversationCatalogItem) {
  const workspacePath = conversation.workspace_path?.trim();
  if (workspacePath) {
    const normalizedPath = workspacePath
      .replace(/[\\/]+/g, "/")
      .replace(/\/$/, "")
      .toLocaleLowerCase("en");
    return `path:${normalizedPath}`;
  }
  const projectUuid = conversation.project_uuid?.trim();
  if (projectUuid) return `uuid:${projectUuid}`;
  const projectName = conversation.project_name?.trim() || conversation.repository_name?.trim();
  if (projectName) return `name:${projectName.toLocaleLowerCase("de")}`;
  return "unknown";
}

export function conversationProjectOptions(
  conversations: ConversationCatalogItem[],
): ConversationProjectOption[] {
  const byKey = new Map<ConversationProjectFilter, ConversationProjectOption>();
  conversations.forEach((conversation) => {
    if (conversation.conversation_type !== "project") return;
    const value = conversationProjectKey(conversation);
    const existing = byKey.get(value);
    if (existing) {
      existing.count += 1;
      return;
    }
    byKey.set(value, {
      count: 1,
      label: conversationProjectLabel(conversation),
      value,
    });
  });
  return [...byKey.values()].sort((left, right) => (
    left.label.localeCompare(right.label, "de", { sensitivity: "base" })
    || left.value.localeCompare(right.value, "en")
  ));
}

export function modelSelectionId(model: ModelCatalogItem) {
  if (model.selection_id) return model.selection_id;
  if (model.source === "custom" && model.custom_model_id) return `custom:${model.custom_model_id}`;
  if (model.source === "codex") return `codex:${model.model_id || model.label}`;
  return `native:${model.model_id || model.label}`;
}

export function filterConversations(
  conversations: ConversationCatalogItem[],
  scope: ConversationScope,
  search: string,
  type: ConversationTypeFilter = "all",
  project: ConversationProjectFilter = ALL_PROJECTS_FILTER,
) {
  const needle = search.trim().toLocaleLowerCase("de");
  return conversations.filter((conversation) => {
    if (scope === "active" && conversation.archived) return false;
    if (scope === "archived" && !conversation.archived) return false;
    if (type === "project" && conversation.conversation_type !== "project") return false;
    if (type === "normal" && conversation.conversation_type === "project") return false;
    if (
      type === "project"
      && project !== ALL_PROJECTS_FILTER
      && conversationProjectKey(conversation) !== project
    ) return false;
    if (!needle) return true;
    return [
      conversation.title,
      conversation.project_name,
      conversation.repository_name,
      conversation.convo_id,
    ].some((value) => value?.toLocaleLowerCase("de").includes(needle));
  });
}

export interface HistoryGroup {
  key: string;
  type: "entry" | "agent";
  entries: ChatHistoryEntry[];
}

export function groupHistory(entries: ChatHistoryEntry[]): HistoryGroup[] {
  const groups: HistoryGroup[] = [];
  let agentEntries: ChatHistoryEntry[] = [];
  const flushAgent = () => {
    if (!agentEntries.length) return;
    groups.push({
      key: `agent-${agentEntries[0]?.idx ?? groups.length}`,
      type: "agent",
      entries: agentEntries,
    });
    agentEntries = [];
  };

  entries.forEach((entry) => {
    if (entry.type === "message" && entry.role === "user") {
      flushAgent();
      groups.push({ key: `entry-${entry.idx}`, type: "entry", entries: [entry] });
      return;
    }
    agentEntries.push(entry);
  });
  flushAgent();
  return groups;
}

export interface AgentEntryGroup {
  key: string;
  type: "entry" | "tools";
  entries: ChatHistoryEntry[];
}

export function groupAgentEntries(entries: ChatHistoryEntry[]): AgentEntryGroup[] {
  const groups: AgentEntryGroup[] = [];
  let tools: ChatHistoryEntry[] = [];
  const flushTools = () => {
    if (!tools.length) return;
    groups.push({ key: `tools-${tools[0]?.idx ?? groups.length}`, type: "tools", entries: tools });
    tools = [];
  };

  entries.forEach((entry) => {
    if (entry.type === "tool_call" || entry.type === "tool_output") {
      tools.push(entry);
      return;
    }
    flushTools();
    groups.push({ key: `entry-${entry.idx}`, type: "entry", entries: [entry] });
  });
  flushTools();
  return groups;
}

export type ToolActivityKind = "commands" | "exploration" | "edits" | "browser" | "tasks" | "other";

export interface ToolActivity {
  background: boolean;
  detail: string;
  failed: boolean;
  key: string;
  kind: ToolActivityKind;
  label: string;
  running: boolean;
}

export interface ToolActivitySection {
  activities: ToolActivity[];
  key: string;
  kind: ToolActivityKind;
}

function recordValue(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

function firstText(...values: unknown[]) {
  return values.find((value) => typeof value === "string" && value.trim()) as string | undefined;
}

function classifyTool(toolName: string): ToolActivityKind {
  const name = toolName.toLocaleLowerCase("en");
  if (name.includes("command") || name.includes("terminal") || name.includes("shell")) return "commands";
  if (name.includes("edit") || name.includes("write") || name.includes("replace") || name.includes("patch")) return "edits";
  if (name.includes("browser") || name.includes("navigate") || name.includes("screenshot")) return "browser";
  if (name.includes("task") || name.includes("todo")) return "tasks";
  if (
    name.includes("view") || name.includes("read") || name.includes("search")
    || name.includes("find") || name.includes("list") || name.includes("grep")
  ) return "exploration";
  return "other";
}

function activityLabel(entry: ChatHistoryEntry, kind: ToolActivityKind) {
  const enriched = entry.enriched ?? {};
  const args = recordValue(entry.args);
  if (kind === "commands") {
    return firstText(enriched.command, args.CommandLine, args.command, enriched.summary) || "Command";
  }
  if (kind === "exploration" || kind === "edits") {
    return firstText(
      args.AbsolutePath,
      args.TargetFile,
      args.FilePath,
      args.Path,
      args.path,
      args.Query,
      args.query,
      enriched.summary,
      enriched.action,
    ) || entry.tool_name || "Datei";
  }
  return firstText(enriched.summary, enriched.action, enriched.url) || entry.tool_name || "Tool action";
}

function outputText(output: unknown) {
  if (typeof output === "string") return output;
  if (output === undefined || output === null) return "";
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return String(output);
  }
}

export function buildToolSections(entries: ChatHistoryEntry[]): ToolActivitySection[] {
  const activities: ToolActivity[] = [];
  let current: ToolActivity | undefined;

  entries.forEach((entry) => {
    if (entry.type === "tool_call") {
      const kind = classifyTool(entry.tool_name || "");
      const state = String(entry.state ?? entry.enriched?.state ?? "").toLocaleLowerCase("en");
      current = {
        background: entry.enriched?.background_task === true,
        detail: "",
        failed: state === "failed" || state === "error" || entry.status === "error",
        key: `activity-${entry.idx}`,
        kind,
        label: activityLabel(entry, kind),
        running: entry.is_running === true || state === "running",
      };
      activities.push(current);
      return;
    }

    const detail = outputText(entry.output);
    if (!detail) return;
    if (current) {
      current.detail = current.detail ? `${current.detail}\n${detail}` : detail;
      return;
    }
    current = {
      background: false,
      detail,
      failed: false,
      key: `activity-${entry.idx}`,
      kind: "other",
      label: "Tool output",
      running: false,
    };
    activities.push(current);
  });

  return activities.reduce<ToolActivitySection[]>((sections, activity) => {
    const previous = sections.at(-1);
    if (previous?.kind === activity.kind) {
      previous.activities.push(activity);
      return sections;
    }
    sections.push({
      activities: [activity],
      key: `${activity.kind}-${activity.key}`,
      kind: activity.kind,
    });
    return sections;
  }, []);
}

export function workDuration(entries: ChatHistoryEntry[], live = false, now = Date.now()) {
  const starts = entries.flatMap((entry) => typeof entry.started_at === "number" ? [entry.started_at * 1_000] : []);
  const finishes = entries.flatMap((entry) => typeof entry.finished_at === "number" ? [entry.finished_at * 1_000] : []);
  if (!starts.length) return null;
  const startedAt = Math.min(...starts);
  const finishedAt = live ? now : finishes.length ? Math.max(...finishes) : startedAt;
  return Math.max(0, finishedAt - startedAt);
}

export function formatWorkDuration(durationMs: number) {
  const seconds = Math.max(1, Math.round(durationMs / 1_000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

export function formatRelativeTime(timestamp: number) {
  if (!timestamp) return "";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (seconds < 60) return "jetzt";
  if (seconds < 3_600) return `vor ${Math.floor(seconds / 60)} Min.`;
  if (seconds < 86_400) return `vor ${Math.floor(seconds / 3_600)} Std.`;
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(
    new Date(timestamp * 1_000),
  );
}
