import type { SystemOverviewResponse } from "@/api/contracts";
import { apiRequest } from "@/api/client";

export function getSystemOverview() {
  return apiRequest<SystemOverviewResponse>("/api/system/overview");
}
