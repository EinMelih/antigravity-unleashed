import type {
  AntiGravityProjectsResponse,
  ScheduledTask,
  ScheduledTaskEventsResponse,
  ScheduledTaskInput,
  ScheduledTasksResponse,
} from "@/api/contracts";
import { apiRequest } from "@/api/client";

const jsonHeaders = { "Content-Type": "application/json" };

export function getScheduledTasks() {
  return apiRequest<ScheduledTasksResponse>("/api/antigravity/scheduled-tasks");
}

export function getAntiGravityProjects() {
  return apiRequest<AntiGravityProjectsResponse>("/api/antigravity/projects");
}

export function createScheduledTask(input: ScheduledTaskInput) {
  return apiRequest<ScheduledTask>("/api/antigravity/scheduled-tasks", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function updateScheduledTask(taskId: string, input: ScheduledTaskInput) {
  return apiRequest<ScheduledTask>(
    `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}`,
    { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(input) },
  );
}

export function setScheduledTaskEnabled(taskId: string, enabled: boolean) {
  return apiRequest<ScheduledTask>(
    `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" },
  );
}

export function restartScheduledTask(taskId: string) {
  return apiRequest<{ success: boolean; task_id: string }>(
    `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/restart`,
    { method: "POST" },
  );
}

export function deleteScheduledTask(taskId: string) {
  return apiRequest<{ success: boolean; task_id: string }>(
    `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}`,
    { method: "DELETE" },
  );
}

export function getScheduledTaskEvents(taskId: string) {
  return apiRequest<ScheduledTaskEventsResponse>(
    `/api/antigravity/scheduled-tasks/${encodeURIComponent(taskId)}/events`,
  );
}
