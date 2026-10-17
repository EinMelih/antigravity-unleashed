import { useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, RefreshCw, ShieldCheck, Workflow } from "lucide-react";
import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { RichText } from "@/features/chats/rich-text";
import {
  getControlPlaneDocumentation,
  type ControlPlaneDocumentId,
} from "@/features/more/api";

const DEFAULT_DOCUMENT: { id: ControlPlaneDocumentId; label: string } = {
  id: "index",
  label: "Übersicht",
};

const DOCUMENTS: ReadonlyArray<{ id: ControlPlaneDocumentId; label: string }> = [
  DEFAULT_DOCUMENT,
  { id: "operator", label: "Operator-Handbuch" },
  { id: "api", label: "API-Referenz" },
  { id: "database", label: "Datenbank" },
  { id: "codebase", label: "Codebase" },
  { id: "dependencies", label: "Dependencies" },
  { id: "configuration", label: "Konfiguration" },
  { id: "operations", label: "Betrieb" },
  { id: "knowledge-chain", label: "Wissenskette" },
  { id: "plan-amendments", label: "Planänderungen" },
  { id: "routes", label: "Generierte HTTP-Routen" },
  { id: "schema", label: "Generiertes SQLite-Schema" },
  { id: "imports", label: "Python-Importgraph" },
  { id: "frontend-imports", label: "Frontend-Importgraph" },
];

const DOCUMENT_LINKS: Readonly<Record<string, string>> = {
  "../README.md": "readme",
  "../OPEN_SOURCE_READINESS.md": "open-source",
  "../CONTRIBUTING.md": "contributing",
  "../SECURITY.md": "security",
  "../CODE_OF_CONDUCT.md": "conduct",
  "../deploy/DEPLOY.md": "deploy",
  "../config.example.json": "config-example",
  "API_REFERENCE.md": "api",
  "DATABASE_SCHEMA.md": "database",
  "CODEBASE_GUIDE.md": "codebase",
  "DEPENDENCIES.md": "dependencies",
  "CONFIGURATION.md": "configuration",
  "OPERATIONS.md": "operations",
  "KNOWLEDGE_CHAIN.md": "knowledge-chain",
  "PLAN_AMENDMENTS.md": "plan-amendments",
  "ARCHITECTURE.md": "architecture",
  "ENGINEERING_CONTROL_PLANE_ARCHITECTURE.md": "control-plane-architecture",
  "AI_ENGINEERING_CONTROL_HUB_MASTERPLAN.md": "masterplan",
  "MASTERPLAN_IMPLEMENTATION_STATUS.md": "implementation-status",
  "MASTERPLAN_PARITY_LEDGER.md": "parity",
  "GITHUB_FIRST_WORKFLOW.md": "github-workflow",
  "CUSTOM_MODELS.md": "custom-models",
  "CONTROL_CENTER_STAGE1.md": "control-center-stage1",
  "react-migration/API_CONTRACTS.md": "react-api-contracts",
  "react-migration/LOCAL_DEVELOPMENT.md": "react-local-development",
  "react-migration/TEST_MATRIX.md": "react-test-matrix",
  "react-migration/MIGRATION_LOG.md": "react-migration-log",
  "generated/HTTP_ROUTES.md": "routes",
  "generated/http_routes.json": "routes-json",
  "generated/SQLITE_SCHEMA.md": "schema",
  "generated/database_schema.json": "schema-json",
  "generated/PYTHON_IMPORT_GRAPH.md": "imports",
  "generated/python_import_graph.json": "imports-json",
  "generated/FRONTEND_IMPORT_GRAPH.md": "frontend-imports",
  "generated/frontend_import_graph.json": "frontend-imports-json",
  "generated/DEPENDENCY_INVENTORY.md": "dependency-inventory",
  "generated/dependencies.json": "dependencies-json",
};

function resolveDocumentationLink(
  href: string,
  currentDocumentId: ControlPlaneDocumentId,
) {
  const fragmentIndex = href.indexOf("#");
  const path = fragmentIndex >= 0 ? href.slice(0, fragmentIndex) : href;
  const rawFragment = fragmentIndex >= 0 ? href.slice(fragmentIndex + 1) : "";
  const documentId = path ? DOCUMENT_LINKS[path] : currentDocumentId;
  if (!documentId) return undefined;
  if (rawFragment && !/^[A-Za-z0-9][A-Za-z0-9._~!$&'()*+,;=:@%/-]*$/.test(rawFragment)) {
    return undefined;
  }
  const fragment = rawFragment ? `#${rawFragment}` : "";
  return `/docs/control-plane/${documentId}${fragment}`;
}

export function HelpPage() {
  const [documentId, setDocumentId] = useState<ControlPlaneDocumentId>("index");
  const selectedDocument = DOCUMENTS.find(({ id }) => id === documentId) ?? DEFAULT_DOCUMENT;
  const docs = useQuery({
    queryKey: ["control-plane", "documentation", documentId],
    queryFn: () => getControlPlaneDocumentation(documentId),
    staleTime: 60_000,
  });

  return (
    <section className="more-detail-page">
      <header className="more-page-header">
        <div><p className="eyebrow">Hilfe & Dokumentation</p><h1>Anti-Gravity sicher steuern</h1><p>Handbuch, API, Datenbank, Codebase und generierte Referenzen an einem Ort.</p></div>
        <Button asChild variant="secondary"><a href={`/docs/control-plane/${documentId}`} rel="noreferrer" target="_blank">Rohfassung öffnen <ExternalLink className="size-3.5" /></a></Button>
      </header>
      <div className="help-entry-grid">
        <article><Workflow className="size-5" /><strong>1. Studio</strong><p>Projektzustand und nächste Schritte prüfen.</p></article>
        <article><ShieldCheck className="size-5" /><strong>2. Automation</strong><p>Plan, Änderungen, Tests und Evidence vor Freigaben kontrollieren.</p></article>
        <article><BookOpen className="size-5" /><strong>3. Projekt</strong><p>Runtime starten, Vorschau prüfen und erst danach mergen oder deployen.</p></article>
      </div>
      <article className="documentation-panel">
        <div className="documentation-toolbar">
          <label className="documentation-picker">
            <span>Dokument</span>
            <select
              aria-label="Dokument"
              onChange={(event) => setDocumentId(event.target.value as ControlPlaneDocumentId)}
              value={documentId}
            >
              {DOCUMENTS.map((document) => <option key={document.id} value={document.id}>{document.label}</option>)}
            </select>
          </label>
          <div className="documentation-toolbar-actions">
            <span>{selectedDocument.label}</span>
            <Button aria-label="Dokumentation aktualisieren" onClick={() => void docs.refetch()} size="icon" variant="ghost"><RefreshCw className={docs.isFetching ? "size-4 motion-safe:animate-spin" : "size-4"} /></Button>
          </div>
        </div>
        {docs.isPending ? <LoadingState description={`${selectedDocument.label} wird geladen.`} /> : null}
        {docs.isError ? <ErrorState description={docs.error.message} onRetry={() => void docs.refetch()} title="Dokumentation nicht verfügbar" /> : null}
        {docs.data ? (
          <RichText
            content={docs.data}
            resolveLink={(href) => resolveDocumentationLink(href, documentId)}
          />
        ) : null}
      </article>
    </section>
  );
}
