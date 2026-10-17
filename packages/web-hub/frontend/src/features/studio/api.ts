import { apiRequest } from "@/api/client";
import type {
  ControlOverviewResponse,
  ConversationSummaryResponse,
  AntigravityInstancesResponse,
  ProjectsResponse,
  ProjectArchiveResponse,
  ProjectRemovalImpact,
  WorkersResponse,
} from "@/api/contracts";

export function getControlOverview() {
  return apiRequest<ControlOverviewResponse>("/api/control-center/overview");
}

export function getConversationSummary() {
  return apiRequest<ConversationSummaryResponse>(
    "/api/antigravity/conversations?type=all&status=running,complete,archived&summary_only=1",
  );
}

export function getWorkers() {
  return apiRequest<WorkersResponse>("/api/antigravity/workers");
}

export function getAntigravityInstances() {
  return apiRequest<AntigravityInstancesResponse>("/api/antigravity/instances");
}

export function getProjects() {
  return apiRequest<ProjectsResponse>("/api/projects");
}

export function getProjectRemovalImpact(projectId: number) {
  return apiRequest<ProjectRemovalImpact>(`/api/projects/${projectId}/removal-impact`);
}

export function archiveProject(projectId: number) {
  return apiRequest<ProjectArchiveResponse>(`/api/projects/${projectId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: "hub_only", delete_remote_repository: false }),
  });
}

export function deleteProjectGitHubRepository(projectId: number, repository: string) {
  return apiRequest<{ success: boolean; repository: string; already_deleted?: boolean }>(
    `/api/projects/${projectId}/github-repository`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, repository }),
    },
  );
}
