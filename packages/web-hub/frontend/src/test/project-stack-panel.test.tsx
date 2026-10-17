import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ProjectStackResponse } from "@/api/contracts";
import { getProjectStack } from "@/features/projects/api";
import { ProjectStackPanel } from "@/features/projects/project-stack-panel";

function stackResponse(): ProjectStackResponse {
  return {
    project: { id: 12, name: "Storefront" },
    technologies: [{ id: "react", name: "React", category: "Frontend", evidence: ["frontend/package.json"] }],
    database_drivers: [{ id: "sqlite", name: "SQLite", category: "Datenbank", evidence: ["src/store.py"] }],
    manifests: [{ path: "frontend/package.json", kind: "package_json", ecosystem: "Node.js", status: "parsed", dependency_count: 14, dev_dependency_count: 9 }],
    docker: {
      dockerfiles: [{ path: "Dockerfile", status: "parsed", stages: [{ name: "runtime", base_image: "node:22-alpine" }], base_images: ["node:22-alpine"], exposed_ports: ["3000"], healthcheck: "configured" }],
      compose_files: [{
        path: "compose.yml",
        status: "parsed",
        services: [{ name: "web", image: "storefront:local", build: { context: ".", external: false }, ports: ["3000:3000"], volumes: [{ source: "web-data", target: "data", type: "volume", external: false }], depends_on: ["database"], healthcheck: true }],
        named_volumes: ["web-data"],
        networks: ["internal"],
      }],
    },
    databases: [{ path: "data/app.sqlite", size_bytes: 2_048, status: "ok", quick_check: "ok", table_count: 2, tables: [{ name: "projects", row_count: 8, count_status: "ok" }, { name: "audit_log", row_count: null, count_status: "limited" }], tables_truncated: false }],
    scan: { read_only: true, truncated: false, files_considered: 24 },
    privacy: { notice: "Nur sichere Strukturmetadaten werden ausgegeben.", guarantees: ["Keine Tabellenzeilen"] },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProjectStackPanel", () => {
  it("keeps a compact technology summary visible and reveals safe details on demand", () => {
    render(<ProjectStackPanel data={stackResponse()} loading={false} onRetry={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Technik & Daten" })).toBeVisible();
    expect(screen.getByLabelText("Stack-Zusammenfassung")).toHaveTextContent("2Technologien");
    expect(screen.getByLabelText("Stack-Zusammenfassung")).toHaveTextContent("1Datenbanken");
    expect(screen.queryByText("React")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Details anzeigen" }));

    expect(screen.getByText("React")).toBeVisible();
    expect(screen.getAllByText("frontend/package.json")).toHaveLength(2);
    expect(screen.getByText("Dockerfile")).toBeVisible();
    expect(screen.getByText("web")).toBeVisible();
    expect(screen.getByText("data/app.sqlite")).toBeVisible();
    expect(screen.getByRole("cell", { name: "projects" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "8" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "Nicht ermittelt" })).toBeVisible();
    expect(screen.getByText("Nur lesend geprüft")).toBeVisible();
  });

  it("shows explicit loading, empty and retryable error states", () => {
    const retry = vi.fn();
    const { rerender } = render(<ProjectStackPanel loading onRetry={retry} />);
    expect(screen.getByRole("heading", { name: "Projekt-Stack wird geprüft" })).toBeVisible();

    rerender(<ProjectStackPanel data={{ scan: { read_only: true } }} loading={false} onRetry={retry} />);
    expect(screen.getByRole("heading", { name: "Noch keine Stack-Daten erkannt" })).toBeVisible();

    rerender(<ProjectStackPanel error="Metadaten momentan nicht erreichbar." loading={false} onRetry={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("never renders absolute paths, environment values, secrets, SQL or table rows", () => {
    const unsafe = {
      ...stackResponse(),
      technologies: [{ id: "unsafe", name: "Runtime", category: "Backend", evidence: ["C:\\Users\\Alice\\private.json", ".env", "src/index.ts"] }],
      docker: {
        dockerfiles: [{ path: "/home/alice/project/Dockerfile", status: "parsed", base_images: ["api_key=TEST_VALUE"], exposed_ports: [] }],
        compose_files: [{ path: "compose.yml", status: "parsed", services: [{ name: "api", image: "https://user:password@registry.example/image", ports: [], volumes: [{ source: "C:\\private\\data", target: "/var/lib/data", type: "bind", external: false }], environment: { API_KEY: "should-never-render" } }] }],
      },
      databases: [{ path: "/home/alice/project/private.sqlite", status: "ok", quick_check: "ok", tables: [{ name: "users", row_count: 1, count_status: "ok", rows: [{ email: "private@example.com" }] }], sql: "SELECT * FROM users" }],
      privacy: { notice: "Scanned /home/alice/project", guarantees: [] },
    } as unknown as ProjectStackResponse;

    render(<ProjectStackPanel data={unsafe} loading={false} onRetry={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Details anzeigen" }));

    expect(screen.getAllByText("Pfad ausgeblendet").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/C:\\Users|C:\\private|\/home\/alice|\/var\/lib/)).not.toBeInTheDocument();
    expect(screen.queryByText(".env")).not.toBeInTheDocument();
    expect(screen.queryByText(/api_key=TEST_VALUE|should-never-render|private@example\.com|SELECT \*/)).not.toBeInTheDocument();
  });

  it("requests the canonical read-only stack route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(stackResponse()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await getProjectStack(27);

    expect(fetchMock).toHaveBeenCalledWith("/api/projects/27/stack", expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }));
  });
});
