import { useQuery } from "@tanstack/react-query";

import {
  getControlOverview,
  getConversationSummary,
  getProjects,
} from "@/features/studio/api";

const LIVE_REFRESH_MS = 5_000;
const PROJECT_REFRESH_MS = 20_000;

export function useStudioData() {
  const control = useQuery({
    queryKey: ["control-overview"],
    queryFn: getControlOverview,
    refetchInterval: LIVE_REFRESH_MS,
  });
  const conversations = useQuery({
    queryKey: ["conversation-summary"],
    queryFn: getConversationSummary,
    refetchInterval: LIVE_REFRESH_MS,
  });
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    refetchInterval: PROJECT_REFRESH_MS,
  });

  return { control, conversations, projects };
}
