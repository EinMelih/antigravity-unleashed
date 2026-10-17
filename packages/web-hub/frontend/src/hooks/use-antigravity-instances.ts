import { useQuery } from "@tanstack/react-query";

import { getAntigravityInstances } from "@/features/studio/api";

const BUSY_ACTIVITIES = new Set(["preparing", "sending", "working", "waiting_human"]);

export function useAntigravityInstances() {
  return useQuery({
    queryKey: ["antigravity-instances"],
    queryFn: getAntigravityInstances,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.instances.some((instance) => BUSY_ACTIVITIES.has(instance.activity))
        ? 1_500
        : 6_000;
    },
  });
}
