import type { AntiGravityProject, ScheduledTask } from "@/api/contracts";

export type TaskFilter = "all" | "active" | "paused" | "error";
export type ScheduleKind = "daily" | "weekly" | "custom";

const weekdays = ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"];

export function parseSchedule(schedule: string) {
  const parts = schedule.trim().split(/\s+/);
  if (parts.length === 5) {
    const [minute = "0", hour = "9", day, month, weekday] = parts;
    const numericTime = /^\d+$/.test(minute) && /^\d+$/.test(hour);
    const time = numericTime
      ? `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`
      : "09:00";
    if (numericTime && day === "*" && month === "*" && weekday === "*") {
      return { kind: "daily" as const, time, weekday: "1", cron: schedule };
    }
    if (numericTime && day === "*" && month === "*" && /^[0-6]$/.test(weekday ?? "")) {
      return { kind: "weekly" as const, time, weekday: weekday ?? "1", cron: schedule };
    }
  }
  return { kind: "custom" as const, time: "09:00", weekday: "1", cron: schedule || "0 9 * * *" };
}

export function buildSchedule(kind: ScheduleKind, time: string, weekday: string, cron: string) {
  if (kind === "custom") return cron.trim();
  const [hour = "9", minute = "0"] = time.split(":");
  return `${Number(minute)} ${Number(hour)} * * ${kind === "weekly" ? weekday : "*"}`;
}

export function friendlySchedule(schedule: string) {
  const parsed = parseSchedule(schedule);
  if (parsed.kind === "daily") return `Täglich · ${parsed.time}`;
  if (parsed.kind === "weekly") return `${weekdays[Number(parsed.weekday)] ?? "Wöchentlich"} · ${parsed.time}`;
  return `Cron · ${schedule}`;
}

export function nextRun(schedule: string, now = new Date()) {
  const parsed = parseSchedule(schedule);
  if (parsed.kind === "custom") return "Nach Cron-Zeitplan";
  const [hour = 9, minute = 0] = parsed.time.split(":").map(Number);
  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setHours(hour, minute, 0, 0);
  if (parsed.kind === "daily") {
    if (next <= now) next.setDate(next.getDate() + 1);
  } else {
    const target = Number(parsed.weekday);
    let distance = (target - now.getDay() + 7) % 7;
    if (distance === 0 && next <= now) distance = 7;
    next.setDate(now.getDate() + distance);
  }
  return new Intl.DateTimeFormat("de-DE", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(next);
}

export function taskProjectName(task: ScheduledTask, projects: AntiGravityProject[]) {
  if (task.all_projects) return "Alle Projekte";
  return projects.find((project) => project.id === task.project_id)?.display_name || task.project_id || "Kein Projekt";
}

export function filterTasks(
  tasks: ScheduledTask[],
  projects: AntiGravityProject[],
  filter: TaskFilter,
  search: string,
) {
  const needle = search.trim().toLocaleLowerCase("de");
  return tasks.filter((task) => {
    if (filter === "active" && !task.enabled) return false;
    if (filter === "paused" && task.enabled) return false;
    if (filter === "error" && !task.last_error) return false;
    if (!needle) return true;
    return [task.name, task.id, task.prompt, task.schedule, taskProjectName(task, projects)]
      .some((value) => value.toLocaleLowerCase("de").includes(needle));
  });
}

export function slugifyTaskName(name: string) {
  return name
    .replace(/[\\/]/g, " ")
    .trim()
    .toLocaleLowerCase("en")
    .replace(/[^a-z0-9\s_-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
}
