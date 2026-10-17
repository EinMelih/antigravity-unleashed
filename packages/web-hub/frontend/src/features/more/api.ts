import { apiRequest } from "@/api/client";
import type {
  CodexModel,
  CodexStatus,
  CustomModel,
  CustomModelInput,
  CustomModelsResponse,
  GitHubStatusResponse,
  LessonsResponse,
} from "@/api/contracts";

export type ControlPlaneDocumentId =
  | "operator"
  | "index"
  | "api"
  | "database"
  | "codebase"
  | "dependencies"
  | "configuration"
  | "operations"
  | "knowledge-chain"
  | "plan-amendments"
  | "routes"
  | "schema"
  | "imports"
  | "frontend-imports";

export function getControlPlaneDocumentation(documentId?: ControlPlaneDocumentId) {
  const path = documentId
    ? `/api/control-plane/docs/${documentId}`
    : "/api/control-plane/docs";
  return apiRequest<string>(path, { headers: { Accept: "text/markdown" } });
}

export function getLessons() {
  return apiRequest<LessonsResponse>("/api/lessons");
}

export function getGitHubStatus() {
  return apiRequest<GitHubStatusResponse>("/api/github/status");
}

export function getCustomModels() {
  return apiRequest<CustomModelsResponse>("/api/antigravity/custom-models");
}

export function saveCustomModel(input: CustomModelInput) {
  return apiRequest<{ model: CustomModel }>("/api/antigravity/custom-models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function testCustomModel(id: number) {
  return apiRequest<{ success: boolean; model_count?: number }>(`/api/antigravity/custom-models/${id}/test`, { method: "POST" });
}

export function deleteCustomModel(id: number) {
  return apiRequest<{ success: boolean }>(`/api/antigravity/custom-models/${id}`, { method: "DELETE" });
}

export function getCodexStatus() {
  return apiRequest<CodexStatus>("/api/antigravity/codex/status");
}

export function getCodexModels() {
  return apiRequest<{ models: CodexModel[] }>("/api/antigravity/codex/models");
}

export function startCodexLogin() {
  return apiRequest<{ login_id: string; auth_url: string }>("/api/antigravity/codex/login/start", { method: "POST" });
}

export function cancelCodexLogin(loginId: string) {
  return apiRequest<{ status: string }>("/api/antigravity/codex/login/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login_id: loginId }),
  });
}

export function logoutCodex() {
  return apiRequest<{ success: boolean }>("/api/antigravity/codex/logout", { method: "POST" });
}
