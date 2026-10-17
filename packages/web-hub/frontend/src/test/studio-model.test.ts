import { describe, expect, it } from "vitest";

import type {
  ControlOverviewResponse,
  ControlTask,
  ConversationSummaryResponse,
  HubProject,
} from "@/api/contracts";
import {
  activeTasks,
  buildNextActions,
  projectHealth,
} from "@/features/studio/model";

function project(overrides: Partial<HubProject> = {}): HubProject {
  return {
    id: 1,
    name: "Antigravity Hub",
    path: "D:\\Projects\\antigravity-web",
    github_url: "https://github.com/example/antigravity-web",
    github_owner: "example",
    github_repo: "antigravity-web",
    default_branch: "main",
    git_branch: "main",
    source_kind: "github",
    github_bootstrap_required: false,
    github_bootstrap_status: "ready",
    antigravity_linked: true,
    antigravity_project_name: "Antigravity Hub",
    ...overrides,
  };
}

function task(status: string): ControlTask {
  return {
    id: `TASK-${status}`,
    project_id: 1,
    campaign_id: "CAM-1",
    candidate_id: "PR-1",
    role: "implementation",
    status,
    wake_reason: "work_order",
    base_sha: "a".repeat(40),
    current_sha: "",
    merged_sha: "",
    branch_name: "codex/test",
    worktree_path: "",
    antigravity_chat_id: "",
    issue_number: null,
    issue_url: "",
    pr_number: null,
    pr_url: "",
    attempt: 0,
    last_error: "",
  };
}

function overview(tasks: ControlTask[] = []): ControlOverviewResponse {
  return {
    policy: { mode: "guided", paused: false },
    summary: {
      attention_open: 0,
      recommendations_open: 0,
      campaigns_open: 0,
      work_orders_approved: 0,
      tasks_active: tasks.length,
      tasks_waiting_human: 0,
      human_gates_open: 0,
      deployments_active: 0,
      webhooks_pending: 0,
      planning_jobs_active: 0,
    },
    attention: [],
    tasks,
    recommendations: [],
    campaigns: [],
    planning_jobs: [],
    deployments: [],
    metrics: [],
    checkpoints: [],
    audit: [],
  };
}

const conversations: ConversationSummaryResponse = {
  conversations: [],
  counts: { running: 2, complete: 8, archived: 1 },
  active_agents: [],
  filters: {},
};

describe("Studio model", () => {
  it("keeps only active task states", () => {
    expect(activeTasks([task("running"), task("completed"), task("waiting_review")])).toHaveLength(2);
  });

  it("prioritizes human attention without hiding later actions", () => {
    const control = overview([task("running")]);
    control.attention = Array.from({ length: 4 }, (_, index) =>
      ({
        id: `ATT-${index + 1}`,
        project_id: 1,
        category: "review",
        entity_type: "agent_task",
        entity_id: `TASK-${index + 1}`,
        title: `Evidence ${index + 1} prüfen`,
        consequence: "Merge bleibt gesperrt.",
        recommendation: "Tests und Änderungen prüfen.",
        urgency: "high",
        status: "open",
      }),
    );

    const actions = buildNextActions({
      control,
      conversations,
      projects: [project({ antigravity_linked: false })],
    });

    expect(actions).toHaveLength(7);
    expect(actions[0]).toMatchObject({
      title: "Evidence 1 prüfen",
      status: "current",
      href: "#/automation",
    });
    expect(actions.slice(0, 4).map((action) => action.title)).toEqual([
      "Evidence 1 prüfen",
      "Evidence 2 prüfen",
      "Evidence 3 prüfen",
      "Evidence 4 prüfen",
    ]);
  });

  it("offers repository import for an empty Studio", () => {
    const actions = buildNextActions({ control: overview(), projects: [] });
    expect(actions.at(0)?.title).toBe("Erstes Repository hinzufügen");
  });

  it("derives project health from real bootstrap and link fields", () => {
    expect(projectHealth(project()).label).toBe("Gesund");
    expect(projectHealth(project({ antigravity_linked: false })).label).toBe("Aufmerksamkeit");
    expect(projectHealth(project({ git_branch: "directory_missing" })).label).toBe("Blockiert");
  });
});
