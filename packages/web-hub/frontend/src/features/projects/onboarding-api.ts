import type {
  AntiGravityProjectLinkResponse,
  AntiGravityProjectsResponse,
  CreateHubProjectInput,
  GitHubRepositoriesResponse,
  HubProject,
  ImportGitHubProjectInput,
} from "@/api/contracts";
import { apiRequest } from "@/api/client";

const jsonHeaders = { "Content-Type": "application/json" };

export function getGitHubRepositories() {
  return apiRequest<GitHubRepositoriesResponse>("/api/github/repos");
}

export function importGitHubProject(input: ImportGitHubProjectInput) {
  return apiRequest<HubProject>("/api/projects/import", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function createHubProject(input: CreateHubProjectInput) {
  return apiRequest<HubProject>("/api/projects", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(input),
  });
}

export function getAvailableAntiGravityProjects() {
  return apiRequest<AntiGravityProjectsResponse>("/api/antigravity/projects");
}

export function linkAntiGravityProject(projectId: number, antigravityProjectId: string) {
  return apiRequest<AntiGravityProjectLinkResponse>(
    `/api/projects/${projectId}/antigravity-link`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ antigravity_project_id: antigravityProjectId }),
    },
  );
}

export function createAntiGravityProject(project: HubProject) {
  return apiRequest<AntiGravityProjectLinkResponse>(
    `/api/projects/${project.id}/antigravity-project`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ workspace_path: project.path }),
    },
  );
}
