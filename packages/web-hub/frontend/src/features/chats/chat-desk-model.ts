export const CHAT_DESK_MAX_PANES = 10;
export const CHAT_DESK_STORAGE_KEY = "antigravity.chat-desk.v2";
export const CHAT_DESK_LEGACY_STORAGE_KEY = "antigravity.chat-desk.v1";

export type ChatDeskMode = "single" | "grid";

export interface ChatDeskState {
  version: 2;
  mode: ChatDeskMode;
  activeConversationId: string | null;
  panes: string[];
}

const MODES = new Set<ChatDeskMode>(["single", "grid"]);
const LEGACY_MULTIPLE_MODES = new Set(["split", "grid", "floating"]);

export function createChatDeskState(conversationId?: string | null): ChatDeskState {
  return {
    version: 2,
    mode: "single",
    activeConversationId: conversationId || null,
    panes: conversationId ? [conversationId] : [],
  };
}

export function focusDeskConversation(
  state: ChatDeskState,
  conversationId: string,
): ChatDeskState {
  if (!state.panes.includes(conversationId) || state.activeConversationId === conversationId) {
    return state;
  }
  return { ...state, activeConversationId: conversationId };
}

export function canOpenDeskConversation(
  state: ChatDeskState,
  conversationId: string,
): boolean {
  return Boolean(conversationId) && (
    state.panes.includes(conversationId)
    || state.panes.length < CHAT_DESK_MAX_PANES
  );
}

export function openDeskConversation(
  state: ChatDeskState,
  conversationId: string,
): ChatDeskState {
  if (!conversationId) return state;
  if (state.panes.includes(conversationId)) {
    return focusDeskConversation(state, conversationId);
  }
  if (!canOpenDeskConversation(state, conversationId)) return state;
  return {
    ...state,
    activeConversationId: conversationId,
    panes: [...state.panes, conversationId],
  };
}

export function closeDeskConversation(
  state: ChatDeskState,
  conversationId: string,
): ChatDeskState {
  if (!state.panes.includes(conversationId)) return state;
  const panes = state.panes.filter((paneId) => paneId !== conversationId);
  return {
    ...state,
    activeConversationId: state.activeConversationId === conversationId
      ? panes[panes.length - 1] ?? null
      : state.activeConversationId,
    panes,
  };
}

export function setChatDeskMode(state: ChatDeskState, mode: ChatDeskMode): ChatDeskState {
  if (!MODES.has(mode) || state.mode === mode) return state;
  return { ...state, mode };
}

interface SerializedChatDeskState {
  version?: unknown;
  mode?: unknown;
  activeConversationId?: unknown;
  panes?: unknown;
}

function restoreMode(candidate: SerializedChatDeskState): ChatDeskMode {
  if (candidate.version === 2) {
    return typeof candidate.mode === "string" && MODES.has(candidate.mode as ChatDeskMode)
      ? candidate.mode as ChatDeskMode
      : "single";
  }
  if (candidate.mode === "single") return "single";
  return typeof candidate.mode === "string" && LEGACY_MULTIPLE_MODES.has(candidate.mode)
    ? "grid"
    : "single";
}

function restorePaneId(value: unknown, version: unknown): string | null {
  if (version === 2) {
    return typeof value === "string" && value ? value : null;
  }
  if (!value || typeof value !== "object") return null;
  const conversationId = (value as { conversationId?: unknown }).conversationId;
  return typeof conversationId === "string" && conversationId ? conversationId : null;
}

export function restoreChatDeskState(
  serialized: string | null | undefined,
  validConversationIds: readonly string[],
): ChatDeskState {
  let parsed: unknown;
  try {
    parsed = serialized ? JSON.parse(serialized) : null;
  } catch {
    parsed = null;
  }
  if (!parsed || typeof parsed !== "object") {
    return createChatDeskState(validConversationIds[0]);
  }

  const candidate = parsed as SerializedChatDeskState;
  if (!Array.isArray(candidate.panes)) {
    return createChatDeskState(validConversationIds[0]);
  }

  const validIds = new Set(validConversationIds);
  const seen = new Set<string>();
  const panes = candidate.panes
    .map((pane) => restorePaneId(pane, candidate.version))
    .filter((conversationId): conversationId is string => Boolean(
      conversationId
      && validIds.has(conversationId)
      && !seen.has(conversationId)
      && seen.add(conversationId),
    ))
    .slice(0, CHAT_DESK_MAX_PANES);
  const requestedActive = typeof candidate.activeConversationId === "string"
    ? candidate.activeConversationId
    : null;

  return {
    version: 2,
    mode: restoreMode(candidate),
    activeConversationId: requestedActive && panes.includes(requestedActive)
      ? requestedActive
      : panes[panes.length - 1] ?? null,
    panes,
  };
}

export function serializeChatDeskState(state: ChatDeskState): string {
  return JSON.stringify({ ...state, version: 2 });
}
