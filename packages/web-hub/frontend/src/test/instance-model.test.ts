import { describe, expect, it } from "vitest";

import type { AntigravityInstance } from "@/api/contracts";
import { instanceIndicator, instancesByConversation } from "@/features/chats/instance-model";

function instance(
  instanceId: string,
  overrides: Partial<AntigravityInstance> = {},
): AntigravityInstance {
  return {
    activity: "idle",
    availability: "online",
    binding_status: "confirmed",
    can_close: true,
    can_focus: false,
    can_snap: false,
    conversation: { conversation_id: "chat-a", title: "Chat A" },
    detail_code: "worker_idle",
    focused: false,
    has_draft: false,
    instance_id: instanceId,
    instance_ref: `${instanceId}-target`,
    role: "worker",
    updated_at: 1,
    ...overrides,
  };
}

describe("instancesByConversation", () => {
  it("uses attention and blocked tones for states that are not positively ready", () => {
    expect(instanceIndicator(instance("AG-01", { activity: "idle" }))).toEqual({
      label: "AG-01 · Bereit",
      tone: "healthy",
    });
    expect(instanceIndicator(instance("AG-01", { activity: "unknown" }))).toEqual({
      label: "AG-01 · Unbekannt",
      tone: "attention",
    });
    expect(instanceIndicator(instance("AG-01", { activity: "waiting_human" }))).toEqual({
      label: "AG-01 · Freigabe nötig",
      tone: "attention",
    });
    expect(instanceIndicator(instance("AG-01", { activity: "error" }))).toEqual({
      label: "AG-01 · Fehler",
      tone: "blocked",
    });
    expect(instanceIndicator(instance("AG-01", { availability: "unreachable" }))).toEqual({
      label: "AG-01 · Nicht erreichbar",
      tone: "blocked",
    });
  });

  it("selects the reachable dedicated instance needing attention independent of API order", () => {
    const candidates = [
      instance("MAIN", {
        activity: "manual",
        binding_status: "none",
        focused: true,
        role: "primary",
        updated_at: 50,
      }),
      instance("AG-01", {
        activity: "waiting_human",
        availability: "unreachable",
        updated_at: 100,
      }),
      instance("AG-02", { activity: "idle", updated_at: 30 }),
      instance("AG-03", {
        activity: "waiting_human",
        binding_status: "mismatch",
        updated_at: 20,
      }),
    ];

    expect(instancesByConversation(candidates).get("chat-a")?.instance_id).toBe("AG-03");
    expect(instancesByConversation([...candidates].reverse()).get("chat-a")?.instance_id).toBe("AG-03");
  });

  it("uses binding, focus, recency and stable identifiers to break equivalent worker ties", () => {
    const confirmed = instance("AG-03", { binding_status: "confirmed", updated_at: 5 });
    const mismatch = instance("AG-01", {
      binding_status: "mismatch",
      focused: true,
      updated_at: 100,
    });
    const recent = instance("AG-04", { focused: true, updated_at: 8 });
    const older = instance("AG-05", { focused: true, updated_at: 7 });
    const lexicalWinner = instance("AG-06", {
      focused: true,
      instance_ref: "target-a",
      updated_at: 8,
    });
    const lexicalLoser = instance("AG-06", {
      focused: true,
      instance_ref: "target-b",
      updated_at: 8,
    });

    for (const [candidates, expected] of [
      [[mismatch, confirmed], confirmed],
      [[older, recent], recent],
      [[lexicalLoser, lexicalWinner], lexicalWinner],
    ] as const) {
      expect(instancesByConversation(candidates).get("chat-a")).toBe(expected);
      expect(instancesByConversation([...candidates].reverse()).get("chat-a")).toBe(expected);
    }
  });
});
