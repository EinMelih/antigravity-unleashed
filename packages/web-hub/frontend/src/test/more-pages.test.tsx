import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomModel } from "@/api/contracts";
import { CustomModelSettings } from "@/features/more/custom-model-settings";
import { HelpPage } from "@/pages/help-page";
import { KnowledgePage } from "@/pages/knowledge-page";

const mocks = vi.hoisted(() => ({
  getControlPlaneDocumentation: vi.fn(),
  getKnowledgeChains: vi.fn(),
  getLessons: vi.fn(),
  getProjects: vi.fn(),
}));

vi.mock("@/features/more/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/features/more/api")>(),
  getControlPlaneDocumentation: mocks.getControlPlaneDocumentation,
  getLessons: mocks.getLessons,
}));
vi.mock("@/features/knowledge/api", () => ({
  getKnowledgeChains: mocks.getKnowledgeChains,
}));
vi.mock("@/features/studio/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/features/studio/api")>(),
  getProjects: mocks.getProjects,
}));

function withClient(content: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{content}</QueryClientProvider>);
}

const model: CustomModel = {
  id: 4,
  name: "Local Proxy",
  base_url: "http://127.0.0.1:11434/v1",
  model_id: "local-model",
  api_key_header: "Authorization",
  api_key_prefix: "Bearer",
  extra_headers: {},
  system_prompt: "",
  temperature: 0.7,
  verify_tls: true,
  timeout_seconds: 60,
  has_api_key: true,
};

