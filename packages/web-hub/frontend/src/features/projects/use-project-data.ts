import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/api/errors";
import {
  getProjectControlOverview,
  getProjectConversations,
  getProjectRuntime,
  getProjectScheduledTasks,
  getProjectStack,
  getProjectWorkers,
} from "@/features/projects/api";
import { getProjects } from "@/features/studio/api";

export function useProjectData(projectId: number) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects, refetchInterval: 20_000 });
  const control = useQuery({
    queryKey: ["control-overview", projectId],
    queryFn: () => getProjectControlOverview(projectId),
    refetchInterval: 5_000,
  });
  const runtime = useQuery({
    queryKey: ["project-runtime", projectId],
    queryFn: () => getProjectRuntime(projectId),
    refetchInterval: 3_000,
  });
  const stack = useQuery({
    queryKey: ["project-stack", projectId],
    queryFn: () => getProjectStack(projectId),
    refetchInterval: 30_000,
  });
  const conversations = useQuery({
    queryKey: ["project-conversations", projectId],
    queryFn: () => getProjectConversations(projectId),
    refetchInterval: 5_000,
  });
  const workers = useQuery({ queryKey: ["antigravity-workers"], queryFn: getProjectWorkers, refetchInterval: 5_000 });
  const tasks = useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: getProjectScheduledTasks,
    refetchInterval: 10_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && [503, 504].includes(error.status ?? 0)) && failureCount < 1,
  });
  return { control, conversations, projects, runtime, stack, tasks, workers };
}
