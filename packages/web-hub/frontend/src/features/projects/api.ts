import type {
  ControlOverviewResponse,
  ConversationCatalogResponse,
  ProjectIdeResponse,
  ProjectRuntimeProfile,
  ProjectRuntimeServiceStatus,
  ProjectRuntimeSnapshot,
  ProjectScreenshotResponse,
  ProjectStackResponse,
  ScheduledTasksResponse,
  WorkersResponse,
} from "@/api/contracts";
import { apiRequest } from "@/api/client";

const jsonHeaders = { "Content-Type": "application/json" };

export function getProjectControlOverview(projectId: number) {
  return apiRequest<ControlOverviewResponse>(`/api/control-center/overview?project_id=${projectId}`);
}

export function getProjectConversations(projectId: number) {
  return apiRequest<ConversationCatalogResponse>(
    `/api/antigravity/conversations?project_id=${projectId}&type=all&status=running,complete,archived`,
  );
}

export function getProjectScheduledTasks() {
  return apiRequest<ScheduledTasksResponse>("/api/antigravity/scheduled-tasks");
}

export function getProjectWorkers() {
  return apiRequest<WorkersResponse>("/api/antigravity/workers");
}

export function getProjectRuntime(projectId: number) {
  return apiRequest<ProjectRuntimeSnapshot>(`/api/projects/${projectId}/runtime`);
}

export function getProjectStack(projectId: number) {
  return apiRequest<ProjectStackResponse>(`/api/projects/${projectId}/stack`);
}

export function saveProjectRuntime(projectId: number, profile: ProjectRuntimeProfile) {
  return apiRequest<ProjectRuntimeSnapshot & { success: boolean }>(
    `/api/projects/${projectId}/runtime`,
    { method: "PUT", headers: jsonHeaders, body: JSON.stringify(profile) },
  );
}

export function startProjectRuntime(projectId: number, service: "frontend" | "backend") {
  return apiRequest<ProjectRuntimeServiceStatus>(
    `/api/projects/${projectId}/runtime/${service}/start`,
    { method: "POST" },
  );
}

export function setupProjectRuntime(projectId: number, service: "frontend" | "backend") {
  return apiRequest<ProjectRuntimeServiceStatus>(
    `/api/projects/${projectId}/runtime/${service}/setup`,
    { method: "POST" },
  );
}

export function stopProjectRuntime(projectId: number, service: "frontend" | "backend") {
  return apiRequest<ProjectRuntimeServiceStatus>(
    `/api/projects/${projectId}/runtime/${service}/stop`,
    { method: "POST" },
  );
}

export function captureProjectScreenshot(projectId: number) {
  return apiRequest<ProjectScreenshotResponse>(
    `/api/projects/${projectId}/runtime/screenshot`,
    { method: "POST" },
  );
}

export function openProjectIde(projectId: number) {
  return apiRequest<ProjectIdeResponse>(`/api/projects/${projectId}/ide/open`, { method: "POST" });
}

export function unlinkAntiGravityProject(projectId: number) {
  return apiRequest<{ success: boolean }>(`/api/projects/${projectId}/antigravity-link`, {
    method: "DELETE",
  });
}

export function removeProjectFromHub(projectId: number) {
  return apiRequest<{ success: boolean }>(`/api/projects/${projectId}`, { method: "DELETE" });
}
