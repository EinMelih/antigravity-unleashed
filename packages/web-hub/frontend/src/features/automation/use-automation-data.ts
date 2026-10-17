import { useQuery } from "@tanstack/react-query";

import { listIdeaSeeds } from "@/features/automation/api";
import { getControlOverview, getProjects, getWorkers } from "@/features/studio/api";
import { useHubHealth } from "@/hooks/use-hub-health";

export function useAutomationData() {
  const health = useHubHealth();
  const control = useQuery({
    queryKey: ["control-overview"],
    queryFn: getControlOverview,
    refetchInterval: 5_000,
  });
  const workers = useQuery({
    queryKey: ["antigravity-workers"],
    queryFn: getWorkers,
    refetchInterval: 5_000,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    refetchInterval: 20_000,
  });
  const ideaSeeds = useQuery({
    queryKey: ["idea-seeds"],
    queryFn: () => listIdeaSeeds(),
    refetchInterval: 10_000,
  });

  return { health, control, workers, projects, ideaSeeds };
}
