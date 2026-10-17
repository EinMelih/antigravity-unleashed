import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CHAT_DESK_LEGACY_STORAGE_KEY,
  CHAT_DESK_STORAGE_KEY,
} from "@/features/chats/chat-desk-model";
import { useChatDesk } from "@/features/chats/use-chat-desk";

describe("useChatDesk persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("migrates the legacy storage key and exposes only desk actions", () => {
    window.localStorage.setItem(CHAT_DESK_LEGACY_STORAGE_KEY, JSON.stringify({
      version: 1,
      mode: "floating",
      activeConversationId: "chat-b",
      panes: [
        { conversationId: "chat-a", rect: {}, restoreRect: {}, snap: "none", z: 1 },
        { conversationId: "chat-b", rect: {}, restoreRect: {}, snap: "full", z: 2 },
      ],
    }));

    const { result } = renderHook(() => useChatDesk(["chat-a", "chat-b"]));

    expect(result.current.state).toEqual({
      version: 2,
      mode: "grid",
      activeConversationId: "chat-b",
      panes: ["chat-a", "chat-b"],
    });
    expect(result.current).not.toHaveProperty("setRect");
    expect(result.current).not.toHaveProperty("snap");

    act(() => vi.advanceTimersByTime(300));
    expect(JSON.parse(window.localStorage.getItem(CHAT_DESK_STORAGE_KEY) ?? "null"))
      .toEqual(result.current.state);
  });

  it("persists only the latest desk state after actions settle", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(() => useChatDesk(["chat-a", "chat-b"]));
    act(() => vi.runOnlyPendingTimers());
    setItem.mockClear();

    act(() => result.current.open("chat-b"));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current.setMode("grid"));
    act(() => vi.advanceTimersByTime(200));

    expect(setItem).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(50));

    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith(CHAT_DESK_STORAGE_KEY, expect.any(String));
    expect(JSON.parse(setItem.mock.calls[0]?.[1] as string)).toEqual({
      version: 2,
      mode: "grid",
      activeConversationId: "chat-b",
      panes: ["chat-a", "chat-b"],
    });
  });

  it("flushes the latest desk state on pagehide and cancels the delayed write", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(() => useChatDesk(["chat-a"]));
    act(() => vi.runOnlyPendingTimers());
    setItem.mockClear();

    act(() => result.current.setMode("grid"));
    expect(setItem).not.toHaveBeenCalled();

    act(() => window.dispatchEvent(new Event("pagehide")));

    expect(setItem).toHaveBeenCalledTimes(1);
    expect(JSON.parse(setItem.mock.calls[0]?.[1] as string).mode).toBe("grid");

    act(() => vi.runOnlyPendingTimers());
    expect(setItem).toHaveBeenCalledTimes(1);
  });

  it("flushes a pending desk action when the workspace unmounts", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result, unmount } = renderHook(() => useChatDesk(["chat-a", "chat-b"]));
    act(() => vi.runOnlyPendingTimers());
    setItem.mockClear();

    act(() => result.current.open("chat-b"));
    unmount();

    expect(setItem).toHaveBeenCalledTimes(1);
    expect(JSON.parse(setItem.mock.calls[0]?.[1] as string).panes)
      .toEqual(["chat-a", "chat-b"]);
    act(() => vi.runOnlyPendingTimers());
    expect(setItem).toHaveBeenCalledTimes(1);
  });

  it("keeps an explicitly closed desk empty after reload", () => {
    const firstMount = renderHook(() => useChatDesk(["chat-a", "chat-b"]));
    act(() => vi.runOnlyPendingTimers());
    expect(firstMount.result.current.state.activeConversationId).toBe("chat-a");

    act(() => firstMount.result.current.close("chat-a"));
    act(() => window.dispatchEvent(new Event("pagehide")));
    expect(JSON.parse(window.localStorage.getItem(CHAT_DESK_STORAGE_KEY) ?? "null"))
      .toMatchObject({ activeConversationId: null, panes: [] });
    firstMount.unmount();

    const secondMount = renderHook(() => useChatDesk(["chat-a", "chat-b"]));

    expect(secondMount.result.current.state.activeConversationId).toBeNull();
    expect(secondMount.result.current.state.panes).toEqual([]);
  });

  it("clears stale panes without opening an unrelated chat when the catalog changes", () => {
    const { result, rerender } = renderHook(
      ({ conversationIds }: { conversationIds: string[] }) => useChatDesk(conversationIds),
      { initialProps: { conversationIds: ["chat-old"] } },
    );
    act(() => vi.runOnlyPendingTimers());

    act(() => rerender({ conversationIds: [] }));

    expect(result.current.state.activeConversationId).toBeNull();
    expect(result.current.state.panes).toEqual([]);
    act(() => vi.advanceTimersByTime(300));
    expect(JSON.parse(window.localStorage.getItem(CHAT_DESK_STORAGE_KEY) ?? "null")).toMatchObject({
      activeConversationId: null,
      panes: [],
    });

    act(() => rerender({ conversationIds: ["chat-new", "chat-later"] }));

    expect(result.current.state.activeConversationId).toBeNull();
    expect(result.current.state.panes).toEqual([]);
  });

  it("waits for the initial catalog before restoring persisted panes", () => {
    window.localStorage.setItem(CHAT_DESK_STORAGE_KEY, JSON.stringify({
      version: 2,
      mode: "grid",
      activeConversationId: "chat-b",
      panes: ["chat-a", "chat-b"],
    }));
    const { result, rerender } = renderHook(
      ({ conversationIds, catalogReady }: { conversationIds: string[]; catalogReady: boolean }) => (
        useChatDesk(conversationIds, catalogReady)
      ),
      { initialProps: { conversationIds: [] as string[], catalogReady: false } },
    );

    expect(result.current.state.panes).toEqual([]);
    act(() => vi.runOnlyPendingTimers());

    act(() => rerender({ conversationIds: ["chat-a", "chat-b"], catalogReady: true }));

    expect(result.current.state.mode).toBe("grid");
    expect(result.current.state.activeConversationId).toBe("chat-b");
    expect(result.current.state.panes).toEqual(["chat-a", "chat-b"]);
  });
});
