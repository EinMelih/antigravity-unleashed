import { describe, expect, it } from "vitest";

import type { ChatHistoryEntry, ConversationCatalogItem } from "@/api/contracts";
import {
  buildToolSections,
  conversationProjectKey,
  conversationProjectOptions,
  filterConversations,
  formatWorkDuration,
  groupAgentEntries,
  groupHistory,
  workDuration,
} from "@/features/chats/model";

const active: ConversationCatalogItem = {
  archived: false,
  conversation_type: "normal",
  convo_id: "active-id",
  created_at: 1,
  project_name: "",
  project_uuid: "outside-of-project",
  repository_name: "",
  sidebar_position: 0,
  source: "antigravity",
  status: "complete",
  step_count: 3,
  title: "Aktiver Chat",
  updated_at: 2,
  visible_in_sidebar: true,
  workspace_path: "",
};

const archived = { ...active, archived: true, convo_id: "archived-id", title: "Altes Projekt", visible_in_sidebar: false };
const project = {
  ...active,
  conversation_type: "project",
  convo_id: "project-id",
  project_name: "Antigravity Agent",
  project_uuid: "project-1",
  title: "Aktiver Projektchat",
  workspace_path: "D:\\Antigravity Agent",
} satisfies ConversationCatalogItem;

describe("chat model", () => {
  it("separates active and archived conversations", () => {
    expect(filterConversations([active, archived], "active", "")).toEqual([active]);
    expect(filterConversations([active, archived], "archived", "")).toEqual([archived]);
  });

  it("searches titles and stable identifiers", () => {
    expect(filterConversations([active, archived], "all", "projekt")).toEqual([archived]);
    expect(filterConversations([active, archived], "all", "active-id")).toEqual([active]);
  });

  it("combines conversation type with scope and search filters", () => {
    expect(filterConversations([active, archived, project], "active", "aktiv", "normal")).toEqual([active]);
    expect(filterConversations([active, archived, project], "active", "aktiv", "project")).toEqual([project]);
    expect(filterConversations([active, archived, project], "archived", "projekt", "project")).toEqual([]);
  });

  it("builds unique project choices and filters one project by stable identity", () => {
    const secondProject = {
      ...project,
      convo_id: "project-id-2",
      project_name: "sample-api",
      project_uuid: "project-2",
      title: "Zweiter Projektchat",
      workspace_path: "D:\\projects\\sample-api",
    };
    const duplicate = { ...project, convo_id: "project-id-3", title: "Noch ein Projektchat" };

    expect(conversationProjectOptions([active, secondProject, duplicate, project])).toEqual([
      { count: 2, label: "Antigravity Agent", value: "path:d:/antigravity agent" },
      { count: 1, label: "sample-api", value: "path:d:/projects/sample-api" },
    ]);
    expect(
      filterConversations(
        [active, project, secondProject],
        "active",
        "projektchat",
        "project",
        conversationProjectKey(secondProject),
      ),
    ).toEqual([secondProject]);
  });

  it("groups each agent turn and preserves inline tool order", () => {
    const entries: ChatHistoryEntry[] = [
      { idx: 1, type: "message", role: "user", content: "Start" },
      { idx: 2, type: "tool_call", tool_name: "run_command" },
      { idx: 3, type: "tool_output", output: "ok" },
      { idx: 4, type: "message", role: "assistant", content: "Fertig" },
    ];
    const groups = groupHistory(entries);
    expect(groups.map((group) => group.type)).toEqual(["entry", "agent"]);
    expect(groups[1]?.entries).toHaveLength(3);
    expect(groupAgentEntries(groups[1]?.entries ?? []).map((group) => group.type)).toEqual(["tools", "entry"]);
  });

  it("builds native command and exploration sections", () => {
    const sections = buildToolSections([
      {
        enriched: { command: "npm run dev", background_task: true },
        idx: 2,
        is_running: true,
        state: "running",
        tool_name: "run_command",
        type: "tool_call",
      },
      { idx: 3, output: "Port 5173", type: "tool_output" },
      { args: { AbsolutePath: "D:\\project\\app.tsx" }, idx: 4, tool_name: "view_file", type: "tool_call" },
    ]);
    expect(sections.map((section) => section.kind)).toEqual(["commands", "exploration"]);
    expect(sections[0]?.activities[0]).toMatchObject({
      background: true,
      detail: "Port 5173",
      label: "npm run dev",
      running: true,
    });
  });

  it("uses persisted timestamps for the worked duration", () => {
    const entries: ChatHistoryEntry[] = [
      { idx: 1, started_at: 100, finished_at: 101, type: "message" },
      { idx: 2, started_at: 101, finished_at: 136, type: "tool_call" },
    ];
    expect(workDuration(entries)).toBe(36_000);
    expect(formatWorkDuration(36_000)).toBe("36s");
  });
});
