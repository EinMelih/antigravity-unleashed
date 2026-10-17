import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CHAT_DESK_LEGACY_STORAGE_KEY,
  CHAT_DESK_STORAGE_KEY,
  closeDeskConversation,
  createChatDeskState,
  focusDeskConversation,
  openDeskConversation,
  restoreChatDeskState,
  serializeChatDeskState,
  setChatDeskMode,
  type ChatDeskMode,
} from "@/features/chats/chat-desk-model";

const CHAT_DESK_PERSIST_DELAY_MS = 250;

export function useChatDesk(
  validConversationIds: readonly string[],
  catalogReady = true,
) {
  const [state, setState] = useState(() => createChatDeskState());
  const hydrated = useRef(false);
  const latestSerializedRef = useRef<string | null>(null);
  const persistedSerializedRef = useRef<string | null>(null);
  const persistTimerRef = useRef<number | null>(null);
  const fingerprint = useMemo(
    () => validConversationIds.join("\u001f"),
    [validConversationIds],
  );
  const stableConversationIds = useMemo(
    () => fingerprint ? fingerprint.split("\u001f") : [],
    [fingerprint],
  );

  useEffect(() => {
    if (!catalogReady) return;
    setState((current) => {
      let serialized: string | null = serializeChatDeskState(current);
      if (!hydrated.current) {
        try {
          const stored = window.localStorage.getItem(CHAT_DESK_STORAGE_KEY);
          serialized = stored ?? window.localStorage.getItem(CHAT_DESK_LEGACY_STORAGE_KEY);
          persistedSerializedRef.current = stored;
        } catch {
          serialized = null;
          // Private browsing or locked-down storage must not break the workspace.
        }
      }
      hydrated.current = true;
      return restoreChatDeskState(serialized, stableConversationIds);
    });
  }, [catalogReady, stableConversationIds]);

  const persistLatest = useCallback(() => {
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
    }
    const serialized = latestSerializedRef.current;
    if (!serialized || serialized === persistedSerializedRef.current) return;
    try {
      window.localStorage.setItem(CHAT_DESK_STORAGE_KEY, serialized);
      persistedSerializedRef.current = serialized;
    } catch {
      // Layout persistence is optional; runtime behavior remains available.
    }
  }, []);

  useEffect(() => {
    const handlePageHide = () => persistLatest();
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      persistLatest();
    };
  }, [persistLatest]);

  useEffect(() => {
    if (!hydrated.current) return;
    latestSerializedRef.current = serializeChatDeskState(state);
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
    }
    persistTimerRef.current = window.setTimeout(persistLatest, CHAT_DESK_PERSIST_DELAY_MS);
  }, [persistLatest, state]);

  const open = useCallback((conversationId: string) => {
    setState((current) => openDeskConversation(current, conversationId));
  }, []);
  const close = useCallback((conversationId: string) => {
    setState((current) => closeDeskConversation(current, conversationId));
  }, []);
  const focus = useCallback((conversationId: string) => {
    setState((current) => focusDeskConversation(current, conversationId));
  }, []);
  const setMode = useCallback((mode: ChatDeskMode) => {
    setState((current) => setChatDeskMode(current, mode));
  }, []);

  return { close, focus, open, setMode, state };
}
