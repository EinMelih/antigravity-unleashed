import { useQuery } from "@tanstack/react-query";

import {
  getActiveModel,
  getChatHistory,
  getConversationCatalog,
  getModelCatalog,
} from "@/features/chats/api";
import { getProjects, getWorkers } from "@/features/studio/api";

export function useConversationCatalog() {
  return useQuery({
    queryKey: ["conversation-catalog"],
    queryFn: getConversationCatalog,
    refetchInterval: 3_000,
  });
}

export function useChatContextData() {
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: getProjects,
    refetchInterval: 20_000,
  });
  const workers = useQuery({
    queryKey: ["antigravity-workers"],
    queryFn: getWorkers,
    refetchInterval: 5_000,
  });

  return { projects, workers };
}

export function useNewChatModels(open: boolean) {
  return useQuery({
    queryKey: ["antigravity-models"],
    queryFn: getModelCatalog,
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });
}

export function useChatPaneData(
  conversationId: string,
  options: { active: boolean; running: boolean },
) {
  const history = useQuery({
    queryKey: ["chat-history", conversationId],
    queryFn: () => getChatHistory(conversationId),
    refetchInterval: options.active || options.running ? 2_000 : 8_000,
  });
  const models = useQuery({
    queryKey: ["antigravity-models"],
    queryFn: getModelCatalog,
    refetchInterval: 30_000,
  });
  const activeModel = useQuery({
    queryKey: ["active-model", conversationId],
    queryFn: () => getActiveModel(conversationId),
    refetchInterval: options.active ? 10_000 : 30_000,
  });
  return { activeModel, history, models };
}
