import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/api/client";
import type { HubHealthResponse } from "@/api/contracts";

export const hubHealthQueryKey = ["hub", "health"] as const;

export function useHubHealth() {
  return useQuery({
    queryKey: hubHealthQueryKey,
    queryFn: ({ signal }) =>
      apiRequest<HubHealthResponse>("/health", { signal }),
    refetchInterval: 15_000,
  });
}

export function useIsHeadlessLinux(): boolean {
  const health = useHubHealth();
  return health.data?.runtime_mode === "headless_linux";
}
