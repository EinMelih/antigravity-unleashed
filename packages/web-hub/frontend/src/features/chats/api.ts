import type {
  ActiveModelResponse,
  ChatAttachment,
  ChatDeliveryResponse,
  ChatHistoryResponse,
  ConversationCatalogResponse,
  ModelCatalogItem,
  ModelCatalogResponse,
} from "@/api/contracts";
import { apiRequest } from "@/api/client";

const jsonHeaders = { "Content-Type": "application/json" };

export interface VoiceDictationResponse {
  error?: string;
  isRecording: boolean;
  success: boolean;
  text: string;
  window?: {
    window_id?: string;
    target_id?: string;
  };
}

export function getConversationCatalog() {
  return apiRequest<ConversationCatalogResponse>(
    "/api/antigravity/conversations?type=all&status=running,complete,archived",
  );
}

export function getChatHistory(conversationId: string) {
  return apiRequest<ChatHistoryResponse>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}/history`,
  );
}

export function getModelCatalog() {
  return apiRequest<ModelCatalogResponse>("/api/antigravity/models");
}

export function getActiveModel(conversationId: string) {
  return apiRequest<ActiveModelResponse>(
    `/api/antigravity/active-model?convo_id=${encodeURIComponent(conversationId)}`,
  );
}

export function createChat(input: {
  conversationType: "normal" | "project";
  message: string;
  attachments: ChatAttachment[];
  model?: ModelCatalogItem;
  projectId?: number;
}) {
  if (input.model?.source === "custom" || input.model?.source === "codex") {
    return apiRequest<ChatDeliveryResponse>("/api/antigravity/proxy-chats", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        source: input.model.source,
        project_id: input.projectId,
        custom_model_id: input.model.custom_model_id,
        model_id: input.model.model_id,
        reasoning_effort: input.model.default_reasoning_effort,
        message: input.message,
        attachments: input.attachments,
      }),
    });
  }
  return apiRequest<ChatDeliveryResponse>("/api/antigravity/chats", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      conversation_type: input.conversationType,
      project_id: input.projectId,
      model: input.model?.model_id || input.model?.label,
      message: input.message,
      attachments: input.attachments,
    }),
  });
}

export function sendChatMessage(
  conversationId: string,
  message: string,
  attachments: ChatAttachment[],
) {
  return apiRequest<ChatDeliveryResponse>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}/message`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ message, attachments }),
    },
  );
}

export function setConversationArchived(conversationId: string, archived: boolean) {
  const action = archived ? "archive" : "restore";
  return apiRequest<{ success: boolean; archived: boolean; verified: boolean }>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}/${action}`,
    { method: "POST" },
  );
}

export function deleteConversation(conversationId: string) {
  return apiRequest<{ success: boolean; conversation_id: string }>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
  );
}

export function openConversationWindow(conversationId: string) {
  return apiRequest<{ success: boolean; window?: Record<string, unknown> }>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}/window`,
    { method: "POST" },
  );
}

export function openConversationBrain(conversationId: string) {
  return apiRequest<{ success: boolean; path: string }>(
    `/api/antigravity/chats/${encodeURIComponent(conversationId)}/brain/open`,
    { method: "POST" },
  );
}

export function switchConversationModel(conversationId: string, model: ModelCatalogItem) {
  return apiRequest<ActiveModelResponse & { success: boolean }>(
    "/api/antigravity/active-model",
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({
        convo_id: conversationId,
        model: model.label,
        source: model.source,
        custom_model_id: model.custom_model_id,
        model_id: model.model_id,
        reasoning_effort: model.default_reasoning_effort,
      }),
    },
  );
}

export function startVoiceDictation(text: string) {
  return apiRequest<VoiceDictationResponse>("/api/voice/dictation/start", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ field_label: "Chat message", text }),
  });
}

export function getVoiceDictationStatus() {
  return apiRequest<VoiceDictationResponse>("/api/voice/dictation/status");
}

export function stopVoiceDictation() {
  return apiRequest<VoiceDictationResponse>("/api/voice/dictation/stop", { method: "POST" });
}
