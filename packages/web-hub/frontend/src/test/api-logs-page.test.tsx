import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiLogsPage } from "@/pages/api-logs-page";

describe("ApiLogsPage (#/api-logs)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders persistent API logs, exact token & context metrics, Dual-Engine switch, and triggers conversation revert", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/logs/stats")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              totals: {
                total_requests: 1,
                success_requests: 1,
                error_requests: 0,
                reverted_requests: 0,
                prompt_tokens: 420,
                completion_tokens: 180,
                cached_tokens: 1200,
                thinking_tokens: 95,
                total_tokens: 695,
                avg_duration_ms: 810,
              },
              by_model: [{ model: "claude-opus-4-6", requests: 1, total_tokens: 695, avg_duration_ms: 810 }],
              total_revert_events: 0,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/logs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              count: 1,
              logs: [
                {
                  req_id: "req001",
                  created_at: "2026-10-18T06:30:00Z",
                  client_ip: "127.0.0.1",
                  user_agent: "Hermes/2.0",
                  api_key_name: "hermes-key",
                  source_framework: "hermes",
                  endpoint: "/v1/chat/completions",
                  engine_mode: "rpc",
                  workspace_slot: "ws-00",
                  conversation_id: "cascade-abc-123",
                  model_requested: "claude-opus-4-6",
                  model_actual: "claude-opus-4-6",
                  reasoning_effort: "high",
                  stream: 0,
                  status_code: 200,
                  duration_ms: 810,
                  prompt_tokens: 420,
                  completion_tokens: 180,
                  cached_tokens: 1200,
                  thinking_tokens: 95,
                  total_tokens: 695,
                  context_used_tokens: 1895,
                  context_max_tokens: 200000,
                  token_source: "exact_rpc",
                  messages_json: '[{"role":"user","content":"Analyze architecture"}]',
                  system_prompt: "Output concise technical results.",
                  user_prompt_preview: "Analyze architecture",
                  response_text: "Architecture analysis complete.",
                  tool_calls_json: "[]",
                  shield_metadata_json: '{"stagger_ms":420}',
                  error_text: "",
                  reverted_at: null,
                  reverted_to_step: null,
                },
              ],
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/engine-mode") && (!init || init.method !== "POST")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              api_engine: {
                mode: "rpc",
                max_parallel_streams: 4,
                slot_count: 10,
                stagger_min_ms: 400,
                stagger_max_ms: 1200,
                adaptive_pacing_enabled: true,
                heartbeat_blocker_enabled: true,
                keyword_firewall_enabled: true,
                quota_breaker_enabled: true,
                quota_min_fraction: 0.05,
                max_turns_per_session: 20,
              },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/api/engine-mode") && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: "updated",
              api_engine: {
                mode: body.mode || "ui",
                max_parallel_streams: body.max_parallel_streams || 4,
                slot_count: 10,
                stagger_min_ms: 400,
                stagger_max_ms: 1200,
                adaptive_pacing_enabled: true,
                heartbeat_blocker_enabled: true,
                keyword_firewall_enabled: true,
                quota_breaker_enabled: true,
                quota_min_fraction: 0.05,
                max_turns_per_session: 20,
              },
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      if (url.startsWith("/v1/chat/revert")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: "reverted",
              conversation_id: "cascade-abc-123",
              reverted_to_step: 2,
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ApiLogsPage />);

    expect(await screen.findByText("Analyze architecture")).toBeVisible();
    expect(screen.getAllByText("claude-opus-4-6").length).toBeGreaterThan(0);
    expect(screen.getByText(/exact_rpc/)).toBeVisible();

    // Verify Hermes & OpenClaw showcase + Undetected Standard badge + Revert explanation + Embedded /docs
    expect(screen.getByText("100 % Undetected-Standard aktiv")).toBeVisible();
    expect(screen.getByText("Hermes Agent Ready")).toBeVisible();
    expect(screen.getByText("OpenClaw Anti-Ban Shield")).toBeVisible();
    expect(
      screen.getByText(/Was macht „Revert“ genau – und wie schützen uns die 8 Anti-Ban-Schilde\?/),
    ).toBeVisible();
    expect(
      screen.getByTitle("Antigravity Web API Dokumentation"),
    ).toBeVisible();

    // Open Custom Settings panel
    fireEvent.click(
      screen.getByRole("button", { name: /Custom-Settings anpassen/i }),
    );
    expect(
      screen.getByText("Custom-Feinsteuerung der Schutzschilde & Grenzwerte"),
    ).toBeVisible();

    // Switch language from DE to EN and back to DE
    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(
      screen.getByText("API Logs & Interactive API Documentation"),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "DE" }));
    expect(
      screen.getByText("API-Logs & Interaktive API-Dokumentation"),
    ).toBeVisible();

    // Switch mode from RPC Direct to UI / CDP Backup
    fireEvent.click(screen.getByRole("button", { name: "UI / CDP Backup" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/engine-mode",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    // Click Revert button on the logged conversation
    fireEvent.click(screen.getByRole("button", { name: /^Revert$/i }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/chat/revert",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
