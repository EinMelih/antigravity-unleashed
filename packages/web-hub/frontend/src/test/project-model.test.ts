import { describe, expect, it } from "vitest";

import type { AntiGravityProject, HubProject, ProjectRuntimeSnapshot } from "@/api/contracts";
import {
  projectAntiGravityLinkState,
  projectMetrics,
  projectNextActions,
} from "@/features/projects/model";
import { automationOverview } from "@/test/automation-fixtures";

const project: HubProject = {
  id: 7,
  name: "Example",
  path: "D:\\Projects\\example",
  github_url: "https://github.com/example/project",
  github_owner: "example",
  github_repo: "project",
  default_branch: "main",
  git_branch: "main",
  source_kind: "github",
  github_bootstrap_required: false,
  github_bootstrap_status: "ready",
  antigravity_linked: true,
  antigravity_project_name: "Example",
};

function runtime(frontendActive: boolean): ProjectRuntimeSnapshot {
  const service = {
    service: "frontend" as const,
    status: frontendActive ? "running" as const : "stopped" as const,
    active: frontendActive,
    managed: frontendActive,
    pid: frontendActive ? 1200 : null,
    url: "http://127.0.0.1:5173/",
    config: {
      name: "Frontend",
      enabled: true,
      command: "npm run dev",
      cwd: ".",
      host: "127.0.0.1",
      port: 5173,
      health_path: "/",
      detected: true,
      reason: "Vite erkannt",
    },
    log: "",
  };
  return {
    project_id: 7,
    configured: false,
    storage_path: "C:\\Users\\Example\\.gemini\\config\\antigravity-hub\\project-runtimes.json",
    profile: {
      project_id: 7,
      version: 1,
      services: {
        frontend: service.config,
        backend: { ...service.config, name: "Backend", enabled: false, port: 8008 },
      },
    },
    services: {
      frontend: { ...service, started_at: frontendActive ? 1_785_000_000 : null },
      backend: { ...service, service: "backend", active: false, managed: false, pid: null, started_at: null, status: "stopped" as const, url: "http://127.0.0.1:8008/", config: { ...service.config, name: "Backend", enabled: false, port: 8008 } },
    },
  };
}

describe("project model", () => {
  it("distinguishes a live native project link from a stale saved UUID", () => {
    const linkedProject = { ...project, integrity_project_uuid: "native-1" };
    const catalog: AntiGravityProject[] = [{
      id: "native-1",
      name: "Example",
      display_name: "Example",
      project_uuid: "native-1",
    }];

    expect(projectAntiGravityLinkState(linkedProject, catalog, "ready")).toBe("linked");
    expect(projectAntiGravityLinkState(linkedProject, [], "ready")).toBe("stale");
    expect(projectAntiGravityLinkState(
      { ...linkedProject, integrity_project_uuid: "" },
      catalog,
      "ready",
    )).toBe("pending_confirmation");
    expect(projectAntiGravityLinkState(
      { ...linkedProject, antigravity_linked: false },
      catalog,
      "ready",
    )).toBe("unlinked");
    expect(projectAntiGravityLinkState(linkedProject, undefined, "pending")).toBe("checking");
    expect(projectAntiGravityLinkState(linkedProject, undefined, "error")).toBe("unavailable");
  });

  it("offers a local frontend start as an internal project action", () => {
    const actions = projectNextActions(project, undefined, runtime(false));
    expect(actions[0]).toMatchObject({
      label: "Frontend starten",
      href: "#/projects/7",
    });
  });

  it("does not offer another start when the frontend is already active", () => {
    const actions = projectNextActions(project, undefined, runtime(true));
    expect(actions.some((action) => action.label === "Frontend starten")).toBe(false);
  });

  it("keeps more than three real next actions reachable", () => {
    const overview = automationOverview();
    const secondCandidate = overview.campaigns[0]?.pr_candidates[1];
    if (!secondCandidate?.task) throw new Error("Automation fixture requires two tasks");
    secondCandidate.status = "approved";
    secondCandidate.task.status = "running";

    const actions = projectNextActions(
      { ...project, id: 52, antigravity_linked: false },
      overview,
      runtime(false),
    );

    expect(actions).toHaveLength(4);
    expect(actions.map((action) => action.description)).toEqual(
      expect.arrayContaining(["Suche zugänglich machen", "Dokumentation abschließen"]),
    );
  });

  it("derives compact project metrics from control data", () => {
    const overview = automationOverview();
    const metrics = projectMetrics(overview, undefined);
    expect(metrics.openPullRequests).toBeGreaterThanOrEqual(0);
    expect(metrics.activeAgents).toBe(overview.summary.tasks_active);
    expect(metrics.blockers).toBeGreaterThanOrEqual(overview.summary.attention_open);
  });

  it("does not count a completed and merged task as an open pull request", () => {
    const overview = automationOverview();
    const task = overview.tasks[0];
    if (!task) throw new Error("Automation fixture requires a task");
    task.status = "completed";
    task.pr_url = "https://github.com/example/project/pull/12";
    task.merged_sha = "b".repeat(40);

    expect(projectMetrics(overview, undefined).openPullRequests).toBe(0);
  });
});
