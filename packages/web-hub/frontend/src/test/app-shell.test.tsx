import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";

describe("AppShell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.location.hash = "";
  });

  it("shows the reduced primary navigation and the Studio", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        let payload: unknown = {};
        if (url.endsWith("/health")) {
          payload = {
            status: "ok",
            hub: "healthy",
            antigravity_backend: { connected: true, port: 8001 },
            web_ide: {},
            control_plane: { mode: "guided" },
          };
        } else if (url.includes("control-center/overview")) {
          payload = {
            policy: { mode: "guided", paused: false },
            summary: { tasks_active: 0 },
            attention: [],
            tasks: [],
          };
        } else if (url.includes("antigravity/conversations")) {
          payload = { conversations: [], counts: { running: 0, complete: 0, archived: 0 }, active_agents: [], filters: {} };
        } else if (url.includes("antigravity/instances")) {
          payload = {
            connection: "online",
            observed_at: "2026-08-30T12:00:00Z",
            revision: "main",
            stale: false,
            capacity: { open_workers: 0, busy_workers: 0, idle_workers: 0, maximum_workers: 4, queued: 0 },
            instances: [{
              instance_ref: "main",
              instance_id: "MAIN",
              role: "primary",
              availability: "online",
              activity: "manual",
              detail_code: "primary_manual",
              conversation: null,
              binding_status: "none",
              focused: true,
              has_draft: false,
              can_close: false,
              can_focus: false,
              can_snap: false,
            }],
          };
        } else if (url.includes("antigravity/workers")) {
          payload = { success: true, primary: null, workers: [], capacity: { active: 0, maximum: 4, minimum_warm: 0, queued: 0, idle_ttl_seconds: 60 } };
        } else if (url.includes("/api/projects")) {
          payload = { projects: [] };
        }
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            headers: { "content-type": "application/json" },
            status: 200,
          }),
        );
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    window.location.hash = "#/studio";

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "Studio" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Als Nächstes" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Studio" }).length).toBeGreaterThan(0);
    expect(await screen.findByText("1 Instanz · bereit")).toBeVisible();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Befehlspalette" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Hub durchsuchen" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Befehlspalette" })).not.toBeInTheDocument();
  });

  it("focuses navigation exclusively on API-Logs in headless_linux mode", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = String(input);
        let payload: unknown = {};
        if (url.endsWith("/health")) {
          payload = {
            status: "ok",
            hub: "healthy",
            runtime_mode: "headless_linux",
            antigravity_backend: { connected: true, port: 8001 },
            web_ide: {},
            control_plane: { mode: "guided" },
          };
        } else if (url.includes("/api/logs/stats")) {
          payload = { totals: {}, by_model: [], total_revert_events: 0 };
        } else if (url.includes("/api/logs/reverts")) {
          payload = { count: 0, reverts: [] };
        } else if (url.includes("/api/logs")) {
          payload = { count: 0, logs: [] };
        } else if (url.includes("/api/engine-mode")) {
          payload = { runtime_mode: "headless_linux", api_engine: { mode: "rpc" }, pool: {} };
        }
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            headers: { "content-type": "application/json" },
            status: 200,
          }),
        );
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    window.location.hash = "#/api-logs";

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Headless Linux · Direct RPC")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "API-Logs" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Chats" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Einstellungen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Studio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mehr" })).not.toBeInTheDocument();
  });
});