describe("secondary React pages", () => {
  beforeEach(() => {
    mocks.getKnowledgeChains.mockReset().mockResolvedValue({
      chains: [],
      unlinked: { idea_seeds: [], artifacts: [], candidates: [] },
    });
    mocks.getLessons.mockReset().mockResolvedValue({ lessons: [] });
    mocks.getProjects.mockReset().mockResolvedValue({ projects: [] });
  });

  it("renders the canonical control-plane documentation", async () => {
    mocks.getControlPlaneDocumentation.mockResolvedValue([
      "# Operator-Handbuch",
      "",
      "- Evidence prüfen",
      "- [API-Vertrag](API_REFERENCE.md)",
      "",
      "| Bereich | Zustand |",
      "| --- | --- |",
      "| Datenbank | Read-only |",
    ].join("\n"));
    withClient(<HelpPage />);
    expect(await screen.findByRole("heading", { name: "Operator-Handbuch" })).toBeVisible();
    expect(screen.getByText("Evidence prüfen")).toBeVisible();
    expect(screen.getByRole("link", { name: "API-Vertrag" })).toHaveAttribute(
      "href",
      "/docs/control-plane/api",
    );
    expect(screen.getByRole("table")).toBeVisible();
  });

  it("preserves safe fragments for same-document and allowlisted documentation links", async () => {
    mocks.getControlPlaneDocumentation.mockResolvedValue([
      "# Anti-Gravity documentation",
      "",
      "- [API-Vertrag](#api-vertrag)",
      "- [Ports](../README.md#ports--services)",
      "",
      "## API-Vertrag",
    ].join("\n"));

    withClient(<HelpPage />);

    expect(await screen.findByRole("link", { name: "API-Vertrag" })).toHaveAttribute(
      "href",
      "/docs/control-plane/index#api-vertrag",
    );
    expect(screen.getByRole("link", { name: "Ports" })).toHaveAttribute(
      "href",
      "/docs/control-plane/readme#ports--services",
    );
  });

  it("switches between allowlisted documentation pages", async () => {
    mocks.getControlPlaneDocumentation.mockImplementation(async (documentId) => (
      documentId === "database"
        ? "# Database schema\n\nPersistenz und Beziehungen"
        : "# Anti-Gravity documentation\n\nDokumentationsübersicht"
    ));
    withClient(<HelpPage />);

    expect(await screen.findByRole("heading", { name: "Anti-Gravity documentation" })).toBeVisible();
    const selector = screen.getByRole("combobox", { name: "Dokument" });
    expect(selector).toHaveValue("index");
    expect(screen.getByRole("option", { name: "Dependencies" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Konfiguration" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Wissenskette" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Frontend-Importgraph" })).toBeVisible();

    fireEvent.change(selector, { target: { value: "database" } });

    expect(await screen.findByRole("heading", { name: "Database schema" })).toBeVisible();
    expect(mocks.getControlPlaneDocumentation).toHaveBeenCalledWith("database");
    expect(screen.getByRole("link", { name: /Rohfassung öffnen/ })).toHaveAttribute(
      "href",
      "/docs/control-plane/database",
    );
  });

  it("keeps the document picker available when one document is missing", async () => {
    mocks.getControlPlaneDocumentation.mockImplementation(async (documentId) => {
      if (documentId === "database") throw new Error("Database documentation is missing.");
      return documentId === "api"
        ? "# API reference\n\nVerträge"
        : "# Anti-Gravity documentation\n\nDokumentationsübersicht";
    });
    withClient(<HelpPage />);

    expect(await screen.findByRole("heading", { name: "Anti-Gravity documentation" })).toBeVisible();
    const selector = screen.getByRole("combobox", { name: "Dokument" });
    fireEvent.change(selector, { target: { value: "database" } });

    expect(await screen.findByRole("heading", { name: "Dokumentation nicht verfügbar" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Dokument" })).toHaveValue("database");
    fireEvent.change(screen.getByRole("combobox", { name: "Dokument" }), { target: { value: "api" } });

    expect(await screen.findByRole("heading", { name: "API reference" })).toBeVisible();
  });

  it("shows lessons with their project and filters them", async () => {
    mocks.getLessons.mockResolvedValue({ lessons: [{ id: 1, project_id: 8, issue_id: 12, technique: "Portkonflikte vermeiden", solution: "Ports vor dem Start reservieren.", created_at: "2026-08-01T12:00:00Z" }] });
    mocks.getProjects.mockResolvedValue({ projects: [{ id: 8, name: "Runtime", path: "D:\\Runtime", github_url: "", github_owner: "", github_repo: "runtime", default_branch: "main", git_branch: "main", source_kind: "github", github_bootstrap_required: false, github_bootstrap_status: "ready", antigravity_linked: true, antigravity_project_name: "Runtime" }] });
    withClient(<KnowledgePage />);
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Erfahrungen" }), { button: 0 });
    const lessonHeading = await screen.findByText("Portkonflikte vermeiden");
    expect(lessonHeading).toBeVisible();
    expect(within(lessonHeading.closest("article") as HTMLElement).getByText("runtime")).toBeVisible();
    fireEvent.change(screen.getByPlaceholderText("Technik, Lösung oder Projekt suchen"), { target: { value: "nicht vorhanden" } });
    expect(screen.getByRole("heading", { name: "Keine passenden Erfahrungen" })).toBeVisible();
  });

  it("shows a read-only knowledge chain with separate PR branches and truthful coverage", async () => {
    mocks.getKnowledgeChains.mockResolvedValue({
      chains: [{
        project: { id: 8, name: "Runtime" },
        idea_seed: { id: "seed-1", title: "Ports stabilisieren", status: "planned", source: "human", created_at: "2026-08-01T10:00:00Z" },
        campaign: { id: "campaign-1", title: "Runtime-Härtung", status: "active", version: 2, base_sha: "a".repeat(40), plan_signature: "plan-v2" },
        idea_group: [
          { id: "artifact-1", artifact_type: "idea_group", title: "Idea Group", status: "approved", version: 1, relative_path: "docs/ideas/runtime.md", content_sha256: "b".repeat(64), materialization_status: "present", materialized_sha256: "b".repeat(64), materialized_commit_sha: "c".repeat(40), materialized_at: "2026-08-01T11:00:00Z" },
        ],
        artifacts: [
          { id: "artifact-2", artifact_type: "design", title: "Runtime design", status: "approved", version: 2, relative_path: "docs/design/runtime.md", content_sha256: "d".repeat(64), materialization_status: "failed", materialized_sha256: "", materialized_commit_sha: "", materialized_at: null },
          { id: "artifact-3", artifact_type: "adr", title: "ADR 12", status: "accepted", version: 1, relative_path: "docs/adr/0012.md", content_sha256: "e".repeat(64), materialization_status: "not_requested", materialized_sha256: "", materialized_commit_sha: "", materialized_at: null },
          { id: "artifact-4", artifact_type: "repository_map", title: "Repository map", status: "draft", version: 1, relative_path: "docs/maps/runtime.md", content_sha256: "f".repeat(64), materialization_status: "pending", materialized_sha256: "", materialized_commit_sha: "", materialized_at: null },
        ],
        relations: [
          { source_artifact_id: "artifact-2", target_artifact_id: "artifact-3", relation_type: "decided_by" },
          { source_artifact_id: "artifact-2", target_artifact_id: "artifact-3", relation_type: "contains" },
          { source_artifact_id: "artifact-2", target_artifact_id: "artifact-4", relation_type: "informs" },
          { source_artifact_id: "artifact-3", target_artifact_id: "artifact-2", relation_type: "references" },
          { source_artifact_id: "artifact-4", target_artifact_id: "artifact-3", relation_type: "follows_decision" },
        ],
        branches: [
          {
            candidate: { id: "candidate-1", title: "Port reservation", status: "merged", priority: 1, base_sha: "a".repeat(40) },
            artifacts: [],
            task: { id: "task-1", status: "merged", issue_number: 12, issue_url: "https://github.com/acme/runtime/issues/12", pr_number: 21, pr_url: "https://github.com/acme/runtime/pull/21", current_sha: "1".repeat(40), merged_sha: "2".repeat(40) },
            evidence: { id: "evidence-1", status: "accepted", sha: "2".repeat(40), summary: "Targeted tests passed." },
            deployments: [{ id: "deployment-1", environment: "preview", status: "healthy", sha: "2".repeat(40), artifact_ref: "image@sha256:demo", previous_stable_sha: "3".repeat(40), rollback_of: null, started_at: "2026-08-01T12:00:00Z", finished_at: "2026-08-01T12:05:00Z" }],
          },
          {
            candidate: { id: "candidate-2", title: "Runtime health", status: "approved", priority: 2, base_sha: "2".repeat(40) },
            artifacts: [],
            task: { id: "task-2", status: "running", issue_number: 13, issue_url: "https://example.com/issues/13", pr_number: null, pr_url: "", current_sha: "4".repeat(40), merged_sha: "" },
            evidence: null,
            deployments: [],
          },
        ],
        coverage: { idea_group_files: 1, linked_artifacts: 4, unlinked_artifacts: 0, linked_candidates: 2, unlinked_candidates: 0 },
      }],
      unlinked: { idea_seeds: [], artifacts: [], candidates: [] },
    });

    withClient(<KnowledgePage />);

    expect(await screen.findByRole("heading", { name: "Ports stabilisieren" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Port reservation" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Runtime health" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Ursprüngliche Idee" })).toBeVisible();
    expect(screen.getAllByRole("heading", { name: "Prüfnachweise" })).toHaveLength(2);
    expect(screen.getAllByRole("heading", { name: "Auslieferung" })).toHaveLength(2);
    expect(screen.getByText("Ideen-Dokument · Freigegeben")).toBeVisible();
    expect(screen.getByText("Technisches Konzept · Freigegeben")).toBeVisible();
    expect(screen.getByText("Zusammengeführt")).toBeVisible();
    expect(screen.getByText("Vorschau")).toBeVisible();
    for (const rawValue of screen.queryAllByText(/approved|merged|healthy|preview/)) {
      expect(rawValue).not.toBeVisible();
    }
    const relationSummary = screen.getByText("5 Querverweise anzeigen");
    const relationDetails = relationSummary.closest("details") as HTMLElement;
    for (const rawRelation of ["decided_by", "contains", "informs", "references", "follows_decision"]) {
      expect(within(relationDetails).getByText(rawRelation)).not.toBeVisible();
    }
    fireEvent.click(relationSummary);
    expect(within(relationDetails).getByText(/→ enthält →/)).toBeVisible();
    expect(within(relationDetails).getByText(/→ liefert die Grundlage für →/)).toBeVisible();
    expect(within(relationDetails).getByText(/→ verweist auf →/)).toBeVisible();
    expect(within(relationDetails).getByText(/→ folgt der Entscheidung →/)).toBeVisible();
    const coverage = screen.getByLabelText("Abdeckung der Wissenskette");
    expect(within(coverage).getByText("1/5")).toBeVisible();
    expect(within(coverage).getByText("Unvollständig")).toBeVisible();
    expect(screen.getByRole("link", { name: "Aufgabe #12 auf GitHub öffnen" })).toHaveAttribute("href", "https://github.com/acme/runtime/issues/12");
    expect(screen.queryByRole("link", { name: "Aufgabe #13 auf GitHub öffnen" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Vorhanden").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fehlgeschlagen").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Nicht angefordert").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Ausstehend").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/kein Nachweis einer externen Auslieferung/i)).toHaveLength(2);
  });

  it("marks an Idea Group complete only at exactly five of five documents", async () => {
    mocks.getKnowledgeChains.mockResolvedValue({
      chains: [{
        project: { id: 8, name: "Runtime" },
        idea_seed: { id: "seed-complete", title: "Vollständige Idee", status: "planned", source: "human", created_at: "2026-08-01T10:00:00Z" },
        campaign: null,
        idea_group: [],
        artifacts: [],
        relations: [],
        branches: [],
        coverage: { idea_group_files: 5, linked_artifacts: 0, unlinked_artifacts: 0, linked_candidates: 0, unlinked_candidates: 0 },
      }],
      unlinked: { idea_seeds: [], artifacts: [], candidates: [] },
    });

    withClient(<KnowledgePage />);

    const coverage = await screen.findByLabelText("Abdeckung der Wissenskette");
    expect(within(coverage).getByText("5/5")).toBeVisible();
    expect(within(coverage).getByText("Vollständig")).toBeVisible();
    expect(within(coverage).queryByText("Unvollständig")).not.toBeInTheDocument();
  });

  it("keeps Lessons Learned usable when the knowledge-chain request fails", async () => {
    mocks.getKnowledgeChains.mockRejectedValue(new Error("Wissenskette nicht erreichbar"));
    mocks.getLessons.mockResolvedValue({ lessons: [{ id: 1, project_id: null, issue_id: null, technique: "Kleine PRs", solution: "Slices getrennt prüfen.", created_at: "2026-08-01T12:00:00Z" }] });

    withClient(<KnowledgePage />);

    expect(await screen.findByRole("heading", { name: "Wissenskette nicht verfügbar" })).toBeVisible();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Erfahrungen" }), { button: 0 });
    expect(await screen.findByText("Kleine PRs")).toBeVisible();
  });

  it("requests knowledge chains for the selected project", async () => {
    mocks.getProjects.mockResolvedValue({ projects: [{ id: 8, name: "Runtime", path: "D:\\Runtime", github_url: "", github_owner: "", github_repo: "runtime", default_branch: "main", git_branch: "main", source_kind: "github", github_bootstrap_required: false, github_bootstrap_status: "ready", antigravity_linked: true, antigravity_project_name: "Runtime" }] });
    withClient(<KnowledgePage />);

    await screen.findByRole("option", { name: "runtime" });
    const projectFilter = await screen.findByRole("combobox", { name: "Projekt für Wissen" });
    fireEvent.change(projectFilter, { target: { value: "8" } });

    await waitFor(() => expect(mocks.getKnowledgeChains).toHaveBeenLastCalledWith(8));
  });

  it("keeps the active project filter visible when switching to Lessons Learned", async () => {
    mocks.getProjects.mockResolvedValue({
      projects: [
        { id: 8, name: "Runtime", path: "D:\\Runtime", github_url: "", github_owner: "", github_repo: "runtime", default_branch: "main", git_branch: "main", source_kind: "github", github_bootstrap_required: false, github_bootstrap_status: "ready", antigravity_linked: true, antigravity_project_name: "Runtime" },
        { id: 9, name: "Portal", path: "D:\\Portal", github_url: "", github_owner: "", github_repo: "portal", default_branch: "main", git_branch: "main", source_kind: "github", github_bootstrap_required: false, github_bootstrap_status: "ready", antigravity_linked: true, antigravity_project_name: "Portal" },
      ],
    });
    mocks.getLessons.mockResolvedValue({
      lessons: [
        { id: 1, project_id: 8, issue_id: null, technique: "Runtime-Lektion", solution: "Runtime bleibt stabil.", created_at: "2026-08-01T12:00:00Z" },
        { id: 2, project_id: 9, issue_id: null, technique: "Portal-Lektion", solution: "Portal bleibt stabil.", created_at: "2026-08-01T12:00:00Z" },
      ],
    });
    withClient(<KnowledgePage />);

    await screen.findByRole("option", { name: "runtime" });
    const projectFilter = await screen.findByRole("combobox", { name: "Projekt für Wissen" });
    fireEvent.change(projectFilter, { target: { value: "8" } });
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Erfahrungen" }), { button: 0 });

    expect(screen.getByRole("combobox", { name: "Projekt für Wissen" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Projekt für Wissen" })).toHaveValue("8");
    expect(await screen.findByText("Runtime-Lektion")).toBeVisible();
    expect(screen.queryByText("Portal-Lektion")).not.toBeInTheDocument();
  });

  it("opens an explicit form for a new custom API model", () => {
    render(<CustomModelSettings models={[]} onDelete={vi.fn()} onSave={vi.fn()} onTest={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Modell hinzufügen" }));
    expect(screen.getByText("Eigenes Modell hinzufügen")).toBeVisible();
    expect(screen.getByText("API Base URL")).toBeVisible();
  });

  it("requires a second action before deleting a provider", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(<CustomModelSettings models={[model]} onDelete={onDelete} onSave={vi.fn()} onTest={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Local Proxy löschen" }));
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Löschen" }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(4));
  });
});
