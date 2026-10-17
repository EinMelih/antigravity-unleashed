import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ChatHistoryEntry, ConversationCatalogItem } from "@/api/contracts";
import { ChatWorkspace, type DeliveryPhase } from "@/features/chats/chat-workspace";
import type { ComposerPayload } from "@/features/chats/chat-composer";
import {
  deleteConversation,
  openConversationBrain,
  openConversationWindow,
  sendChatMessage,
  setConversationArchived,
  switchConversationModel,
} from "@/features/chats/api";
import { useChatPaneData } from "@/features/chats/use-chats-data";

interface ChatPaneProps {
  active: boolean;
  conversation: ConversationCatalogItem;
  onDeleted: (conversationId: string) => void;
}

export function ChatPane({ active, conversation, onDeleted }: ChatPaneProps) {
  const conversationId = conversation.convo_id;
  const queryClient = useQueryClient();
  const data = useChatPaneData(conversationId, {
    active,
    running: conversation.status === "running",
  });
  const [busyAction, setBusyAction] = useState("");
  const [deliveryPhase, setDeliveryPhase] = useState<DeliveryPhase>("idle");
  const [modelSwitching, setModelSwitching] = useState(false);
  const [modelError, setModelError] = useState("");
  const [optimisticEntry, setOptimisticEntry] = useState<ChatHistoryEntry | null>(null);

  async function invalidateChat() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["conversation-catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["chat-history", conversationId] }),
      queryClient.invalidateQueries({ queryKey: ["antigravity-workers"] }),
      queryClient.invalidateQueries({ queryKey: ["antigravity-instances"] }),
    ]);
  }

  async function send(payload: ComposerPayload) {
    const pending: ChatHistoryEntry = {
      attachments: payload.attachments,
      content: payload.message,
      idx: Date.now(),
      role: "user",
      type: "message",
    };
    setOptimisticEntry(pending);
    setBusyAction("send");
    setDeliveryPhase("preparing");
    try {
      window.setTimeout(() => setDeliveryPhase((phase) => phase === "preparing" ? "sending" : phase), 600);
      const result = await sendChatMessage(conversationId, payload.message, payload.attachments);
      setDeliveryPhase(result.pending_verification ? "verifying" : "confirmed");
      await invalidateChat();
      await data.history.refetch();
      setOptimisticEntry(null);
      window.setTimeout(() => setDeliveryPhase("idle"), result.pending_verification ? 2_500 : 1_200);
    } catch (error) {
      setOptimisticEntry(null);
      setDeliveryPhase("error");
      window.setTimeout(() => setDeliveryPhase("idle"), 3_000);
      throw error;
    } finally {
      setBusyAction("");
    }
  }

  async function archiveChange(archived: boolean) {
    setBusyAction(archived ? "archive" : "restore");
    try {
      await setConversationArchived(conversationId, archived);
      await invalidateChat();
    } finally {
      setBusyAction("");
    }
  }

  async function remove() {
    setBusyAction("delete");
    try {
      await deleteConversation(conversationId);
      onDeleted(conversationId);
      await invalidateChat();
    } finally {
      setBusyAction("");
    }
  }

  async function switchModel(selectionId: string) {
    const model = data.models.data?.models.find((item) => {
      if (item.selection_id) return item.selection_id === selectionId;
      if (item.source === "custom") return `custom:${item.custom_model_id}` === selectionId;
      if (item.source === "codex") return `codex:${item.model_id || item.label}` === selectionId;
      return `native:${item.model_id || item.label}` === selectionId;
    });
    if (!model || selectionId === data.activeModel.data?.selection_id) return;
    setModelSwitching(true);
    setModelError("");
    try {
      const result = await switchConversationModel(conversationId, model);
      if (result.confirmed === false) {
        throw new Error(`Anti-Gravity hat den Wechsel zu „${model.label}“ nicht bestätigt.`);
      }
      await data.activeModel.refetch();
    } catch (error) {
      setModelError(error instanceof Error ? error.message : String(error));
    } finally {
      setModelSwitching(false);
    }
  }

  const activeModel = data.activeModel.data?.selection_id
    ?? (() => {
      const activeLabel = data.activeModel.data?.model ?? data.models.data?.current ?? "";
      const activeSource = data.activeModel.data?.source;
      const matching = data.models.data?.models.find((item) => item.label === activeLabel && (!activeSource || activeSource.startsWith(item.source)));
      if (matching?.selection_id) return matching.selection_id;
      if (matching?.source === "custom") return `custom:${matching.custom_model_id}`;
      if (matching?.source === "codex") return `codex:${matching.model_id || matching.label}`;
      return activeLabel ? `native:${activeLabel}` : "";
    })();
  const history = [...(data.history.data?.history ?? []), ...(optimisticEntry ? [optimisticEntry] : [])];

  return (
    <ChatWorkspace
      activeModel={activeModel}
      activePane={active}
      conversation={conversation}
      deliveryPhase={deliveryPhase}
      embedded
      history={history}
      historyLoading={data.history.isPending}
      key={conversationId}
      models={data.models.data?.models ?? []}
      modelError={modelError}
      modelSwitching={modelSwitching}
      mutationBusy={Boolean(busyAction)}
      onArchiveChange={archiveChange}
      onDelete={remove}
      onModelChange={switchModel}
      onOpenBrain={() => openConversationBrain(conversationId).then(() => undefined)}
      onOpenWindow={() => openConversationWindow(conversationId).then(() => undefined)}
      onSend={send}
    />
  );
}
