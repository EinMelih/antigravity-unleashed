import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProjectRuntimeSnapshot } from "@/api/contracts";
import { ProjectRuntimeCockpit } from "@/features/projects/project-runtime-cockpit";

function snapshot(active = false): ProjectRuntimeSnapshot {
  const frontendConfig = {
    name: "Vite Frontend",
    enabled: true,
    command: "npm run dev",
    cwd: "frontend",
    host: "127.0.0.1",
    port: 5173,
    health_path: "/",
    detected: true,
    reason: "Vite package.json erkannt",
  };
  return {
    project_id: 12,
    configured: true,
    storage_path: "C:\\Users\\Example\\.gemini\\config\\antigravity-hub\\project-runtimes.json",
    profile: {
      project_id: 12,
      version: 1,
      services: {
        frontend: frontendConfig,
        backend: { ...frontendConfig, name: "Backend", enabled: false, cwd: ".", port: 8012 },
      },
    },
    services: {
      frontend: {
        service: "frontend",
        status: active ? "running" as const : "stopped" as const,
        active,
        managed: active,
        pid: active ? 9012 : null,
        started_at: active ? 1_785_000_000 : null,
        url: "http://127.0.0.1:5173/",
        config: frontendConfig,
        log: "ready",
      },
      backend: {
        service: "backend",
        status: "stopped" as const,
        active: false,
        managed: false,
        pid: null,
        started_at: null,
        url: "http://127.0.0.1:8012/",
        config: { ...frontendConfig, name: "Backend", enabled: false, cwd: ".", port: 8012 },
        log: "",
      },
    },
  };
}

describe("ProjectRuntimeCockpit", () => {
  it("exposes a visible frontend start action", () => {
    const onStart = vi.fn().mockResolvedValue(undefined);
    render(<ProjectRuntimeCockpit busyService="" onCapture={vi.fn()} onSetup={vi.fn()} onStart={onStart} onStop={vi.fn()} runtime={snapshot()} />);
    fireEvent.click(screen.getByRole("button", { name: "Vite Frontend starten" }));
    expect(onStart).toHaveBeenCalledWith("frontend");
    expect(screen.getByText("Frontend noch nicht gestartet")).toBeVisible();
  });

  it("renders the live preview and captured screenshot", async () => {
    const onCapture = vi.fn().mockResolvedValue({
      success: true,
      captured_at: 1_785_000_000,
      path: "preview.png",
      url: "/api/projects/12/runtime/screenshot/image",
    });
    render(<ProjectRuntimeCockpit busyService="" onCapture={onCapture} onSetup={vi.fn()} onStart={vi.fn()} onStop={vi.fn()} runtime={snapshot(true)} />);
    expect(screen.getByTitle("Vite Frontend Vorschau")).toHaveAttribute("src", "http://127.0.0.1:5173/");
    fireEvent.click(screen.getByRole("button", { name: "Screenshot" }));
    await waitFor(() => expect(screen.getByAltText("Automatisch erfasste Projektvorschau")).toBeVisible());
    expect(onCapture).toHaveBeenCalledOnce();
  });

  it("offers explicit dependency setup before starting", () => {
    const runtime = snapshot();
    runtime.services.frontend.setup = { required: true, command: "npm ci", reason: "Dependencies are not installed in web." };
    const onSetup = vi.fn().mockResolvedValue(undefined);
    render(<ProjectRuntimeCockpit busyService="" onCapture={vi.fn()} onSetup={onSetup} onStart={vi.fn()} onStop={vi.fn()} runtime={runtime} />);
    expect(screen.queryByRole("button", { name: "Vite Frontend starten" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Abhängigkeiten einrichten" }));
    expect(onSetup).toHaveBeenCalledWith("frontend");
    expect(screen.getByText("npm ci")).toBeVisible();
  });
});
