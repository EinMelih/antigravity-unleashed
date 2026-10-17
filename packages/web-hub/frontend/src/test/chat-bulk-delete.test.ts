import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import {
  cleanupWarningSuffix,
  deleteConversationsSequentially,
  includeMissingSelectedConversations,
  updateConversationSelection,
} from "@/features/chats/bulk-delete";

describe("bulk chat deletion", () => {
  it("keeps cleanup warnings available for mixed bulk results", () => {
    expect(cleanupWarningSuffix(0)).toBe("");
    expect(cleanupWarningSuffix(1)).toBe(
      " Bei 1 Chat konnten lokale Restdateien noch nicht bereinigt werden.",
    );
    expect(cleanupWarningSuffix(2)).toBe(
      " Bei 2 Chats konnten lokale Restdateien noch nicht bereinigt werden.",
    );
  });

  it("can deselect a failed snapshot that is no longer in the live catalog", () => {
    const selected = new Set(["missing-after-partial-delete", "still-live"]);

    expect([
      ...updateConversationSelection(selected, "missing-after-partial-delete", false),
    ]).toEqual(["still-live"]);
    expect([...selected]).toEqual(["missing-after-partial-delete", "still-live"]);
  });

  it("keeps a failed selected conversation visible after it leaves the catalog", () => {
    const current = [{ convo_id: "chat-a", title: "A" }];
    const failedSnapshot = { convo_id: "chat-b", title: "B" };

    expect(includeMissingSelectedConversations(
      current,
      new Set(["chat-b"]),
      new Map([["chat-b", failedSnapshot], ["not-selected", { convo_id: "not-selected", title: "C" }]]),
    )).toEqual([current[0], failedSnapshot]);
  });

  it("deletes unique chats sequentially and reports progress", async () => {
    const inFlight: string[] = [];
    const order: string[] = [];
    const remove = vi.fn(async (conversationId: string) => {
      expect(inFlight).toEqual([]);
      inFlight.push(conversationId);
      order.push(`start:${conversationId}`);
      await Promise.resolve();
      order.push(`end:${conversationId}`);
      inFlight.pop();
    });
    const progress = vi.fn();

    const result = await deleteConversationsSequentially(
      ["chat-a", "chat-b", "chat-a"],
      remove,
      progress,
    );

    expect(order).toEqual(["start:chat-a", "end:chat-a", "start:chat-b", "end:chat-b"]);
    expect(result).toEqual({
      alreadyAbsentIds: [],
      cleanupWarnings: [],
      deletedIds: ["chat-a", "chat-b"],
      failures: [],
    });
    expect(progress).toHaveBeenLastCalledWith({ completed: 2, total: 2 });
  });

  it("treats missing chats as deleted and retains other failures", async () => {
    const remove = vi.fn(async (conversationId: string) => {
      if (conversationId === "missing") throw new ApiError("Nicht gefunden", { status: 404 });
      if (conversationId === "locked") throw new ApiError("Datei ist gesperrt", { status: 503 });
    });

    const result = await deleteConversationsSequentially(
      ["deleted", "missing", "locked"],
      remove,
    );

    expect(result.deletedIds).toEqual(["deleted", "missing"]);
    expect(result.alreadyAbsentIds).toEqual(["missing"]);
    expect(result.cleanupWarnings).toEqual([]);
    expect(result.failures).toEqual([
      { conversationId: "locked", message: "Datei ist gesperrt" },
    ]);
  });

  it("turns the busy contract into a user-facing failure", async () => {
    const result = await deleteConversationsSequentially(["working"], async () => {
      throw new ApiError("Conversation is active", {
        code: "conversation_busy",
        status: 409,
      });
    });

    expect(result.failures).toEqual([{
      conversationId: "working",
      message: "Der Chat arbeitet gerade und bleibt geschützt.",
    }]);
  });

  it("explains an unavailable native state without exposing backend details", async () => {
    const result = await deleteConversationsSequentially(["uncertain"], async () => {
      throw new ApiError("Internal runtime detail", {
        code: "conversation_state_unavailable",
        status: 503,
      });
    });

    expect(result.failures).toEqual([{
      conversationId: "uncertain",
      message: "Der Anti-Gravity-Zustand konnte nicht sicher geprüft werden. Der Chat bleibt geschützt.",
    }]);
  });

  it("keeps a chat protected when native deletion is unconfirmed", async () => {
    const result = await deleteConversationsSequentially(["stale"], async () => {
      throw new ApiError("Internal gRPC detail", {
        code: "native_delete_unconfirmed",
        status: 503,
      });
    });

    expect(result.failures).toEqual([{
      conversationId: "stale",
      message: "Anti-Gravity hat die Löschung nicht bestätigt. Der Chat bleibt erhalten.",
    }]);
  });

  it("distinguishes native removal from incomplete local cleanup", async () => {
    const result = await deleteConversationsSequentially(["partial"], async () => {
      throw new ApiError("Internal path detail", {
        code: "local_cleanup_incomplete",
        status: 503,
      });
    });

    expect(result.deletedIds).toEqual(["partial"]);
    expect(result.failures).toEqual([]);
    expect(result.cleanupWarnings).toEqual([{
      conversationId: "partial",
      message: "Der Chat wurde in Anti-Gravity entfernt, aber lokale Restdateien konnten noch nicht bereinigt werden.",
    }]);
  });
});
