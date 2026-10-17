import { apiRequest } from "@/api/client";
import type { ControlKnowledgeChainsResponse } from "@/api/contracts";

export function getKnowledgeChains(projectId?: number) {
  const query = Number.isInteger(projectId) && Number(projectId) > 0
    ? `?project_id=${encodeURIComponent(String(projectId))}`
    : "";
  return apiRequest<ControlKnowledgeChainsResponse>(
    `/api/control-center/knowledge-chains${query}`,
  );
}
