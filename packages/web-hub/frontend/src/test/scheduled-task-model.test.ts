import { describe, expect, it } from "vitest";

import type { AntiGravityProject, ScheduledTask } from "@/api/contracts";
import {
  buildSchedule,
  filterTasks,
  friendlySchedule,
  nextRun,
  parseSchedule,
} from "@/features/scheduled-tasks/model";

const project: AntiGravityProject = { display_name: "Antigravity Agent", id: "project-1", name: "Antigravity Agent" };
const task: ScheduledTask = {
  all_projects: false,
  command: ["agent", "run"],
  enabled: true,
  id: "daily-check",
  is_bundled: false,
  last_error: "",
  name: "Täglicher Check",
  project_id: "project-1",
  prompt: "Prüfe offene Pull Requests",
  schedule: "0 9 * * *",
  start_time_ms: "",
  status_code: 0,
};

describe("scheduled task model", () => {
  it("parses friendly daily and weekly schedules", () => {
    expect(parseSchedule("0 9 * * *")).toMatchObject({ kind: "daily", time: "09:00" });
    expect(parseSchedule("30 14 * * 1")).toMatchObject({ kind: "weekly", time: "14:30", weekday: "1" });
    expect(friendlySchedule("30 14 * * 1")).toBe("Montag · 14:30");
  });

  it("keeps custom cron and builds simple schedules", () => {
    expect(parseSchedule("*/10 * * * *").kind).toBe("custom");
    expect(buildSchedule("daily", "08:15", "1", "")).toBe("15 8 * * *");
    expect(buildSchedule("weekly", "08:15", "5", "")).toBe("15 8 * * 5");
  });

  it("computes the next daily execution", () => {
    const label = nextRun("0 9 * * *", new Date("2026-08-03T10:00:00"));
    expect(label).toContain("09:00");
  });

  it("filters status and project-aware search", () => {
    const paused = { ...task, enabled: false, id: "paused", name: "Pausiert" };
    const failed = { ...task, id: "failed", last_error: "Netzwerkfehler", name: "Fehler" };
    expect(filterTasks([task, paused, failed], [project], "active", "")).toEqual([task, failed]);
    expect(filterTasks([task, paused, failed], [project], "error", "")).toEqual([failed]);
    expect(filterTasks([task], [project], "all", "antigravity")).toEqual([task]);
  });
});
