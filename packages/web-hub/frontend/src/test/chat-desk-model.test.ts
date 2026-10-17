import { describe, expect, it } from "vitest";

import {
  CHAT_DESK_MAX_PANES,
  canOpenDeskConversation,
  closeDeskConversation,
  createChatDeskState,
  focusDeskConversation,
  openDeskConversation,
  restoreChatDeskState,
  serializeChatDeskState,
  setChatDeskMode,
} from "@/features/chats/chat-desk-model";

describe("chat desk model", () => {
  it.each([
    ["single", "single"],
    ["split", "grid"],
    ["grid", "grid"],
    ["floating", "grid"],
  ] as const)("migrates a v1 %s desk to the compact v2 %s layout", (legacyMode, mode) => {
    const restored = restoreChatDeskState(
      JSON.stringify({
        version: 1,
        mode: legacyMode,
        activeConversationId: "chat-b",
        panes: [
          { conversationId: "chat-a", rect: { x: 4, y: 4, width: 62, height: 72 }, snap: "none", z: 1 },
          { conversationId: "chat-b", rect: { x: 18, y: 12, width: 58, height: 64 }, snap: "full", z: 2 },
        ],
      }),
      ["chat-a", "chat-b"],
    );

    expect(restored).toEqual({
      version: 2,
      mode,
      activeConversationId: "chat-b",
      panes: ["chat-a", "chat-b"],
    });
    expect(JSON.parse(serializeChatDeskState(restored))).toEqual(restored);
  });

  it("keeps ten unique conversations open without moving panes when focus changes", () => {
    let state = createChatDeskState("chat-a");
    for (const conversationId of [
      "chat-b",
      "chat-c",
      "chat-d",
      "chat-e",
      "chat-f",
      "chat-g",
      "chat-h",
      "chat-i",
      "chat-j",
      "chat-k",
    ]) {
      state = openDeskConversation(state, conversationId);
    }

    expect(state.panes).toEqual([
      "chat-a",
      "chat-b",
      "chat-c",
      "chat-d",
      "chat-e",
      "chat-f",
      "chat-g",
      "chat-h",
      "chat-i",
      "chat-j",
    ]);
    expect(state.panes).toHaveLength(CHAT_DESK_MAX_PANES);
    expect(state.activeConversationId).toBe("chat-j");
    expect(canOpenDeskConversation(state, "chat-k")).toBe(false);
    expect(canOpenDeskConversation(state, "chat-b")).toBe(true);

    const paneOrder = state.panes;
    state = focusDeskConversation(state, "chat-b");
    expect(state.panes).toEqual(paneOrder);
    expect(state.activeConversationId).toBe("chat-b");

    state = closeDeskConversation(state, "chat-b");
    expect(state.panes).not.toContain("chat-b");
    expect(state.activeConversationId).toBe("chat-j");
  });

  it("switches only between focus and automatic grid modes", () => {
    const state = createChatDeskState("chat-a");
    const grid = setChatDeskMode(state, "grid");

    expect(grid.mode).toBe("grid");
    expect(setChatDeskMode(grid, "single").mode).toBe("single");
  });

  it("repairs persisted desks without reopening stale conversations", () => {
    const restored = restoreChatDeskState(
      JSON.stringify({
        version: 1,
        mode: "floating",
        activeConversationId: "missing",
        panes: [
          { conversationId: "missing", rect: {}, snap: "none", z: 1 },
          { conversationId: "chat-b", rect: {}, snap: "none", z: 2 },
          { conversationId: "chat-b", rect: {}, snap: "none", z: 3 },
        ],
      }),
      ["chat-a", "chat-b"],
    );

    expect(restored).toEqual({
      version: 2,
      mode: "grid",
      activeConversationId: "chat-b",
      panes: ["chat-b"],
    });
  });

  it.each([
    JSON.stringify({ version: 1, mode: "grid", activeConversationId: null, panes: [] }),
    serializeChatDeskState(createChatDeskState()),
  ])("restores an explicitly empty persisted desk without opening another chat", (serialized) => {
    const restored = restoreChatDeskState(serialized, ["chat-a", "chat-b"]);

    expect(restored.activeConversationId).toBeNull();
    expect(restored.panes).toEqual([]);
  });
});
