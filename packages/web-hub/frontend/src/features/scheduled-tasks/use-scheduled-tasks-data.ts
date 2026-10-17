import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/api/errors";
import {
  getAntiGravityProjects,
  getScheduledTaskEvents,
  getScheduledTasks,
} from "@/features/scheduled-tasks/api";

export function useScheduledTasksData(selectedTaskId: string | null) {
  const tasks = useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: getScheduledTasks,
    refetchInterval: 5_000,
    retry: (failureCount, error) =>
      !(error instanceof ApiError && [503, 504].includes(error.status ?? 0))
      && failureCount < 1,
  });
  const projects = useQuery({
    queryKey: ["antigravity-projects"],
    queryFn: getAntiGravityProjects,
    refetchInterval: 30_000,
  });
  const events = useQuery({
    queryKey: ["scheduled-task-events", selectedTaskId],
    queryFn: () => getScheduledTaskEvents(selectedTaskId ?? ""),
    enabled: Boolean(selectedTaskId),
    refetchInterval: selectedTaskId ? 10_000 : false,
  });
  return { events, projects, tasks };
}
