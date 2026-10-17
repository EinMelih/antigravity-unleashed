import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SystemOverviewResponse } from "@/api/contracts";
import { SystemStatusPage } from "@/pages/system-status-page";

const mocks = vi.hoisted(() => ({ getSystemOverview: vi.fn() }));

vi.mock("@/features/system/api", () => mocks);

const overview: SystemOverviewResponse = {
  status: "healthy",
  generated_at: "2026-08-24T12:00:00Z",
  services: [
    { id: "hub", name: "Hub UI", role: "React-Oberfläche und API-Gateway", port: 8000, status: "healthy", http_status: 200, latency_ms: 1.2 },
    { id: "api_bridge", name: "API Bridge", role: "Agenten- und Modellzugriff", port: 8001, status: "healthy", http_status: 200, latency_ms: 2.4 },
  ],
  database: {
    engine: "SQLite",
    filename: "dashboard.db",
    size_bytes: 1_500_000,
    table_count: 40,
    journal_mode: "wal",
    schema_version: 1,
    quick_check: "ok",
    foreign_key_violations: 0,
    last_modified: "2026-08-24T11:59:00Z",
    record_counts: [{ table: "control_agent_tasks", label: "Agentenaufgaben", count: 9 }],
    privacy: "Nur Metadaten und freigegebene Zähler – keine Zeileninhalte.",
  },
  deployment: {
    model: "Aktuell nativ · optional als ein Docker-Stack betreibbar",
    containerized: false,
    runtime_verified: false,
    source_manifest_available: true,
    compose_service: "hub",
    network_mode: "host",
    configured: true,
    checks: [{ id: "dockerfile", label: "Multi-Stage Dockerfile", ready: true, detail: "React-Build und Python-Runtime" }],
  },
  runtime: { hub_version: "0.1.0-dev", build_sha: "abc123def456", python_version: "3.12.10", platform: "Windows", architecture: "AMD64", cpu_count: 12, uptime_seconds: 3660, watchdog_retention_days: 30, api_content_logging: false, control_mode: "guided", paused: false },
  integrations: { antigravity: { connected: true, port: 9222, latency_ms: 1.1 }, web_ide: { running: false, port: 3000 } },
};

describe("SystemStatusPage", () => {
  it("shows services, safe database metadata and deployment readiness", async () => {
    mocks.getSystemOverview.mockResolvedValue(overview);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><SystemStatusPage /></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "System & Stack" })).toBeVisible();
    expect(screen.getByText("Betriebsbereit")).toBeVisible();
    expect(screen.getByText("API Bridge")).toBeVisible();
    expect(screen.getByText("Agentenaufgaben")).toBeVisible();
    expect(screen.getByText("Multi-Stage Dockerfile")).toBeVisible();
    expect(screen.getByText(/keine Zeileninhalte/)).toBeVisible();
    expect(screen.getByText(/echter Containerlauf.*noch nicht verifiziert/)).toBeVisible();
  });
});
