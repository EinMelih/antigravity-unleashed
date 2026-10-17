import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Box,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  HardDrive,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  Workflow,
} from "lucide-react";

import { ApiError } from "@/api/errors";
import type { SystemServiceOverview } from "@/api/contracts";
import { ErrorState, LoadingState, OfflineState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSystemOverview } from "@/features/system/api";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

function formatUptime(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} h ${minutes} min` : `${Math.max(0, minutes)} min`;
}

function serviceTone(status: string): "healthy" | "attention" | "blocked" {
  if (status === "healthy") return "healthy";
  if (status === "offline") return "blocked";
  return "attention";
}

function serviceLabel(service: SystemServiceOverview) {
  if (service.status === "healthy") return "Online";
  if (service.status === "offline") return "Offline";
  return `HTTP ${service.http_status ?? "–"}`;
}

export function SystemStatusPage() {
  const overview = useQuery({
    queryKey: ["system", "overview"],
    queryFn: getSystemOverview,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  if (overview.isPending) {
    return <LoadingState description="Dienste, Datenbank und Deployment werden geprüft." />;
  }

  if (overview.isError) {
    if (overview.error instanceof ApiError && overview.error.offline) {
      return <OfflineState onRetry={() => void overview.refetch()} />;
    }
    return <ErrorState description={overview.error.message} onRetry={() => void overview.refetch()} />;
  }

  const data = overview.data;
  const databaseHealthy = data.database.quick_check === "ok" && data.database.foreign_key_violations === 0;

  return (
    <section className="system-overview-page">
      <header className="more-page-header">
        <div>
          <p className="eyebrow">Systemstatus & Diagnose</p>
          <h1>System & Stack</h1>
          <p>Dienste, Datenbank, Laufzeit und Container-Kapselung auf einen Blick – ohne Secrets oder gespeicherte Inhalte offenzulegen.</p>
        </div>
        <Button disabled={overview.isFetching} onClick={() => void overview.refetch()} variant="secondary">
          <RefreshCw className={overview.isFetching ? "size-4 motion-safe:animate-spin" : "size-4"} />
          Aktualisieren
        </Button>
      </header>

      <div className={`system-health-banner is-${data.status}`}>
        <div className="system-health-icon">{data.status === "healthy" ? <ShieldCheck /> : <Activity />}</div>
        <div>
          <span>Gesamtzustand</span>
          <strong>{data.status === "healthy" ? "Betriebsbereit" : "Aufmerksamkeit nötig"}</strong>
          <p>{data.services.filter((service) => service.status === "healthy").length}/{data.services.length} Dienste online · SQLite {databaseHealthy ? "konsistent" : "prüfen"} · optionales Docker-Profil {data.deployment.configured ? "geprüft" : "prüfen"}</p>
        </div>
      </div>

      <section className="system-section" aria-labelledby="system-services-heading">
        <div className="system-section-heading">
          <div><p className="eyebrow">Laufender Stack</p><h2 id="system-services-heading">Fünf Kerndienste</h2></div>
          <span>Live-Prüfung alle 30 Sekunden</span>
        </div>
        <div className="system-service-grid">
          {data.services.map((service) => (
            <article className="system-service-card" key={service.id}>
              <header><Server className="size-5" /><Badge variant={serviceTone(service.status)}>{serviceLabel(service)}</Badge></header>
              <h3>{service.name}</h3><p>{service.role}</p>
              <dl><div><dt>Port</dt><dd>{service.port}</dd></div><div><dt>Latenz</dt><dd>{service.latency_ms === null ? "–" : `${service.latency_ms} ms`}</dd></div></dl>
            </article>
          ))}
        </div>
      </section>

      <section className="system-section" aria-labelledby="database-heading">
        <div className="system-section-heading">
          <div><p className="eyebrow">Persistenz</p><h2 id="database-heading">Datenbank</h2></div>
          <Badge variant={databaseHealthy ? "healthy" : "attention"}>{databaseHealthy ? "Integrität OK" : `${data.database.foreign_key_violations} FK-Probleme`}</Badge>
        </div>
        <div className="system-database-panel">
          <div className="system-stat-grid">
            <article><Database /><span>Engine</span><strong>{data.database.engine}</strong><small>{data.database.filename}</small></article>
            <article><HardDrive /><span>Größe</span><strong>{formatBytes(data.database.size_bytes)}</strong><small>{data.database.table_count} Tabellen</small></article>
            <article><Workflow /><span>Journal</span><strong>{data.database.journal_mode.toUpperCase()}</strong><small>Schema v{data.database.schema_version}</small></article>
            <article><CheckCircle2 /><span>Quick Check</span><strong>{data.database.quick_check.toUpperCase()}</strong><small>{data.database.foreign_key_violations} FK-Verletzungen</small></article>
          </div>
          <div className="system-record-grid" aria-label="Wichtige Datenbankzähler">
            {data.database.record_counts.map((item) => <div key={item.table} title={item.table}><span>{item.label}</span><strong>{item.count.toLocaleString("de-DE")}</strong></div>)}
          </div>
          <p className="system-privacy-note"><ShieldCheck className="size-4" />{data.database.privacy}</p>
        </div>
      </section>

      <section className="system-section" aria-labelledby="architecture-heading">
        <div className="system-section-heading">
          <div><p className="eyebrow">Architektur</p><h2 id="architecture-heading">So fließt die Arbeit</h2></div>
          <span>{data.deployment.model}</span>
        </div>
        <ol className="system-flow" aria-label="Anti-Gravity Stackfluss">
          <li><Box /><strong>React UI</strong><span>Bedienung</span></li>
          <li><Network /><strong>Hub Gateway</strong><span>API & Routing</span></li>
          <li><Cpu /><strong>Agent Services</strong><span>Planung & Ausführung</span></li>
          <li><Database /><strong>SQLite</strong><span>Audit & Zustand</span></li>
          <li><Workflow /><strong>GitHub</strong><span>PR, CI & Review</span></li>
        </ol>
      </section>

      <section className="system-stack-grid" aria-label="Laufzeit und Deployment">
        <article className="system-detail-card">
          <header><Cpu /><div><p className="eyebrow">Laufzeit</p><h2>Lokale Engine</h2></div></header>
          <dl>
            <div><dt>Python</dt><dd>{data.runtime.python_version}</dd></div>
            <div><dt>Hub-Version</dt><dd>{data.runtime.hub_version}</dd></div>
            <div><dt>Build</dt><dd>{data.runtime.build_sha}</dd></div>
            <div><dt>Installationsmodus</dt><dd>{data.deployment.containerized ? "Docker" : "Native"}</dd></div>
            <div><dt>Plattform</dt><dd>{data.runtime.platform} · {data.runtime.architecture}</dd></div>
            <div><dt>CPU</dt><dd>{data.runtime.cpu_count ?? "–"} logische Kerne</dd></div>
            <div><dt>Uptime</dt><dd>{formatUptime(data.runtime.uptime_seconds)}</dd></div>
            <div><dt>Monitoring-Historie</dt><dd>{data.runtime.watchdog_retention_days} Tage</dd></div>
            <div><dt>API-Inhalte im Log</dt><dd>{data.runtime.api_content_logging ? "Opt-in aktiv" : "Aus · nur Metadaten"}</dd></div>
            <div><dt>Anti-Gravity</dt><dd>{data.integrations.antigravity.connected ? `Verbunden · Port ${data.integrations.antigravity.port}` : "Nicht verbunden"}</dd></div>
            <div><dt>Web-IDE</dt><dd>{data.integrations.web_ide.running ? `Online · Port ${data.integrations.web_ide.port}` : "Optional / offline"}</dd></div>
          </dl>
        </article>

        <article className="system-detail-card">
          <header><Box /><div><p className="eyebrow">Optionales Deployment</p><h2>Docker-Profil & Persistenz</h2></div></header>
          <ul className="system-check-list">
            {data.deployment.checks.map((check) => (
              <li key={check.id}>
                <span className={check.ready ? "is-ready" : "is-missing"}>{check.ready ? <CheckCircle2 /> : <Activity />}</span>
                <div><strong>{check.label}</strong><p>{check.detail}</p></div>
              </li>
            ))}
          </ul>
          <p className="system-runtime-verification">{data.deployment.runtime_verified ? "Container-Laufzeit erkannt und verifiziert." : "Docker-Dateien geprüft; ein echter Containerlauf ist auf diesem Host noch nicht verifiziert."}</p>
        </article>
      </section>

      <footer className="system-generated-at"><Clock3 className="size-4" /> Letzte vollständige Prüfung: {new Date(data.generated_at).toLocaleString("de-DE")}</footer>
    </section>
  );
}
