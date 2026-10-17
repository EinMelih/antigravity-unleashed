import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SystemConnection } from "@/components/shell/system-connection";

function renderConnection(instances: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.endsWith("/health")
      ? { status: "ok", antigravity_backend: { connected: true, port: 8001 } }
      : instances;
    return Promise.resolve(new Response(JSON.stringify(payload), {
      headers: { "content-type": "application/json" },
      status: 200,
    }));
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><SystemConnection /></QueryClientProvider>);
}

describe("SystemConnection", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows live AG instances and their current conversations", async () => {
    renderConnection({
      connection: "online",
      observed_at: "2026-08-30T12:00:00Z",
      revision: "abc",
      stale: false,
      capacity: { open_workers: 2, busy_workers: 2, idle_workers: 0, maximum_workers: 4, queued: 0 },
      instances: [
        { instance_ref: "one", instance_id: "AG-01", role: "worker", availability: "online", activity: "working", detail_code: "worker_working", conversation: { conversation_id: "chat-a", title: "API bauen" }, binding_status: "confirmed", focused: true, has_draft: false, can_close: false, can_focus: false, can_snap: false },
        { instance_ref: "two", instance_id: "AG-02", role: "worker", availability: "online", activity: "waiting_human", detail_code: "worker_waiting_human", conversation: { conversation_id: "chat-b", title: "Review prüfen" }, binding_status: "confirmed", focused: false, has_draft: false, can_close: false, can_focus: false, can_snap: false },
      ],
    });

    const trigger = await screen.findByRole("button", { name: /2 Instanzen · Freigabe nötig/i });
    await userEvent.click(trigger);
    expect(await screen.findByText("AG-01")).toBeVisible();
    expect(screen.getByText("Arbeitet")).toBeVisible();
    expect(screen.getByText("API bauen")).toBeVisible();
    expect(screen.getByText("Freigabe nötig")).toBeVisible();
  });

  it("does not report a green system when the native fleet is offline", async () => {
    renderConnection({
      connection: "offline",
      observed_at: "2026-08-30T12:00:00Z",
      revision: "offline",
      stale: true,
      capacity: { open_workers: 0, busy_workers: 0, idle_workers: 0, maximum_workers: 4, queued: 0 },
      instances: [],
    });

    expect(await screen.findByText("Anti-Gravity offline")).toBeVisible();
    expect(screen.queryByText("System verbunden")).not.toBeInTheDocument();
  });

  it("does not report an unknown instance as ready or healthy", async () => {
    renderConnection({
      connection: "online",
      observed_at: "2026-08-30T12:00:00Z",
      revision: "unknown",
      stale: false,
      capacity: { open_workers: 0, busy_workers: 0, idle_workers: 0, maximum_workers: 4, queued: 0 },
      instances: [
        { instance_ref: "main", instance_id: "MAIN", role: "primary", availability: "online", activity: "unknown", detail_code: "native_status_unknown", conversation: null, binding_status: "none", focused: true, has_draft: false, can_close: false, can_focus: true, can_snap: false },
      ],
    });

    const trigger = await screen.findByRole("button", { name: "1 Instanz · Status unklar" });
    expect(trigger).toBeVisible();
    expect(trigger.querySelector(".text-success")).not.toBeInTheDocument();
    expect(trigger.querySelector(".text-warning")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /bereit/i })).not.toBeInTheDocument();
  });
});
