import {
  Boxes,
  ChevronDown,
  Container,
  Database,
  FileCode2,
  GitBranch,
  Network,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";

import type {
  ProjectStackComposeFile,
  ProjectStackComposeService,
  ProjectStackDatabase,
  ProjectStackManifest,
  ProjectStackResponse,
  ProjectStackTechnology,
} from "@/api/contracts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

interface ProjectStackPanelProps {
  data?: ProjectStackResponse;
  error?: string;
  loading: boolean;
  onRetry: () => void;
}

const statusLabels: Record<string, string> = {
  parsed: "Erkannt",
  invalid: "Ungültig",
  skipped: "Übersprungen",
  ok: "In Ordnung",
  failed: "Fehler",
  limited: "Begrenzt geprüft",
  unavailable: "Nicht verfügbar",
  configured: "Konfiguriert",
  none: "Nicht konfiguriert",
  absent: "Nicht vorhanden",
};

function isSensitiveText(value: string) {
  return /(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]/i.test(value)
    || /(?:ghp_|github_pat_|sk-)[a-z0-9_-]{8,}/i.test(value)
    || /:\/\/[^/\s:@]+:[^/\s@]+@/.test(value);
}

function containsAbsolutePath(value: string) {
  return /(?:^|\s)[a-z]:[\\/]/i.test(value)
    || /(?:^|\s)\\\\[^\\\s]+/.test(value)
    || /(?:^|\s)\/(?:[^/\s]+\/)+[^\s]*/.test(value);
}

function safeLabel(value: unknown, fallback = "Unbekannt", maxLength = 160) {
  if (typeof value !== "string") return fallback;
  const label = value.trim().replace(/[\r\n\t]+/g, " ");
  if (!label || isSensitiveText(label) || containsAbsolutePath(label)) return fallback;
  return label.slice(0, maxLength);
}

function safeRelativePath(value: unknown) {
  if (typeof value !== "string") return undefined;
  const path = value.trim().replace(/\\/g, "/");
  if (
    !path
    || path.length > 240
    || path.startsWith("/")
    || path.startsWith("~/")
    || /^[a-z]:\//i.test(path)
    || path.split("/").includes("..")
    || path.includes("://")
    || /(^|\/)\.env(?:\.|$)/i.test(path)
    || isSensitiveText(path)
  ) return undefined;
  return path;
}

function formatBytes(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "Nicht ermittelt";
  if (value < 1_024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1_024;
  let unitIndex = 0;
  while (size >= 1_024 && unitIndex < units.length - 1) {
    size /= 1_024;
    unitIndex += 1;
  }
  return `${size >= 10 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function numberOrZero(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function statusLabel(status: unknown) {
  const normalized = typeof status === "string" ? status.toLowerCase() : "";
  return statusLabels[normalized] ?? "Status unbekannt";
}

function statusVariant(status: unknown): "healthy" | "attention" | "blocked" | "neutral" {
  if (["parsed", "ok", "configured"].includes(String(status).toLowerCase())) return "healthy";
  if (["invalid", "failed"].includes(String(status).toLowerCase())) return "blocked";
  if (["skipped", "limited", "unavailable"].includes(String(status).toLowerCase())) return "attention";
  return "neutral";
}

function reasonLabel(reason: unknown) {
  if (reason === "parse_error") return "Die Datei konnte nicht sicher ausgewertet werden.";
  if (reason === "size_limit") return "Die Datei überschreitet das sichere Scan-Limit.";
  return undefined;
}

function PathValue({ value }: { value: unknown }) {
  const path = safeRelativePath(value);
  return <code>{path ?? "Pfad ausgeblendet"}</code>;
}

function Tags({ values }: { values?: Array<string | null | undefined> }) {
  const labels = (values ?? [])
    .map((value) => safeLabel(value, ""))
    .filter(Boolean);
  if (!labels.length) return <span className="stack-muted">Keine</span>;
  return <div className="project-stack-tags">{labels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</div>;
}

function TechnologyList({ items, title }: { items?: ProjectStackTechnology[]; title: string }) {
  if (!items?.length) return null;
  return (
    <div className="project-stack-group">
      <h3>{title}</h3>
      <div className="project-stack-card-grid">
        {items.map((item, index) => {
          const evidence = (item.evidence ?? []).map(safeRelativePath).filter((path): path is string => Boolean(path));
          return (
            <article className="project-stack-card" key={item.id ?? `${item.name}-${index}`}>
              <header>
                <span className="project-stack-icon"><Boxes aria-hidden="true" /></span>
                <div><strong>{safeLabel(item.name, "Unbekannte Technologie")}</strong><small>{safeLabel(item.category, "Technologie")}</small></div>
              </header>
              {evidence.length ? <div className="project-stack-evidence"><span>Erkannt durch</span>{evidence.map((path) => <code key={path}>{path}</code>)}</div> : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function ManifestCard({ manifest }: { manifest: ProjectStackManifest }) {
  const explanation = reasonLabel(manifest.reason);
  return (
    <article className="project-stack-card project-stack-manifest">
      <header>
        <span className="project-stack-icon"><FileCode2 aria-hidden="true" /></span>
        <div><PathValue value={manifest.path} /><small>{safeLabel(manifest.ecosystem || manifest.kind, "Manifest")}</small></div>
        <Badge variant={statusVariant(manifest.status)}>{statusLabel(manifest.status)}</Badge>
      </header>
      <dl>
        <div><dt>Abhängigkeiten</dt><dd>{numberOrZero(manifest.dependency_count)}</dd></div>
        <div><dt>Entwicklung</dt><dd>{numberOrZero(manifest.dev_dependency_count)}</dd></div>
      </dl>
      {explanation ? <p>{explanation}</p> : null}
    </article>
  );
}

function ComposeService({ service }: { service: ProjectStackComposeService }) {
  const buildContext = safeRelativePath(service.build?.context);
  return (
    <article className="project-stack-service">
      <header>
        <div><Container aria-hidden="true" /><strong>{safeLabel(service.name, "Unbenannter Service")}</strong></div>
        <Badge variant={service.healthcheck ? "healthy" : "neutral"}>{service.healthcheck ? "Healthcheck" : "Ohne Healthcheck"}</Badge>
      </header>
      <dl>
        <div><dt>Image</dt><dd>{service.image ? safeLabel(service.image, "Ausgeblendet") : "Build aus Projekt"}</dd></div>
        {service.build ? <div><dt>Build</dt><dd>{service.build.external ? "Externer Kontext ausgeblendet" : buildContext ?? "Projektwurzel"}</dd></div> : null}
        <div><dt>Ports</dt><dd><Tags values={service.ports} /></dd></div>
        <div><dt>Abhängigkeiten</dt><dd><Tags values={service.depends_on} /></dd></div>
      </dl>
      {service.volumes?.length ? (
        <div className="project-stack-volumes">
          <span>Volumes</span>
          {service.volumes.map((volume, index) => {
            const source = volume.external ? "Externe Quelle ausgeblendet" : safeRelativePath(volume.source);
            const target = safeRelativePath(volume.target);
            return (
              <div key={`${volume.type}-${index}`}>
                <Badge>{safeLabel(volume.type, "Volume")}</Badge>
                <span>{source ?? "Anonymes Volume"}{target ? ` → ${target}` : ""}</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </article>
  );
}

function ComposeCard({ compose }: { compose: ProjectStackComposeFile }) {
  const explanation = reasonLabel(compose.reason);
  return (
    <article className="project-stack-compose">
      <header>
        <div><Network aria-hidden="true" /><span><PathValue value={compose.path} /><small>{compose.services?.length ?? 0} Services</small></span></div>
        <Badge variant={statusVariant(compose.status)}>{statusLabel(compose.status)}</Badge>
      </header>
      {explanation ? <p className="project-stack-note">{explanation}</p> : null}
      {compose.services?.length ? <div className="project-stack-services">{compose.services.map((service, index) => <ComposeService key={service.name ?? index} service={service} />)}</div> : <p className="project-stack-note">Keine Services erkannt.</p>}
      {(compose.named_volumes?.length || compose.networks?.length) ? (
        <footer>
          <div><span>Benannte Volumes</span><Tags values={compose.named_volumes} /></div>
          <div><span>Netzwerke</span><Tags values={compose.networks} /></div>
        </footer>
      ) : null}
    </article>
  );
}

function DatabaseCard({ database }: { database: ProjectStackDatabase }) {
  const explanation = reasonLabel(database.reason);
  return (
    <article className="project-stack-database">
      <header>
        <div><Database aria-hidden="true" /><span><PathValue value={database.path} /><small>{formatBytes(database.size_bytes)}</small></span></div>
        <div className="project-stack-badges"><Badge variant={statusVariant(database.status)}>{statusLabel(database.status)}</Badge><Badge variant={statusVariant(database.quick_check)}>Integrität: {statusLabel(database.quick_check)}</Badge></div>
      </header>
      <div className="project-stack-db-summary"><span>{database.table_count ?? "–"}<small>Tabellen gesamt</small></span><span>{database.tables?.length ?? 0}<small>angezeigt</small></span></div>
      {database.tables?.length ? (
        <div className="project-stack-table-list" role="table" aria-label="Datenbanktabellen und begrenzte Zählwerte">
          <div role="row"><span role="columnheader">Tabelle</span><span role="columnheader">Einträge</span></div>
          {database.tables.map((table, index) => (
            <div role="row" key={`${table.name}-${index}`}>
              <code role="cell">{safeLabel(table.name, "Unbenannte Tabelle")}</code>
              <span role="cell">{table.count_status === "ok" && typeof table.row_count === "number" ? table.row_count.toLocaleString("de-DE") : "Nicht ermittelt"}</span>
            </div>
          ))}
        </div>
      ) : <p className="project-stack-note">Keine Tabellennamen verfügbar.</p>}
      {database.tables_truncated ? <p className="project-stack-note">Die Tabellenliste wurde am sicheren Anzeigelimit gekürzt.</p> : null}
      {explanation ? <p className="project-stack-note">{explanation}</p> : null}
    </article>
  );
}

function hasStackData(data: ProjectStackResponse) {
  return Boolean(
    data.technologies?.length
    || data.database_drivers?.length
    || data.manifests?.length
    || data.docker?.dockerfiles?.length
    || data.docker?.compose_files?.length
    || data.databases?.length
    || data.processes?.length
    || data.topology?.nodes?.length,
  );
}

export function ProjectStackPanel({ data, error, loading, onRetry }: ProjectStackPanelProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const dockerfiles = data?.docker?.dockerfiles ?? [];
  const composeFiles = data?.docker?.compose_files ?? [];
  const composeServices = composeFiles.reduce((count, file) => count + (file.services?.length ?? 0), 0);

  return (
    <section aria-labelledby="project-stack-title" className="project-stack-section">
      <div className="project-section-heading">
        <div><p className="eyebrow">Projekt-Inventar</p><h2 id="project-stack-title">Technik &amp; Daten</h2></div>
        {data?.scan ? <Badge variant={data.scan.read_only ? "healthy" : "attention"}>{data.scan.read_only ? "Nur lesend geprüft" : "Scanstatus unbekannt"}</Badge> : null}
      </div>

      {loading ? <LoadingState description="Technologien, Container und Datenbank-Metadaten werden sicher eingelesen." title="Projekt-Stack wird geprüft" /> : null}
      {!loading && error ? <ErrorState description={error} onRetry={onRetry} title="Projekt-Stack nicht verfügbar" /> : null}
      {!loading && !error && data && !hasStackData(data) ? <EmptyState description="Im sicheren Scan wurden keine unterstützten Manifeste, Container oder Datenbanken erkannt." title="Noch keine Stack-Daten erkannt" /> : null}

      {!loading && !error && data && hasStackData(data) ? (
        <Collapsible className="grid gap-3" onOpenChange={setDetailsOpen} open={detailsOpen}>
          <div className="project-stack-summary" aria-label="Stack-Zusammenfassung">
            <div><Boxes aria-hidden="true" /><span><strong>{(data.technologies?.length ?? 0) + (data.database_drivers?.length ?? 0)}</strong><small>Technologien</small></span></div>
            <div><FileCode2 aria-hidden="true" /><span><strong>{data.manifests?.length ?? 0}</strong><small>Manifeste</small></span></div>
            <div><Container aria-hidden="true" /><span><strong>{composeServices}</strong><small>Compose-Services</small></span></div>
            <div><Database aria-hidden="true" /><span><strong>{data.databases?.length ?? 0}</strong><small>Datenbanken</small></span></div>
          </div>

          <CollapsibleTrigger asChild>
            <Button className="justify-self-end" size="sm" variant="secondary">
              {detailsOpen ? "Details ausblenden" : "Details anzeigen"}
              <ChevronDown
                aria-hidden="true"
                className={detailsOpen ? "rotate-180 transition-transform" : "transition-transform"}
              />
            </Button>
          </CollapsibleTrigger>

          <CollapsibleContent className="grid gap-4">
            <aside className="project-stack-privacy" aria-label="Datenschutz und Scan-Grenzen">
              <ShieldCheck aria-hidden="true" />
              <div>
                <strong>Struktur sichtbar, Inhalte geschützt</strong>
                <p>Anti-Gravity zeigt hier keine Secrets, `.env`-Werte, Tabellenzeilen, SQL oder absoluten Pfade. Datenbank-Zählwerte sind begrenzt und ausschließlich lesend ermittelt.</p>
              </div>
            </aside>

            <div className="project-stack-content">

              <TechnologyList items={data.technologies} title="Erkannte Technologien" />
              <TechnologyList items={data.database_drivers} title="Datenbank-Treiber" />

          {data.manifests?.length ? <div className="project-stack-group"><h3>Manifeste &amp; Abhängigkeiten</h3><div className="project-stack-card-grid">{data.manifests.map((manifest, index) => <ManifestCard key={`${manifest.path}-${index}`} manifest={manifest} />)}</div></div> : null}

          {(dockerfiles.length || composeFiles.length) ? (
            <div className="project-stack-group">
              <h3>Docker &amp; Compose</h3>
              {dockerfiles.length ? <div className="project-stack-dockerfiles">{dockerfiles.map((dockerfile, index) => (
                <article className="project-stack-dockerfile" key={`${dockerfile.path}-${index}`}>
                  <header><div><Container aria-hidden="true" /><span><PathValue value={dockerfile.path} /><small>{dockerfile.stages?.length ?? 0} Build-Stufen</small></span></div><Badge variant={statusVariant(dockerfile.status)}>{statusLabel(dockerfile.status)}</Badge></header>
                  <dl><div><dt>Basis-Images</dt><dd><Tags values={dockerfile.base_images} /></dd></div><div><dt>Exponierte Ports</dt><dd><Tags values={dockerfile.exposed_ports} /></dd></div><div><dt>Healthcheck</dt><dd>{statusLabel(dockerfile.healthcheck)}</dd></div></dl>
                  {reasonLabel(dockerfile.reason) ? <p className="project-stack-note">{reasonLabel(dockerfile.reason)}</p> : null}
                </article>
              ))}</div> : null}
              {composeFiles.length ? <div className="project-stack-compose-list">{composeFiles.map((compose, index) => <ComposeCard compose={compose} key={`${compose.path}-${index}`} />)}</div> : null}
            </div>
          ) : null}

          {data.databases?.length ? <div className="project-stack-group"><h3>Datenbank-Metadaten</h3><div className="project-stack-database-grid">{data.databases.map((database, index) => <DatabaseCard database={database} key={`${database.path}-${index}`} />)}</div></div> : null}

          {data.processes?.length ? (
            <div className="project-stack-group"><h3>Prozesse</h3><div className="project-stack-processes">{data.processes.map((process, index) => <article key={process.id ?? index}><span className="project-stack-icon"><ScanSearch aria-hidden="true" /></span><div><strong>{safeLabel(process.name, "Unbenannter Prozess")}</strong><small>{safeLabel(process.kind, "Prozess")} · {safeLabel(process.status, "Status unbekannt")}</small></div>{process.port != null ? <Badge>Port {safeLabel(String(process.port))}</Badge> : null}</article>)}</div></div>
          ) : null}

          {data.topology?.nodes?.length ? (
            <div className="project-stack-group"><h3>Topologie</h3><div className="project-stack-topology"><div>{data.topology.nodes.map((node, index) => <article key={node.id ?? index}><GitBranch aria-hidden="true" /><span><strong>{safeLabel(node.label, "Komponente")}</strong><small>{safeLabel(node.kind, "Knoten")}{node.port != null ? ` · Port ${safeLabel(String(node.port))}` : ""}</small></span></article>)}</div>{data.topology.edges?.length ? <ul>{data.topology.edges.map((edge, index) => <li key={`${edge.source}-${edge.target}-${index}`}>{safeLabel(edge.source, "Quelle")} → {safeLabel(edge.target, "Ziel")}{edge.label ? ` · ${safeLabel(edge.label)}` : ""}</li>)}</ul> : null}</div></div>
          ) : null}

              <footer className="project-stack-scan-note">
                <ShieldCheck aria-hidden="true" />
                <span><strong>{typeof data.scan?.files_considered === "number" ? `${data.scan.files_considered} Dateien berücksichtigt` : "Dateianzahl nicht gemeldet"}</strong><small>{data.scan?.truncated ? "Der Scan wurde an einem Sicherheitslimit gekürzt." : "Scan innerhalb der konfigurierten Sicherheitslimits."}</small></span>
              </footer>
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
    </section>
  );
}
