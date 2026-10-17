import { ApiError } from "@/api/errors";

export interface ConversationDeleteFailure {
  conversationId: string;
  message: string;
}

export interface ConversationDeleteProgress {
  completed: number;
  total: number;
}

export interface ConversationDeleteResult {
  alreadyAbsentIds: string[];
  cleanupWarnings: ConversationDeleteFailure[];
  deletedIds: string[];
  failures: ConversationDeleteFailure[];
}

export function cleanupWarningSuffix(count: number): string {
  if (count <= 0) return "";
  const subject = count === 1 ? "Bei 1 Chat" : `Bei ${count} Chats`;
  return ` ${subject} konnten lokale Restdateien noch nicht bereinigt werden.`;
}

type DeleteConversation = (conversationId: string) => Promise<unknown>;

export function updateConversationSelection(
  selectedIds: ReadonlySet<string>,
  conversationId: string,
  selected: boolean,
): Set<string> {
  const next = new Set(selectedIds);
  if (selected) next.add(conversationId);
  else next.delete(conversationId);
  return next;
}

export function includeMissingSelectedConversations<T extends { convo_id: string }>(
  conversations: readonly T[],
  selectedIds: ReadonlySet<string>,
  snapshots: ReadonlyMap<string, T>,
): T[] {
  const knownIds = new Set(conversations.map((conversation) => conversation.convo_id));
  const missingSelected = [...selectedIds]
    .filter((conversationId) => !knownIds.has(conversationId))
    .flatMap((conversationId) => {
      const snapshot = snapshots.get(conversationId);
      return snapshot ? [snapshot] : [];
    });
  return [...conversations, ...missingSelected];
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === "conversation_busy") {
    return "Der Chat arbeitet gerade und bleibt geschützt.";
  }
  if (error instanceof ApiError && error.code === "conversation_state_unavailable") {
    return "Der Anti-Gravity-Zustand konnte nicht sicher geprüft werden. Der Chat bleibt geschützt.";
  }
  if (error instanceof ApiError && error.code === "native_delete_unconfirmed") {
    return "Anti-Gravity hat die Löschung nicht bestätigt. Der Chat bleibt erhalten.";
  }
  if (error instanceof ApiError && error.code === "local_cleanup_incomplete") {
    return "Der Chat wurde in Anti-Gravity entfernt, aber lokale Restdateien konnten noch nicht bereinigt werden.";
  }
  return error instanceof Error ? error.message : String(error);
}

export async function deleteConversationsSequentially(
  conversationIds: readonly string[],
  deleteConversation: DeleteConversation,
  onProgress?: (progress: ConversationDeleteProgress) => void,
): Promise<ConversationDeleteResult> {
  const uniqueIds = [...new Set(conversationIds.filter(Boolean))];
  const result: ConversationDeleteResult = {
    alreadyAbsentIds: [],
    cleanupWarnings: [],
    deletedIds: [],
    failures: [],
  };

  for (const [index, conversationId] of uniqueIds.entries()) {
    try {
      await deleteConversation(conversationId);
      result.deletedIds.push(conversationId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        result.alreadyAbsentIds.push(conversationId);
        result.deletedIds.push(conversationId);
      } else if (error instanceof ApiError && error.code === "local_cleanup_incomplete") {
        result.deletedIds.push(conversationId);
        result.cleanupWarnings.push({
          conversationId,
          message: errorMessage(error),
        });
      } else {
        result.failures.push({ conversationId, message: errorMessage(error) });
      }
    }
    onProgress?.({ completed: index + 1, total: uniqueIds.length });
  }

  return result;
}
